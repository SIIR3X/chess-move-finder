"""Entry point: listen to Chrome and draw the best move on the board.

Connects to a Chrome you started with remote debugging, follows the game (start,
moves, your colour) and puzzles, and whenever it's your turn asks Stockfish for the
best move (puzzles use their given solution) and draws it as an arrow on a
transparent overlay over the board. It resets on each new game.

Two launch modes:

* **console** (``python -m chess_move_finder``) - as before: prompts board
  calibration straight away, no window, logs to the console;
* **interface** (``python -m chess_move_finder --gui``) - opens a small dark
  **control panel** (:mod:`.gui.control_panel`) that toggles game and puzzle
  assistance, has a Calibrate button, and shows the logs; it does *not* auto-prompt
  calibration - you calibrate manually (until then the overlay stays blank).

The board's on-screen position is set by **calibration**: click its two corners
once. This is robust to multi-monitor and display scaling; re-calibrate if you move
the Chrome window.

Threads: Qt on the main thread; CDP listener on a background thread; game logic +
engine on a worker thread, plus a board poller (so none blocks the listen loop).

Run with Chrome already started with ``--remote-debugging-port=9222``. Set
``CMF_DEBUG_FRAMES=1`` to also log every raw WebSocket frame in full.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import logging
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chess
import yaml
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication

from .advisor import BestMoveFn, GameAdvisor
from .engine.stockfish import StockfishEngine
from .gui.arrow_window import ArrowOverlay
from .gui.calibration import CalibrationOverlay
from .gui.control_panel import ControlPanel, QtLogHandler
from .gui.overlay_controller import OverlayController
from .overlay.calibration_store import load_calibration
from .paths import bundled, config_dir, is_frozen
from .tracking.board_state import READ_BOARD_JS, parse_live_game
from .tracking.chesscom import GameSnapshot
from .tracking.chrome_cdp import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_URL_FILTER,
    ChromeCdpTracker,
)
from .tracking.game_stream import GameStream
from .tracking.puzzles import (
    NEXT_PUZZLE_URL,
    PuzzleSolver,
    parse_puzzle,
    placement_fen,
)

_CONFIG_PATH = config_dir() / "config.yaml"
_DEBUG_FRAMES_ENV = "CMF_DEBUG_FRAMES"
# A stable identity so Windows shows our taskbar icon, not python.exe's.
_APP_ID = "chessmovefinder.app"

logger = logging.getLogger("chess_move_finder")


def _app_icon() -> QIcon | None:
    """The app/window icon bundled with the app (.ico preferred), or None if absent."""
    for name in ("logo.ico", "logo.png"):
        path = bundled("assets", name)
        if path.exists():
            return QIcon(str(path))
    return None


def _ensure_config() -> None:
    """In a frozen build, seed an editable config next to the exe on first run."""
    if not is_frozen() or _CONFIG_PATH.exists():
        return
    with contextlib.suppress(OSError):
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_PATH.write_text(
            bundled("config", "config.yaml").read_text(encoding="utf-8"), encoding="utf-8"
        )


def _set_taskbar_identity() -> None:
    """Let Windows group the app under its own taskbar icon instead of python.exe."""
    if sys.platform != "win32":
        return
    with contextlib.suppress(Exception):  # not Windows-shell, or call unavailable
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_APP_ID)


@dataclass
class AssistanceState:
    """Live on/off switches for the two kinds of assistance (toggled from the GUI)."""

    games: bool = True
    puzzles: bool = True


class FrameWorker(threading.Thread):
    """Runs the game logic off the CDP loop, so analysis never blocks listening."""

    def __init__(self, handler: Callable[[str], None]) -> None:
        super().__init__(daemon=True)
        self._handler = handler
        self._queue: queue.Queue[str | None] = queue.Queue()

    def submit(self, payload: str) -> None:
        self._queue.put(payload)

    def stop(self) -> None:
        self._queue.put(None)
        self.join(timeout=2.0)

    def run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break
            try:
                self._handler(item)
            except Exception:
                logger.exception("frame handler error")


class BoardPoller(threading.Thread):
    """Reads the board off the page each tick and drives the overlay.

    Two jobs, told apart by the page and by whether a puzzle is loaded:

    * **puzzles** - match the live position to the known solution and show the move
      that's due (puzzles give no per-move network signal, so we must poll);
    * **live games, mid-game bootstrap** - when the move stream can't help (the
      colour wasn't announced and no fresh frame is coming), read the board's own
      FEN + orientation and ask the engine, so activating mid-game still suggests.

    Runs on its own thread so the blocking ``evaluate``/engine calls never touch the
    CDP loop or the GUI thread. ``ws_color_known`` (set when the move stream knows
    your colour) keeps the two paths from both driving live play at once.
    """

    def __init__(
        self,
        solver: PuzzleSolver,
        controller: OverlayController,
        best_move: BestMoveFn,
        ws_color_known: threading.Event,
        state: AssistanceState,
        interval_s: float,
    ) -> None:
        super().__init__(daemon=True)
        self._solver = solver
        self._controller = controller
        self._best_move = best_move
        self._ws_color_known = ws_color_known
        self._state = state
        self._interval = interval_s
        self._tracker: ChromeCdpTracker | None = None
        self._stop_event = threading.Event()  # not '_stop': Thread._stop is internal
        self._last_key: str | None = None  # dedupe across both modes

    def set_tracker(self, tracker: ChromeCdpTracker) -> None:
        self._tracker = tracker

    def reset(self) -> None:
        """Force the next read to be re-evaluated (e.g. a new puzzle just loaded)."""
        self._last_key = None

    def stop(self) -> None:
        self._stop_event.set()
        self.join(timeout=2.0)

    def run(self) -> None:
        while not self._stop_event.wait(self._interval):
            try:
                self._tick()
            except Exception:
                logger.exception("board poller error")

    def _tick(self) -> None:
        tracker = self._tracker
        if tracker is None:
            return
        state = tracker.evaluate(READ_BOARD_JS)
        if not isinstance(state, dict):
            return
        # Dropped the puzzles page with a puzzle still loaded: stop tracking it.
        if self._solver.is_loaded() and "puzzle" not in state.get("path", ""):
            self._solver.clear()
        if self._solver.is_loaded():
            if self._state.puzzles:
                self._tick_puzzle(state)
        elif self._state.games and not self._ws_color_known.is_set():
            self._tick_live(state)

    def _tick_puzzle(self, state: dict[str, Any]) -> None:
        pieces = state.get("pieces")
        if not isinstance(pieces, list):
            return
        placement = placement_fen([c for c in pieces if isinstance(c, str)])
        if placement is None or placement == self._last_key:
            return
        self._last_key = placement
        result = self._solver.suggestion_for(placement)
        if result is None:
            return  # position matches no ply (mid-animation): leave the overlay as-is
        board, move = result
        self._controller.on_suggestion(board, move)

    def _tick_live(self, state: dict[str, Any]) -> None:
        live = parse_live_game(state)
        if live is None:
            return
        key = f"live:{live.board.fen()}"
        if key == self._last_key:
            return
        self._last_key = key
        self._controller.set_color("black" if live.user_color == chess.BLACK else "white")
        if live.board.turn == live.user_color:
            self._controller.on_suggestion(live.board, self._best_move(live.board))
        else:
            self._controller.clear()  # opponent to move: nothing to show


class StatusMonitor(threading.Thread):
    """Polls whether Chrome's debug port is reachable and reports it to the panel."""

    def __init__(
        self, host: str, port: int, report: Callable[[bool], None], interval_s: float = 1.5
    ) -> None:
        super().__init__(daemon=True)
        self._host = host
        self._port = port
        self._report = report
        self._interval = interval_s
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()
        self.join(timeout=2.0)

    def run(self) -> None:
        while True:
            try:
                self._report(_chrome_port_open(self._host, self._port))
            except Exception:
                logger.exception("status monitor error")
            if self._stop_event.wait(self._interval):
                break


def _load_config() -> dict[str, Any]:
    try:
        with _CONFIG_PATH.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except OSError:
        return {}
    return data if isinstance(data, dict) else {}


def _section(cfg: dict[str, Any], name: str) -> dict[str, Any]:
    section = cfg.get(name, {})
    return section if isinstance(section, dict) else {}


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() not in ("", "0", "false", "no")


def _persist_stockfish_path(path: str) -> None:
    """Write the chosen Stockfish path back to config.yaml, keeping comments intact."""
    try:
        text = _CONFIG_PATH.read_text(encoding="utf-8")
    except OSError:
        return
    quoted = '"' + path.replace("\\", "/").replace('"', '\\"') + '"'
    pattern = re.compile(r"(?m)^([ \t]*stockfish_path:)[ \t]*[^#\n]*(#.*)?$")

    def repl(match: re.Match[str]) -> str:
        comment = f"  {match.group(2)}" if match.group(2) else ""
        return f"{match.group(1)} {quoted}{comment}"

    if pattern.search(text):
        try:
            _CONFIG_PATH.write_text(pattern.sub(repl, text, count=1), encoding="utf-8")
        except OSError:
            logger.warning("Could not save the Stockfish path to %s", _CONFIG_PATH)


def _find_chrome(configured: str | None) -> str | None:
    """The configured Chrome path if it exists, else a common install location."""
    candidates = [configured] if configured else []
    candidates += [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    return next((c for c in candidates if c and Path(c).exists()), None)


def _chrome_port_open(host: str, port: int) -> bool:
    """Whether Chrome's DevTools endpoint answers (i.e. it was started with the port)."""
    try:
        with urllib.request.urlopen(  # noqa: S310 (localhost)
            f"http://{host}:{port}/json/version", timeout=1.0
        ):
            return True
    except OSError:
        return False


def _log_game_start(snapshot: GameSnapshot, color: str | None) -> None:
    clocks = "/".join(f"{c // 1000}s" for c in snapshot.clocks) if snapshot.clocks else "?"
    logger.info(
        "Game started %s - clocks %s - you play %s",
        snapshot.game_id,
        clocks,
        color or "unknown",
    )


def _no_engine(_board: chess.Board) -> chess.Move | None:
    return None


def _open_engine(engine_cfg: dict[str, Any]) -> StockfishEngine | None:
    threads = engine_cfg.get("threads", 1)
    hash_mb = engine_cfg.get("hash_mb", 16)
    try:
        engine = StockfishEngine(
            engine_cfg.get("stockfish_path", "stockfish"),
            engine_cfg.get("movetime_ms", 200),
            threads=threads,
            hash_mb=hash_mb,
        )
    except Exception as exc:  # binary missing, not executable, bad UCI handshake
        logger.warning("Stockfish unavailable (%s); running without analysis", exc)
        return None
    logger.info("Stockfish ready (threads=%s, hash=%sMB)", threads, hash_mb)
    return engine


def _make_on_frame(submit: Callable[[str], None], debug: bool) -> Callable[[str], None]:
    if not debug:
        return submit

    def on_frame(payload: str) -> None:
        logger.info("FRAME %s", payload)
        submit(payload)

    return on_frame


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="chess_move_finder",
        description="Overlay Stockfish's best move on your chess.com board.",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="open the control panel (toggles + manual calibration) instead of "
        "auto-prompting calibration in the console",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    # A double-clicked exe has no console and no args, so default to the GUI there.
    gui = args.gui or is_frozen()
    _ensure_config()
    cfg = _load_config()
    tracking_cfg = _section(cfg, "tracking")
    overlay_cfg = _section(cfg, "overlay")
    puzzles_cfg = _section(cfg, "puzzles")
    chrome_cfg = _section(cfg, "chrome")
    debug = _env_flag(_DEBUG_FRAMES_ENV)
    if debug:
        logger.info("Raw-frame debug logging enabled (%s)", _DEBUG_FRAMES_ENV)

    # Keep fractional display scaling exact, so the overlay lines up with the board.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    # Transient calibration/overlay windows come and go; we quit on panel close / Ctrl+C.
    app.setQuitOnLastWindowClosed(False)
    _set_taskbar_identity()  # must run before any window is shown (Windows)
    icon = _app_icon()
    if icon is not None:  # title bar + taskbar; harmless if no image is present
        app.setWindowIcon(icon)

    # GUI mode: assistance starts off and is enabled only once setup is complete.
    # Console mode: no panel, so assistance follows the config.
    if gui:
        state = AssistanceState(games=False, puzzles=False)
    else:
        state = AssistanceState(games=True, puzzles=puzzles_cfg.get("enabled", True))
    panel: ControlPanel | None = None
    monitor: StatusMonitor | None = None

    overlay = ArrowOverlay(
        tuple(overlay_cfg.get("arrow_color", [0, 200, 0])),
        overlay_cfg.get("arrow_thickness", 8),
    )
    controller = OverlayController(overlay)
    saved_calibration = load_calibration()
    controller.set_board_rect(saved_calibration)

    engine_cfg = _section(cfg, "engine")
    # The engine sits behind a holder so the GUI can swap it when the user picks a new
    # Stockfish path, without re-wiring the advisor/poller that capture ``best_move``.
    engine_box: dict[str, StockfishEngine | None] = {"engine": _open_engine(engine_cfg)}

    def best_move(board: chess.Board) -> chess.Move | None:
        engine = engine_box["engine"]
        return engine.best_move(board) if engine is not None else None

    def set_stockfish(path: str) -> None:
        new_engine = _open_engine({**engine_cfg, "stockfish_path": path})
        if new_engine is None:
            return  # _open_engine already logged why; keep the old engine
        old = engine_box["engine"]
        engine_box["engine"] = new_engine
        if old is not None:
            old.close()
        engine_cfg["stockfish_path"] = path
        _persist_stockfish_path(path)
        if panel is not None:
            panel.set_stockfish_status(True)

    def on_game_suggestion(board: chess.Board, move: chess.Move | None) -> None:
        if state.games:  # game assistance switch
            controller.on_suggestion(board, move)

    advisor = GameAdvisor(best_move=best_move, on_suggestion=on_game_suggestion)

    # Set while the move stream knows our colour (announced before the game). When
    # it doesn't - e.g. the tool is started mid-game - the poller bootstraps instead.
    ws_color_known = threading.Event()

    # Board poller: drives puzzles, and bootstraps live suggestions when activated
    # mid-game. The solution/colour arrive without a per-move signal, so we read the
    # board to overlay the next move.
    solver = PuzzleSolver()
    poller = BoardPoller(
        solver,
        controller,
        best_move,
        ws_color_known,
        state,
        max(50, int(puzzles_cfg.get("poll_interval_ms", 400))) / 1000,
    )

    def on_puzzle_response(_url: str, body: str) -> None:
        if not state.puzzles:  # puzzle assistance switch
            return
        puzzle = parse_puzzle(body)
        if puzzle is None or not solver.load(puzzle):
            return
        controller.set_color(puzzle.user_color)
        controller.clear()
        poller.reset()
        logger.info(
            "Puzzle loaded %s - you play %s - %d-move solution",
            puzzle.puzzle_id,
            puzzle.user_color,
            len(puzzle.solution),
        )

    # Keep references so calibration windows aren't garbage-collected mid-use.
    calibrators: list[CalibrationOverlay] = []

    def start_calibration() -> None:
        window = CalibrationOverlay()
        calibrators.append(window)

        def finished(rect: object) -> None:
            if rect is not None:
                controller.set_board_rect(rect)  # type: ignore[arg-type]
                logger.info("Board calibrated")
            controller.set_ready()  # prompt resolved (calibrated or kept): arrows allowed
            poller.reset()  # re-emit for the current position now that we can draw
            if panel is not None:
                panel.set_calibration_status(controller.is_calibrated())
            calibrators.remove(window)

        window.done.connect(finished)
        window.show()
        window.raise_()
        window.activateWindow()
        window.setFocus()

    def set_games(on: bool) -> None:
        state.games = on
        logger.info("Game assistance %s", "on" if on else "off")
        if not on:
            controller.clear()
        poller.reset()

    def set_puzzles(on: bool) -> None:
        state.puzzles = on
        logger.info("Puzzle assistance %s", "on" if on else "off")
        if not on:
            solver.clear()
            controller.clear()
        poller.reset()

    def launch_chrome() -> None:
        chrome = _find_chrome(chrome_cfg.get("path"))
        if chrome is None:
            logger.warning("Chrome not found; set chrome.path in config.yaml")
            return
        port = tracking_cfg.get("port", DEFAULT_PORT)
        user_dir = chrome_cfg.get("user_data_dir", "C:/chess-profile")
        try:
            subprocess.Popen(
                [chrome, f"--remote-debugging-port={port}", f"--user-data-dir={user_dir}"]
            )
            logger.info("Launched Chrome (debug port %s, profile %s)", port, user_dir)
        except OSError as exc:
            logger.warning("Could not launch Chrome: %s", exc)

    chrome_host = tracking_cfg.get("host", DEFAULT_HOST)
    chrome_port = tracking_cfg.get("port", DEFAULT_PORT)

    if gui:
        # Interface mode: show the panel, no auto-calibration. The user works through the
        # setup (each step shows a status dot); assistance unlocks only once all are green.
        panel = ControlPanel(
            games_on=state.games,
            puzzles_on=state.puzzles,
            stockfish_path=engine_cfg.get("stockfish_path", ""),
            chrome_port=chrome_port,
        )
        log_handler = QtLogHandler()
        log_handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
        log_handler.bridge.message.connect(panel.append_log)
        logger.addHandler(log_handler)
        panel.games_toggled.connect(set_games)
        panel.puzzles_toggled.connect(set_puzzles)
        panel.calibrate_requested.connect(start_calibration)
        panel.stockfish_chosen.connect(set_stockfish)
        panel.launch_chrome_requested.connect(launch_chrome)
        panel.closed.connect(app.quit)
        if saved_calibration is not None:
            controller.set_ready()  # reuse an existing calibration; no re-calibrate needed
        panel.set_stockfish_status(engine_box["engine"] is not None)
        panel.set_calibration_status(controller.is_calibrated())
        monitor = StatusMonitor(chrome_host, chrome_port, panel.chrome_status.emit)
        monitor.start()
        panel.show()
        logger.info("Control panel ready - calibrate the board to begin")
    else:
        # Console mode (no window): prompt calibration straight away, as before. The
        # saved calibration stays as a fallback if the user cancels with Esc.
        logger.info("Opening calibration prompt (Esc to keep the previous calibration)")
        QTimer.singleShot(0, start_calibration)

    def on_game_start(snapshot: GameSnapshot, color: str | None) -> None:
        _log_game_start(snapshot, color)
        solver.clear()  # leaving any puzzle behind: don't let it drive the overlay
        advisor.on_game_start(snapshot, color)
        if color is not None:  # move stream can drive; otherwise the poller bootstraps
            ws_color_known.set()
            controller.set_color(color)
            controller.clear()
        else:
            ws_color_known.clear()

    def on_move(uci: str) -> None:
        logger.info("Move played: %s", uci)
        if ws_color_known.is_set():  # else the poller owns the overlay; don't fight it
            controller.clear()
        advisor.on_move(uci)

    stream = GameStream(on_game_start=on_game_start, on_move=on_move)
    worker = FrameWorker(stream.feed)
    tracker = ChromeCdpTracker(
        on_status=lambda msg: logger.info("%s", msg),
        on_frame=_make_on_frame(worker.submit, debug),
        host=tracking_cfg.get("host", DEFAULT_HOST),
        port=tracking_cfg.get("port", DEFAULT_PORT),
        url_filter=tracking_cfg.get("url_filter", DEFAULT_URL_FILTER),
        on_http=on_puzzle_response,  # gated at runtime by the puzzle switch
        http_filters=(NEXT_PUZZLE_URL,),
    )

    worker.start()
    # The poller also bootstraps live games mid-game, so it runs even with puzzles off.
    poller.set_tracker(tracker)
    poller.start()
    cdp_thread = threading.Thread(target=tracker.run_forever, daemon=True)
    cdp_thread.start()

    # Make Ctrl+C work: SIGINT quits the app, and a periodic no-op timer lets the
    # Python interpreter run often enough to actually deliver the signal while the
    # Qt event loop is running.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    sigint_timer = QTimer()
    sigint_timer.timeout.connect(lambda: None)
    sigint_timer.start(200)
    try:
        app.exec()
    finally:
        tracker.stop()
        poller.stop()
        if monitor is not None:
            monitor.stop()
        worker.stop()
        if engine_box["engine"] is not None:
            engine_box["engine"].close()


if __name__ == "__main__":
    main()
