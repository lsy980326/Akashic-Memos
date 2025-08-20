import sys
import os
from PyQt5.QtWidgets import QDesktopWidget

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    return os.path.join(base_path, relative_path)

def get_screen_geometry():
    return QDesktopWidget().availableGeometry()

def center_window(widget):
    screen_geo = get_screen_geometry()
    widget_geo = widget.frameGeometry()
    center_point = screen_geo.center()
    widget_geo.moveCenter(center_point)
    widget.move(widget_geo.topLeft())
