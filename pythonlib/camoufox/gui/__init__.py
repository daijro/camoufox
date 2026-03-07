"""
Camouman - QML-based GUI for managing Camoufox versions
"""

import os

# Force Basic style before PySide6 import to avoid Breeze conflicts
os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"
os.environ["QT_QPA_PLATFORMTHEME"] = ""
os.environ["QT_STYLE_OVERRIDE"] = ""
os.environ["KDE_FULL_SESSION"] = ""
os.environ["DESKTOP_SESSION"] = ""

from .backend import main

__all__ = ['main']
