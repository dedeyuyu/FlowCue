# -*- coding: utf-8 -*-
import os
import re
import subprocess
import sys
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QTextEdit, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QTabWidget, QListWidget, QListWidgetItem, 
                             QMessageBox, QSplitter, QLineEdit, QAbstractItemView, 
                              QToolTip, QComboBox, QFrame, QDialog, QCheckBox, QScrollArea,
                             QInputDialog, QMenu)
from PyQt6.QtCore import Qt, pyqtSlot, QUrl, QTimer, QDateTime
from PyQt6.QtGui import QDesktopServices, QGuiApplication, QCursor, QPixmap
from models.project_model import ProjectModel
from services.text_processor import TextProcessor
from services.downloader import DownloadThread


class NoWheelComboBox(QComboBox):
    """禁用鼠标滚轮切换选项的下拉框，防止鼠标停留滚动时误改片段配置"""
    def wheelEvent(self, event):
        event.ignore()


def flip_image_horizontally_replace(file_path) -> Path:
    """
    将指定图片进行左右水平翻转（镜像），用翻转后的新图片替换原图：
    1. 读取原图并执行水平翻转，写入同目录下的临时新文件
    2. 显式删除原有的旧图片文件 (unlink)
    3. 将翻转后的新图片重命名为原图片的文件名（完全继承原文件名与扩展名）
    """
    import gc
    import time
    from PIL import Image, ImageOps

    path = Path(file_path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"图片文件不存在: {path}")

    ext = path.suffix.lower()
    valid_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
    if ext not in valid_exts:
        raise ValueError(f"仅支持翻转图片文件，当前格式不支持: {path.name}")

    with Image.open(path) as img:
        orig_format = img.format
        transposed = ImageOps.exif_transpose(img)
        flipped = transposed.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        flipped.load()

    tmp_path = path.with_name(f".flip_tmp_{int(time.time() * 1000)}_{os.getpid()}{path.suffix}")
    try:
        save_img = flipped
        if ext in (".jpg", ".jpeg"):
            if save_img.mode in ("RGBA", "LA", "P"):
                save_img = save_img.convert("RGB")
            save_img.save(tmp_path, format="JPEG", quality=95)
        elif ext == ".png":
            save_img.save(tmp_path, format="PNG")
        elif ext == ".webp":
            save_img.save(tmp_path, format="WEBP", quality=95)
        elif ext == ".bmp":
            if save_img.mode in ("RGBA", "LA", "P"):
                save_img = save_img.convert("RGB")
            save_img.save(tmp_path, format="BMP")
        else:
            save_img.save(tmp_path, format=orig_format or "PNG")

        if not tmp_path.exists() or tmp_path.stat().st_size == 0:
            raise RuntimeError("翻转后的新图片写入失败")

        gc.collect()
        if path.exists():
            path.unlink()
        tmp_path.rename(path)
        return path
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        raise


def encode_image_to_data_url(file_path) -> str:
    """读取图片文件并编码为 Base64 Data URL。"""
    import base64
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        return ""
    ext = path.suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp"
    }
    mime = mime_map.get(ext, "image/jpeg")
    try:
        raw = path.read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception:
        return ""
