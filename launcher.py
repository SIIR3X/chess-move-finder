"""Entry point for the packaged executable.

PyInstaller targets this file (``__main__.py`` can't be the entry directly because
of its relative imports). It just hands off to the real entry point.
"""

from chess_move_finder.__main__ import main

if __name__ == "__main__":
    main()
