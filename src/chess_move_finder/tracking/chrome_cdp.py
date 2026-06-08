r"""Talk to chess.com in your own Chrome over the DevTools Protocol.

This does **not** automate or drive the browser (no Selenium/WebDriver). It
attaches to a Chrome *you* started with remote debugging enabled and:

* **listens** to the WebSocket frames chess.com exchanges (forwarded to a
  callback), reconnecting on its own if the tab isn't there yet or the link drops;
* **evaluates** small read-only expressions in the page on demand
  (:meth:`evaluate`) - used to read where the board sits on screen.

Start Chrome with remote debugging - a dedicated profile directory is required,
since Chrome 136 ignores ``--remote-debugging-port`` on the default profile::

    chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\\chess-profile"

then log in to chess.com in that window once. Note that only one client can be
attached to a tab at a time, so close its DevTools panel while this runs.
"""

from __future__ import annotations

import asyncio
import base64
import itertools
import json
import urllib.request
from collections.abc import Callable
from typing import Any

import websockets

# Default Chrome remote-debugging endpoint.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9222
# Substring a tab's URL must contain for us to attach to it.
DEFAULT_URL_FILTER = "chess.com"
# How long to wait before retrying when no tab is found or the link drops.
_RETRY_SECONDS = 2.0
# How long to wait for a CDP command response before giving up.
_COMMAND_TIMEOUT = 5.0

FrameCallback = Callable[[str], None]
StatusCallback = Callable[[str], None]
# (url, response body) of an HTTP response whose URL matched a watched substring.
HttpCallback = Callable[[str, str], None]


def _noop(_payload: str) -> None:
    pass


def _noop_http(_url: str, _body: str) -> None:
    pass


class ChromeCdpTracker:
    """Attaches to a chess.com tab: forwards its frames and evaluates expressions."""

    def __init__(
        self,
        on_status: StatusCallback,
        on_frame: FrameCallback | None = None,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        url_filter: str = DEFAULT_URL_FILTER,
        on_http: HttpCallback | None = None,
        http_filters: tuple[str, ...] = (),
    ) -> None:
        self._on_status = on_status
        self._on_frame: FrameCallback = on_frame or _noop
        self._on_http: HttpCallback = on_http or _noop_http
        self._http_filters = http_filters
        self._host = host
        self._port = port
        self._url_filter = url_filter
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[None] | None = None
        self._ws: Any = None
        self._ids = itertools.count(2)  # id 1 is reserved for Network.enable
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._watched: dict[str, str] = {}  # requestId -> url, for bodies we want

    def set_on_frame(self, on_frame: FrameCallback) -> None:
        self._on_frame = on_frame

    # --- lifecycle (called from the owning thread) ---

    def run_forever(self) -> None:
        """Blocking: connect, listen, and reconnect until :meth:`stop`."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._task = self._loop.create_task(self._main())
        try:
            self._loop.run_until_complete(self._task)
        except asyncio.CancelledError:
            pass
        finally:
            self._loop.close()

    def stop(self) -> None:
        """Ask the listen loop to exit (thread-safe)."""
        loop, task = self._loop, self._task
        if loop is not None and task is not None:
            loop.call_soon_threadsafe(task.cancel)

    # --- commands (thread-safe; called from another thread) ---

    def evaluate(self, expression: str) -> Any:
        """Evaluate a JS expression in the page and return its value (or None)."""
        result = self._call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        if not isinstance(result, dict):
            return None
        inner = result.get("result")
        return inner.get("value") if isinstance(inner, dict) else None

    def _call(self, method: str, params: dict[str, Any]) -> Any:
        loop = self._loop
        if loop is None:
            return None
        try:
            future = asyncio.run_coroutine_threadsafe(self._command(method, params), loop)
            return future.result(timeout=_COMMAND_TIMEOUT)
        except Exception:  # not connected, timeout, or transport error
            return None

    async def _command(self, method: str, params: dict[str, Any]) -> Any:
        ws = self._ws
        if ws is None:
            raise ConnectionError("not connected")
        cmd_id = next(self._ids)
        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[cmd_id] = fut
        try:
            await ws.send(json.dumps({"id": cmd_id, "method": method, "params": params}))
            return await asyncio.wait_for(fut, timeout=_COMMAND_TIMEOUT)
        finally:
            self._pending.pop(cmd_id, None)

    # --- internals (run on the asyncio loop) ---

    async def _main(self) -> None:
        while True:
            ws_url = await asyncio.to_thread(self._debugger_url)
            if ws_url is None:
                self._on_status("Waiting for a chess.com tab")
                await asyncio.sleep(_RETRY_SECONDS)
                continue
            self._on_status("Connected to Chrome - listening for frames")
            try:
                await self._listen(ws_url)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # link dropped, tab closed, navigation
                self._on_status(f"Chrome link lost ({exc}); reconnecting")
                await asyncio.sleep(_RETRY_SECONDS)

    async def _listen(self, ws_url: str) -> None:
        async with websockets.connect(ws_url, max_size=None) as ws:
            self._ws = ws
            try:
                # Turn on network events so we receive the page's WebSocket frames.
                await ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
                async for raw in ws:
                    self._handle(raw)
            finally:
                self._ws = None
                self._watched.clear()
                self._fail_pending()

    def _fail_pending(self) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("disconnected"))
        self._pending.clear()

    def _handle(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return
        cmd_id = msg.get("id")
        if cmd_id is not None:  # a response to one of our commands
            fut = self._pending.get(cmd_id)
            if fut is not None and not fut.done():
                fut.set_result(msg.get("result"))
            return
        method = msg.get("method")
        params = msg.get("params", {})
        if method == "Network.webSocketFrameReceived":
            payload = params.get("response", {}).get("payloadData", "")
            if payload:
                self._on_frame(payload)
        elif method == "Network.responseReceived":
            self._note_response(params)
        elif method == "Network.loadingFinished":
            self._fetch_watched(params)

    def _note_response(self, params: dict[str, Any]) -> None:
        """Remember a request whose URL we want the body of, by request id."""
        if not self._http_filters:
            return
        url = params.get("response", {}).get("url", "")
        request_id = params.get("requestId")
        if isinstance(request_id, str) and any(f in url for f in self._http_filters):
            self._watched[request_id] = url

    def _fetch_watched(self, params: dict[str, Any]) -> None:
        """Once a watched request finishes, schedule reading its body off the loop."""
        request_id = params.get("requestId")
        if not isinstance(request_id, str):
            return
        url = self._watched.pop(request_id, None)
        loop = self._loop
        if url is not None and loop is not None:
            loop.create_task(self._read_body(request_id, url))

    async def _read_body(self, request_id: str, url: str) -> None:
        try:
            result = await self._command("Network.getResponseBody", {"requestId": request_id})
        except Exception:  # body evicted, disconnected, or timed out
            return
        if not isinstance(result, dict):
            return
        body = result.get("body", "")
        if result.get("base64Encoded"):
            try:
                body = base64.b64decode(body).decode("utf-8", "replace")
            except (ValueError, TypeError):
                return
        if body:
            self._on_http(url, body)

    def _debugger_url(self) -> str | None:
        """The WebSocket debugger URL of the first matching chess.com page, or None."""
        endpoint = f"http://{self._host}:{self._port}/json"
        try:
            with urllib.request.urlopen(endpoint, timeout=2) as resp:  # noqa: S310 (localhost)
                targets = json.loads(resp.read().decode())
        except (OSError, json.JSONDecodeError, ValueError):
            return None
        for target in targets:
            if target.get("type") == "page" and self._url_filter in (target.get("url") or ""):
                url = target.get("webSocketDebuggerUrl")
                return url if isinstance(url, str) else None
        return None
