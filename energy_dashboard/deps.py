"""Third-party and stdlib imports shared across the dashboard."""
import energy_dashboard.qt_env  # noqa: F401 — configures QT_API / Linux a11y logs
import os
import sys
import math
import shutil
import socket
import subprocess
import traceback
from pathlib import Path
import growattServer
import requests
import pandas as pd
import polars as pl
import numpy as np
import matplotlib
matplotlib.use('QtAgg')
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as _MplNavigationToolbar
from matplotlib.figure import Figure
from datetime import datetime, timedelta, time, timezone
import threading
import time as _time_mod
import queue
import sqlite3
import base64
import json
import html
import re
import weakref
import ipaddress

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QLineEdit, QPushButton, QRadioButton, QCheckBox,
    QTabWidget, QSplitter, QTreeWidget, QTreeWidgetItem, QTextEdit, QTextBrowser,
    QStatusBar, QFileDialog, QMessageBox, QButtonGroup, QSizePolicy,
    QHeaderView, QFrame, QSlider, QDoubleSpinBox, QSpinBox, QScrollArea,
    QTableWidget, QTableWidgetItem, QComboBox, QAbstractItemView, QTimeEdit,
    QAbstractSpinBox,
    QDialog, QDialogButtonBox, QMenu, QTabBar, QStyle, QStyleOptionTab,
    QStackedWidget, QSystemTrayIcon,
    QGraphicsDropShadowEffect, QGraphicsView, QGraphicsScene,
    QGraphicsPixmapItem, QGraphicsPolygonItem, QGraphicsPathItem,
)
from PySide6.QtCore import (
    Qt, QTime, QTimer, Signal, QObject, Slot, QSettings, QUrl, QPointF, QRectF,
    QSize, QEvent, QThread, QRunnable, QThreadPool,
)
from PySide6.QtGui import (
    QFont, QBrush, QColor, QPixmap, QDesktopServices, QFontMetrics,
    QPainter, QPen, QPainterPath, QLinearGradient, QCursor, QPalette, QIcon,
    QTextCursor, QTransform, QPolygonF,
)

__all__ = [n for n in globals() if not n.startswith("__")]
