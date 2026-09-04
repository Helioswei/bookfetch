"""PyInstaller entry point — launches the desktop shell (`bookfetch gui`).

Kept OUT of src/ so packaging never ships it; the console script
`bookfetch gui` remains the source-tree way to run the shell.
"""
import sys

from bookfetch.gui_app import run

if __name__ == "__main__":
    sys.exit(run(debug=False))
