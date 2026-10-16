"""Shared application artwork, also resolved inside the frozen application."""
from pathlib import Path
from PySide6.QtGui import QIcon

ASSETS=Path(__file__).with_name('assets')

def app_icon():
    return QIcon(str(ASSETS/'app-icon.ico'))
