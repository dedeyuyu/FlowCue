# -*- coding: utf-8 -*-
"""全局托管模块共用的导入与常量。"""
import json
import time
import shutil
import logging
from pathlib import Path

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox,
                             QDoubleSpinBox, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
                             QAbstractItemView, QTextEdit, QGroupBox, QSplitter)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor

logger = logging.getLogger(__name__)

GREEN, RED, YELLOW, BLUE, GRAY = "#DCFCE7", "#FEE2E2", "#FEF9C3", "#DBEAFE", "#F3F4F6"
