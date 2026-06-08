"""Read chess.com game and puzzle events live from your own Chrome.

This package attaches to a Chrome you started with remote debugging (the DevTools
Protocol) and turns its traffic into high-level events. Live games come over a
WebSocket (a game starting, each move played); puzzles come over an HTTP RPC
(:mod:`.puzzles`), with the whole solution up front. No browser automation
(Selenium/WebDriver) and no extension are involved: Chrome is yours, we only
listen (and read the board, never inject).
"""
