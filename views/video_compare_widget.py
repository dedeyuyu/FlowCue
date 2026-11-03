# -*- coding: utf-8 -*-
import os
import subprocess
import sys
import datetime
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QListWidget, QListWidgetItem,
    QSplitter, QComboBox, QFrame, QProgressBar,
    QMessageBox, QDoubleSpinBox, QCheckBox, QFileDialog, QApplication,
    QDialog, QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
)
from PyQt6.QtCore import Qt, QUrl, QRectF, pyqtSignal
from PyQt6.QtGui import (
    QColor, QFont, QDesktopServices, QPainter, QPen, QBrush, QLinearGradient
)

# Optional multimedia support - graceful fallback if not installed
_HAS_MULTIMEDIA = False
try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PyQt6.QtMultimediaWidgets import QVideoWidget
    _HAS_MULTIMEDIA = True
except ImportError:
    QMediaPlayer = None
    QAudioOutput = None
    QVideoWidget = None


class SegmentTimelineBar(QWidget):
    """Interactive visual timeline bar for adjusting a segment's [cut_in, cut_out] duration.

    Displays:
    - Red trimmed head zone [0, cut_in] (片头气口切除)
    - Blue/Green active kept zone [cut_in, cut_out] (保留有效片段)
    - Red trimmed tail zone [cut_out, duration] (片尾气口切除)
    - Recognized word blocks along the timeline
    - Draggable Cyan In-Handle (cut_in) and Yellow Out-Handle (cut_out)
    - White/Red Playhead indicator
    """

    cut_range_changed = pyqtSignal(float, float)  # (cut_in, cut_out)
    seek_requested = pyqtSignal(float)            # (time_sec)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(56)
        self.setMaximumHeight(68)
        self.setMouseTracking(True)

        self.duration = 0.0
        self.cut_in = 0.0
        self.cut_out = 0.0
        self.speech_start = 0.0
        self.speech_end = 0.0
        self.playhead = 0.0
        self.words = []

        self._dragging_mode = None  # "in", "out", "seek", None
        self._hover_mode = None
        self._margin_x = 14

    def set_timeline_data(
        self,
        duration: float,
        cut_in: float,
        cut_out: float,
        words: list = None,
        speech_start: float = 0.0,
        speech_end: float = 0.0,
    ):
        self.duration = max(0.0, float(duration or 0.0))
        self.cut_in = max(0.0, float(cut_in or 0.0))
        if self.duration > 0:
            self.cut_out = min(self.duration, float(cut_out if cut_out > self.cut_in else self.duration))
        else:
            self.cut_out = max(self.cut_in, float(cut_out or 0.0))
        self.speech_start = max(0.0, float(speech_start or 0.0))
        self.speech_end = max(0.0, float(speech_end or 0.0))
        self.words = words or []
        self.update()

    def set_playhead(self, position_sec: float):
        self.playhead = max(0.0, float(position_sec or 0.0))
        self.update()

    def _time_to_x(self, t: float) -> float:
        w = max(10, self.width() - 2 * self._margin_x)
        if self.duration <= 0.001:
            return float(self._margin_x)
        ratio = max(0.0, min(1.0, t / self.duration))
        return self._margin_x + ratio * w

    def _x_to_time(self, x: float) -> float:
        w = max(10, self.width() - 2 * self._margin_x)
        if self.duration <= 0.001:
            return 0.0
        ratio = max(0.0, min(1.0, (x - self._margin_x) / w))
        return round(ratio * self.duration, 3)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        painter.fillRect(rect, QColor("#1E293B"))

        track_x = self._margin_x
        track_w = max(10, rect.width() - 2 * self._margin_x)
        track_y = 8
        track_h = rect.height() - 22

        # Track background
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#0F172A"))
        painter.drawRoundedRect(QRectF(track_x, track_y, track_w, track_h), 5, 5)

        if self.duration <= 0.001:
            painter.setPen(QColor("#94A3B8"))
            painter.setFont(QFont("Segoe UI", 9))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "加载视频后在此拖拽调整【入场 / 出场】时长（自动切气口）")
            return

        x_in = self._time_to_x(self.cut_in)
        x_out = self._time_to_x(self.cut_out)

        # 1. Left trimmed breath zone [0, cut_in]
        if x_in > track_x + 1:
            painter.setBrush(QColor(239, 68, 68, 85))
            painter.drawRoundedRect(QRectF(track_x, track_y, x_in - track_x, track_h), 4, 4)

        # 2. Right trimmed breath zone [cut_out, duration]
        track_right = track_x + track_w
        if x_out < track_right - 1:
            painter.setBrush(QColor(239, 68, 68, 85))
            painter.drawRoundedRect(QRectF(x_out, track_y, track_right - x_out, track_h), 4, 4)

        # 3. Active kept region [cut_in, cut_out]
        active_w = max(2.0, x_out - x_in)
        grad = QLinearGradient(x_in, track_y, x_in, track_y + track_h)
        grad.setColorAt(0.0, QColor("#0284C7"))
        grad.setColorAt(1.0, QColor("#0369A1"))
        painter.setBrush(QBrush(grad))
        painter.drawRoundedRect(QRectF(x_in, track_y, active_w, track_h), 4, 4)

        # 4. Draw word blocks inside the track
        if self.words:
            word_y = track_y + track_h - 14
            word_h = 11
            painter.setFont(QFont("Segoe UI", 7))
            for w in self.words:
                ws = float(w.get("start", 0.0) or 0.0)
                we = float(w.get("end", ws) or ws)
                wx1 = self._time_to_x(ws)
                wx2 = max(wx1 + 3.0, self._time_to_x(we))
                is_trimmed = (we <= self.cut_in + 0.02) or (ws >= self.cut_out - 0.02)
                if is_trimmed:
                    painter.setBrush(QColor(248, 113, 113, 150))
                else:
                    painter.setBrush(QColor(56, 189, 248, 210))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(QRectF(wx1, word_y, wx2 - wx1, word_h), 2, 2)

        # 5. Draw time ruler ticks at bottom
        painter.setPen(QColor("#94A3B8"))
        painter.setFont(QFont("Segoe UI", 8))
        kept_dur = max(0.0, self.cut_out - self.cut_in)
        info_str = (
            f"🔵 入场: {self.cut_in:.2f}s   |   "
            f"🟡 出场: {self.cut_out:.2f}s   |   "
            f"⏱️ 保留时长: {kept_dur:.2f}s (原长 {self.duration:.2f}s)"
        )
        painter.drawText(
            QRectF(track_x, track_y + 2, track_w, 16),
            Qt.AlignmentFlag.AlignCenter,
            info_str,
        )

        # 6. Draw In-Handle (Cyan) and Out-Handle (Amber/Yellow)
        handle_w = 8
        # In-Handle
        in_color = QColor("#38BDF8") if self._hover_mode != "in" else QColor("#7DD3FC")
        painter.setBrush(in_color)
        painter.setPen(QPen(QColor("#0F172A"), 1))
        painter.drawRoundedRect(QRectF(x_in - handle_w / 2, track_y - 2, handle_w, track_h + 4), 3, 3)

        # Out-Handle
        out_color = QColor("#FACC15") if self._hover_mode != "out" else QColor("#FEF08A")
        painter.setBrush(out_color)
        painter.drawRoundedRect(QRectF(x_out - handle_w / 2, track_y - 2, handle_w, track_h + 4), 3, 3)

        # 7. Draw Playhead
        x_play = self._time_to_x(self.playhead)
        painter.setPen(QPen(QColor("#FFFFFF"), 2))
        painter.drawLine(int(x_play), track_y - 3, int(x_play), track_y + track_h + 3)

        # Bottom hint
        painter.setPen(QColor("#CBD5E1"))
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(
            QRectF(track_x, track_y + track_h + 1, track_w, 14),
            Qt.AlignmentFlag.AlignCenter,
            "💡 拖拽 🔵青色入点 / 🟡黄色出点 可微调片段时长（红色区域为自动切掉的前后气口），点击时间轴可跳转试听",
        )

    def mousePressEvent(self, event):
        if self.duration <= 0.001 or event.button() != Qt.MouseButton.LeftButton:
            return
        x = event.position().x()
        x_in = self._time_to_x(self.cut_in)
        x_out = self._time_to_x(self.cut_out)

        if abs(x - x_in) <= 10:
            self._dragging_mode = "in"
        elif abs(x - x_out) <= 10:
            self._dragging_mode = "out"
        else:
            self._dragging_mode = "seek"
            t = self._x_to_time(x)
            self.set_playhead(t)
            self.seek_requested.emit(t)

    def mouseMoveEvent(self, event):
        if self.duration <= 0.001:
            return
        x = event.position().x()
        if self._dragging_mode == "in":
            new_in = min(self._x_to_time(x), max(0.0, self.cut_out - 0.20))
            self.cut_in = max(0.0, new_in)
            self.update()
            self.cut_range_changed.emit(self.cut_in, self.cut_out)
            self.seek_requested.emit(self.cut_in)
        elif self._dragging_mode == "out":
            new_out = max(self._x_to_time(x), min(self.duration, self.cut_in + 0.20))
            self.cut_out = min(self.duration, new_out)
            self.update()
            self.cut_range_changed.emit(self.cut_in, self.cut_out)
            self.seek_requested.emit(max(self.cut_in, self.cut_out - 0.3))
        elif self._dragging_mode == "seek":
            t = self._x_to_time(x)
            self.set_playhead(t)
            self.seek_requested.emit(t)
        else:
            x_in = self._time_to_x(self.cut_in)
            x_out = self._time_to_x(self.cut_out)
            if abs(x - x_in) <= 10:
                self._hover_mode = "in"
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif abs(x - x_out) <= 10:
                self._hover_mode = "out"
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                self._hover_mode = None
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.update()

    def mouseReleaseEvent(self, event):
        self._dragging_mode = None


class VideoCompareWidget(QWidget):
    """Widget for comparing video segments against their known script text,
    trimming breath (气口) & adjusting segment duration on the timeline,
    deleting/replacing segments in a closed loop with FlowCue, and splicing final video + SRT.
    """

    videos_deleted = pyqtSignal()
    send_to_reels_requested = pyqtSignal(dict)  # Emits {"video_path", "srt_path", "manifest_path", "project_name", "words"}

    # Short button labels (top bar)
    BTN_TEXT_EXTRACT_ALL = "🚀 极速核对（单任务）"
    BTN_TEXT_SPLICE_EXPORT = "🎬 当前任务一键拼接"

    # Fallback breath padding defaults (used when no config manager is available)
    DEFAULT_PAD_BEFORE = 0.10
    DEFAULT_PAD_AFTER = 0.15

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project_model = None
        self.project_path = None
        self.config_manager = None
        self.video_report = None  # From VideoChecker
        self.current_segment_index = -1
        self._continuous_preview_active = False
        self._last_merged_result = None
        self._applied_cfg_pads = None  # (pad_before, pad_after) last applied from config
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet("""
            QWidget#video_compare_root {
                background-color: #FAF6F0;
            }
            QLabel {
                font-size: 13px;
                color: #5D4037;
            }
            QPushButton {
                background-color: #E0A96D;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 5px 10px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #D2904C;
            }
            QPushButton:pressed {
                background-color: #B87635;
            }
            QPushButton:disabled {
                background-color: #D7CCC8;
                color: #A1887F;
            }
            QListWidget {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                color: #5D4037;
                font-size: 12px;
                padding: 2px;
            }
            QListWidget::item {
                padding: 6px 4px;
                border-bottom: 1px solid #F5F5F5;
            }
            QListWidget::item:hover {
                background-color: #FFF8E1;
            }
            QListWidget::item:selected {
                background-color: #FFE0B2;
                color: #5D4037;
                font-weight: bold;
            }
            QComboBox, QDoubleSpinBox {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 3px 6px;
                font-size: 12px;
                color: #5D4037;
            }
            QComboBox:hover, QDoubleSpinBox:hover {
                border: 1px solid #E0A96D;
            }
            QProgressBar {
                background-color: #EFEBE9;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                text-align: center;
                font-size: 11px;
                color: #5D4037;
                height: 18px;
            }
            QProgressBar::chunk {
                background-color: #66BB6A;
                border-radius: 3px;
            }
        """)
        self.setObjectName("video_compare_root")

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 8, 10, 8)
        root_layout.setSpacing(6)

        # ═══════════════════════════════════════════════════════
        # AREA 1: Top Summary & High-Speed Pipeline Bar
        # ═══════════════════════════════════════════════════════
        summary_frame = QFrame()
        summary_frame.setStyleSheet("""
            QFrame {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 6px;
                padding: 4px;
            }
        """)
        summary_vbox = QVBoxLayout(summary_frame)
        summary_vbox.setContentsMargins(10, 6, 10, 6)
        summary_vbox.setSpacing(6)

        # Row 1: Statistics + Engine + Fast Concurrent Extract + Batch Replace + Batch Delete
        row1_layout = QHBoxLayout()
        row1_layout.setSpacing(10)

        self.lbl_total = QLabel("总片段: 0")
        self.lbl_total.setStyleSheet("font-weight: bold; font-size: 12px;")
        row1_layout.addWidget(self.lbl_total)

        self.lbl_checked = QLabel("✅ 已核对: 0")
        self.lbl_checked.setStyleSheet("font-weight: bold; color: #2E7D32; font-size: 12px;")
        row1_layout.addWidget(self.lbl_checked)

        self.lbl_unchecked = QLabel("⚪ 待核对: 0")
        self.lbl_unchecked.setStyleSheet("font-weight: bold; color: #F57F17; font-size: 12px;")
        row1_layout.addWidget(self.lbl_unchecked)

        self.lbl_missing = QLabel("❌ 缺失: 0")
        self.lbl_missing.setStyleSheet("font-weight: bold; color: #C62828; font-size: 12px;")
        row1_layout.addWidget(self.lbl_missing)

        self.lbl_marked_delete = QLabel("🗑️ 待删除: 0")
        self.lbl_marked_delete.setStyleSheet("font-weight: bold; color: #DC2626; font-size: 12px;")
        row1_layout.addWidget(self.lbl_marked_delete)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(110)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        row1_layout.addWidget(self.progress_bar)

        row1_layout.addStretch()

        row1_layout.addWidget(QLabel("🔊 引擎:"))
        self.combo_engine = QComboBox()
        self.combo_engine.addItem("Gladia 极速并发", "gladia")
        self.combo_engine.addItem("ElevenLabs", "elevenlabs")
        self.combo_engine.setFixedWidth(135)
        row1_layout.addWidget(self.combo_engine)

        self.btn_extract_all = QPushButton(self.BTN_TEXT_EXTRACT_ALL)
        self.btn_extract_all.setStyleSheet("""
            QPushButton {
                background-color: #0284C7;
                color: white;
                font-weight: bold;
                padding: 5px 12px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #0369A1; }
            QPushButton:disabled { background-color: #D7CCC8; color: #A1887F; }
        """)
        self.btn_extract_all.setToolTip(
            "极速核对当前任务的全部片段文案（自动归位新视频后重新核对）：\n"
            "• FFmpeg 毫秒级提取 16kHz 轻量音频上传（提速 10 倍）\n"
            "• 多 Key 分段并行（分段并行数见「全任务一键核对」设置，每个 Key 最多 3 个并发）+ 本地缓存秒读\n"
            "• 逐句核对已知字幕并自动切除片头/片尾多余气口"
        )
        self.btn_extract_all.clicked.connect(self.extract_all_texts)
        row1_layout.addWidget(self.btn_extract_all)

        self.btn_batch_verify_all_tasks = QPushButton("📚 全任务一键核对")
        self.btn_batch_verify_all_tasks.setStyleSheet("""
            QPushButton {
                background-color: #7C3AED;
                color: white;
                font-weight: bold;
                padding: 5px 12px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #6D28D9; }
            QPushButton:disabled { background-color: #D7CCC8; color: #A1887F; }
        """)
        self.btn_batch_verify_all_tasks.setToolTip(
            "批量核对所有 FlowCue 任务的文案与自动气口剪切\n"
            "• 任务并行数 1~4 × 分段并行数 1~40（理论最大 160 并发）\n"
            "• 实际并发受 Gladia Key 数量限制：每个 Key 最多 3 个并发请求，不足时自动降低并行度\n"
            "• 自动归位待归位视频、识别西语数字与单词等价匹配、自动切除气口"
        )
        self.btn_batch_verify_all_tasks.clicked.connect(self.open_batch_all_tasks_verify_dialog)
        row1_layout.addWidget(self.btn_batch_verify_all_tasks)

        self.btn_delete_marked = QPushButton("🗑️ 一键删除标记视频")
        self.btn_delete_marked.setObjectName("btn_delete_marked")
        self.btn_delete_marked.setStyleSheet("""
            QPushButton#btn_delete_marked {
                background-color: #DC2626;
                color: white;
                font-weight: bold;
                padding: 5px 12px;
                border-radius: 4px;
            }
            QPushButton#btn_delete_marked:hover { background-color: #B91C1C; }
            QPushButton#btn_delete_marked:disabled { background-color: #D7CCC8; color: #A1887F; }
        """)
        self.btn_delete_marked.clicked.connect(self.batch_delete_marked_videos)
        self.btn_delete_marked.setEnabled(False)
        row1_layout.addWidget(self.btn_delete_marked)

        summary_vbox.addLayout(row1_layout)

        # Row 2: Breath Padding Config (前留白 / 后留白) + Splice & Send to Batch Reels
        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(8)

        lbl_breath = QLabel("✂️ 自动切气口留白:")
        lbl_breath.setStyleSheet("font-weight: bold; color: #475569; font-size: 12px;")
        row2_layout.addWidget(lbl_breath)

        row2_layout.addWidget(QLabel("前留白:"))
        self.spin_pad_before = QDoubleSpinBox()
        self.spin_pad_before.setRange(0.0, 2.0)
        self.spin_pad_before.setSingleStep(0.05)
        self.spin_pad_before.setDecimals(2)
        self.spin_pad_before.setValue(self.DEFAULT_PAD_BEFORE)
        self.spin_pad_before.setSuffix(" s")
        self.spin_pad_before.setFixedWidth(72)
        self.spin_pad_before.setToolTip("每个视频片段第一句发音前保留的气口缓冲时间（默认值可在「⚙️ 规则设置」中修改，出厂 0.10 秒）")
        row2_layout.addWidget(self.spin_pad_before)

        row2_layout.addWidget(QLabel("后留白:"))
        self.spin_pad_after = QDoubleSpinBox()
        self.spin_pad_after.setRange(0.0, 2.0)
        self.spin_pad_after.setSingleStep(0.05)
        self.spin_pad_after.setDecimals(2)
        self.spin_pad_after.setValue(self.DEFAULT_PAD_AFTER)
        self.spin_pad_after.setSuffix(" s")
        self.spin_pad_after.setFixedWidth(72)
        self.spin_pad_after.setToolTip("每个视频片段最后发音结束后保留的气口缓冲时间（默认值可在「⚙️ 规则设置」中修改，出厂 0.15 秒）")
        row2_layout.addWidget(self.spin_pad_after)

        self.btn_recalc_breath = QPushButton("⚡ 应用留白重算全部切点")
        self.btn_recalc_breath.setStyleSheet("background-color: #6366F1; color: white; padding: 4px 10px;")
        self.btn_recalc_breath.setToolTip("根据上方设置的前留白/后留白秒数，立即重新计算所有已提取片段的入场和出场切点（无需重新消耗 API）")
        self.btn_recalc_breath.clicked.connect(self.recalculate_all_breath_cuts)
        row2_layout.addWidget(self.btn_recalc_breath)

        row2_layout.addStretch()

        self.btn_preview_all_timeline = QPushButton("🔗 跨片段联播预览")
        self.btn_preview_all_timeline.setStyleSheet("background-color: #8B5CF6; color: white; padding: 5px 12px;")
        self.btn_preview_all_timeline.setToolTip("从当前片段开始，按每个片段切除气口后的 [入场~出场] 区间无缝跳播预览整条时间线")
        self.btn_preview_all_timeline.clicked.connect(self.toggle_continuous_timeline_preview)
        row2_layout.addWidget(self.btn_preview_all_timeline)

        self.btn_splice_export = QPushButton(self.BTN_TEXT_SPLICE_EXPORT)
        self.btn_splice_export.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: white;
                font-weight: bold;
                padding: 5px 12px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #059669; }
            QPushButton:disabled { background-color: #D7CCC8; color: #A1887F; }
        """)
        self.btn_splice_export.setToolTip(
            "按时间线审核后的【入场~出场】时长裁切所有片段并无缝拼接导出成片 MP4 + 同步 SRT 字幕\n"
            "（自带 SHA-256 片段裁切缓存，只修改某一段时其余片段 0 秒复用）"
        )
        self.btn_splice_export.clicked.connect(self.export_spliced_video)
        row2_layout.addWidget(self.btn_splice_export)

        self.btn_batch_splice_all = QPushButton("📚 所有任务一键拼接")
        self.btn_batch_splice_all.setStyleSheet("""
            QPushButton {
                background-color: #0D9488;
                color: white;
                font-weight: bold;
                padding: 5px 12px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #0F766E; }
            QPushButton:disabled { background-color: #D7CCC8; color: #A1887F; }
        """)
        self.btn_batch_splice_all.setToolTip(
            "弹窗勾选需要拼接的多个（或全部）任务，最多 4 个任务并行完成合并拼接（+SRT与逐词时间轴），\n"
            "并全部一键送入【🎬 批量Reels】批量设置字幕与覆层预设"
        )
        self.btn_batch_splice_all.clicked.connect(self.open_batch_all_tasks_splice_dialog)
        row2_layout.addWidget(self.btn_batch_splice_all)

        summary_vbox.addLayout(row2_layout)
        root_layout.addWidget(summary_frame)

        # ═══════════════════════════════════════════════════════
        # AREA 2: Left · Center · Right 3-Column Horizontal Splitter
        # 左: 句段列表 | 中: 视频预览 + 时间线拖拽条 | 右: 播放/入场出场控制 + 对比文案 + 核对操作
        # ═══════════════════════════════════════════════════════
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # ─── LEFT COLUMN: Segment Navigation List (左边：句段列表) ───
        left_widget = QWidget()
        left_widget.setMinimumWidth(200)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("句段列表:"))
        filter_layout.addStretch()

        self.combo_filter = QComboBox()
        self.combo_filter.addItem("全部", "all")
        self.combo_filter.addItem("✅ 已归位", "relocated")
        self.combo_filter.addItem("⚪ 待核对", "unchecked")
        self.combo_filter.addItem("🟢 已核对", "checked")
        self.combo_filter.addItem("🔴 差异告警", "flagged")
        self.combo_filter.addItem("🗑️ 待删除", "marked_delete")
        self.combo_filter.addItem("❌ 缺失", "missing")
        self.combo_filter.setFixedWidth(115)
        self.combo_filter.currentIndexChanged.connect(self.apply_filter)
        filter_layout.addWidget(self.combo_filter)

        left_layout.addLayout(filter_layout)

        self.list_segments = QListWidget()
        self.list_segments.currentRowChanged.connect(self.on_segment_selected)
        left_layout.addWidget(self.list_segments, stretch=1)

        self.btn_refresh = QPushButton("🔄 刷新状态")
        self.btn_refresh.clicked.connect(self.refresh_data)
        left_layout.addWidget(self.btn_refresh)

        main_splitter.addWidget(left_widget)

        # ─── CENTER COLUMN: Video Player + Visual Timeline Bar (中间：视频与时间线) ───
        center_widget = QWidget()
        center_widget.setMinimumWidth(260)
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(2, 0, 2, 0)
        center_layout.setSpacing(6)

        if _HAS_MULTIMEDIA:
            self.video_widget = QVideoWidget()
            self.video_widget.setMinimumHeight(240)
            self.video_widget.setStyleSheet("background-color: #1A1A2E; border-radius: 6px;")
            center_layout.addWidget(self.video_widget, stretch=1)

            self.media_player = QMediaPlayer()
            self.audio_output = QAudioOutput()
            self.media_player.setAudioOutput(self.audio_output)
            self.media_player.setVideoOutput(self.video_widget)
        else:
            self.video_widget = None
            self.media_player = None
            self.audio_output = None

            self._video_placeholder = QLabel("🎬 视频预览区域\n\n需安装 PyQt6-Multimedia 以启用内嵌播放器\n点击右侧 [📂 打开] 使用系统播放器")
            self._video_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._video_placeholder.setMinimumHeight(240)
            self._video_placeholder.setStyleSheet("""
                QLabel {
                    background-color: #1A1A2E;
                    color: #A1887F;
                    border-radius: 6px;
                    font-size: 13px;
                    padding: 20px;
                }
            """)
            center_layout.addWidget(self._video_placeholder, stretch=1)

        # Visual Timeline Bar under Video in Center Column
        self.timeline_bar = SegmentTimelineBar()
        self.timeline_bar.cut_range_changed.connect(self._on_timeline_bar_cut_changed)
        self.timeline_bar.seek_requested.connect(self._on_timeline_bar_seek)
        center_layout.addWidget(self.timeline_bar)

        self.lbl_video_info = QLabel("未选择视频文件")
        self.lbl_video_info.setStyleSheet("font-size: 11px; color: #A1887F; font-weight: normal; font-style: italic;")
        center_layout.addWidget(self.lbl_video_info)

        main_splitter.addWidget(center_widget)

        # ─── RIGHT COLUMN: Play & In/Out Controls + Text Comparison + Actions (右边：播放/入场出场控制 + 对比文案) ───
        right_widget = QWidget()
        right_widget.setMinimumWidth(360)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(2, 0, 0, 0)
        right_layout.setSpacing(6)

        # Top Control Box in Right Column (Play buttons + In/Out duration controls)
        controls_frame = QFrame()
        controls_frame.setStyleSheet("""
            QFrame {
                background-color: #EFEBE9;
                border: 1px solid #D7CCC8;
                border-radius: 6px;
                padding: 4px 6px;
            }
        """)
        controls_vbox = QVBoxLayout(controls_frame)
        controls_vbox.setContentsMargins(6, 6, 6, 6)
        controls_vbox.setSpacing(6)

        # Row 1 of Right Controls: Play button, time, trimmed-only toggle, speed, open, external player
        play_row = QHBoxLayout()
        play_row.setSpacing(6)

        self.btn_play = QPushButton("▶ 播放")
        self.btn_play.setFixedWidth(78)
        self.btn_play.clicked.connect(self.toggle_play)
        play_row.addWidget(self.btn_play)

        self.lbl_video_time = QLabel("00:00 / 00:00")
        self.lbl_video_time.setStyleSheet("font-size: 12px; color: #5D4037; font-weight: bold;")
        play_row.addWidget(self.lbl_video_time)

        self.chk_play_trimmed_only = QCheckBox("仅播保留段")
        self.chk_play_trimmed_only.setChecked(True)
        self.chk_play_trimmed_only.setToolTip("勾选后，播放时自动从【入场】开始并在【出场】结束，直观预览切除气口后的效果")
        self.chk_play_trimmed_only.setStyleSheet("font-size: 12px; color: #0284C7; font-weight: bold;")
        play_row.addWidget(self.chk_play_trimmed_only)

        play_row.addStretch()

        play_row.addWidget(QLabel("⚙"))
        self.combo_speed = QComboBox()
        self.combo_speed.addItem("0.5x", 0.5)
        self.combo_speed.addItem("1.0x", 1.0)
        self.combo_speed.addItem("1.25x", 1.25)
        self.combo_speed.addItem("1.5x", 1.5)
        self.combo_speed.addItem("2.0x", 2.0)
        self.combo_speed.setCurrentIndex(1)
        self.combo_speed.setFixedWidth(68)
        self.combo_speed.currentIndexChanged.connect(self.change_speed)
        play_row.addWidget(self.combo_speed)

        self.btn_open_file = QPushButton("📂 打开")
        self.btn_open_file.setFixedWidth(68)
        self.btn_open_file.setStyleSheet("background-color: #D7CCC8; color: #5D4037;")
        self.btn_open_file.clicked.connect(self.open_current_video_file)
        play_row.addWidget(self.btn_open_file)

        self.btn_play_external = QPushButton("▶ 外部播放")
        self.btn_play_external.setFixedWidth(86)
        self.btn_play_external.setStyleSheet("background-color: #7E57C2; color: white;")
        self.btn_play_external.clicked.connect(self.play_external)
        play_row.addWidget(self.btn_play_external)

        controls_vbox.addLayout(play_row)

        # Row 2 of Right Controls: In/Out Spinboxes + Kept Duration + Reset AI Breath Cut
        inout_row = QHBoxLayout()
        inout_row.setSpacing(6)

        inout_row.addWidget(QLabel("🔵入场:"))
        self.spin_cut_in = QDoubleSpinBox()
        self.spin_cut_in.setRange(0.0, 600.0)
        self.spin_cut_in.setSingleStep(0.05)
        self.spin_cut_in.setDecimals(2)
        self.spin_cut_in.setSuffix("s")
        self.spin_cut_in.setFixedWidth(78)
        self.spin_cut_in.valueChanged.connect(self._on_spin_cut_changed)
        inout_row.addWidget(self.spin_cut_in)

        inout_row.addWidget(QLabel("🟡出场:"))
        self.spin_cut_out = QDoubleSpinBox()
        self.spin_cut_out.setRange(0.0, 600.0)
        self.spin_cut_out.setSingleStep(0.05)
        self.spin_cut_out.setDecimals(2)
        self.spin_cut_out.setSuffix("s")
        self.spin_cut_out.setFixedWidth(78)
        self.spin_cut_out.valueChanged.connect(self._on_spin_cut_changed)
        inout_row.addWidget(self.spin_cut_out)

        self.lbl_kept_duration = QLabel("保留: 0.00s")
        self.lbl_kept_duration.setStyleSheet("font-size: 12px; font-weight: bold; color: #0F766E;")
        inout_row.addWidget(self.lbl_kept_duration)

        inout_row.addStretch()

        self.btn_reset_cut = QPushButton("↺ 恢复AI气口")
        self.btn_reset_cut.setToolTip("将当前片段的入场/出场时间恢复为 AI 识别的默认气口切点")
        self.btn_reset_cut.setStyleSheet("background-color: #64748B; color: white; padding: 4px 10px; font-size: 11px;")
        self.btn_reset_cut.clicked.connect(self.reset_current_segment_breath_cut)
        inout_row.addWidget(self.btn_reset_cut)

        controls_vbox.addLayout(inout_row)
        right_layout.addWidget(controls_frame)

        # Segment Info Label
        self.lbl_segment_info = QLabel("请在左侧选择一个句段")
        self.lbl_segment_info.setStyleSheet("font-size: 13px; font-weight: bold; color: #5D4037; padding: 2px 0;")
        right_layout.addWidget(self.lbl_segment_info)

        # Text Comparison Splitter (Original vs AI Recognized)
        compare_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left column of text compare: Original Script
        left_compare = QWidget()
        left_compare_layout = QVBoxLayout(left_compare)
        left_compare_layout.setContentsMargins(0, 0, 3, 0)
        left_compare_layout.setSpacing(4)

        lbl_original_header = QLabel("📝 已知目标字幕 (可双击工作台修改)")
        lbl_original_header.setStyleSheet("font-weight: bold; font-size: 13px; color: #5D4037; background-color: #EFEBE9; padding: 4px 8px; border-radius: 4px;")
        left_compare_layout.addWidget(lbl_original_header)

        self.txt_original = QTextEdit()
        self.txt_original.setReadOnly(True)
        self.txt_original.setPlaceholderText("原始文案将显示在这里...")
        self.txt_original.setStyleSheet("""
            QTextEdit {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                font-family: "Segoe UI", sans-serif;
                font-size: 13px;
                color: #3E2723;
                padding: 8px;
            }
        """)
        left_compare_layout.addWidget(self.txt_original)
        compare_splitter.addWidget(left_compare)

        # Right column of text compare: Extracted Text
        right_compare = QWidget()
        right_compare_layout = QVBoxLayout(right_compare)
        right_compare_layout.setContentsMargins(3, 0, 0, 0)
        right_compare_layout.setSpacing(4)

        lbl_extracted_header = QLabel("🔊 AI 识别核对结果 (标红=错读 / 橙色=漏词 / 绿色=多读)")
        lbl_extracted_header.setStyleSheet("font-weight: bold; font-size: 13px; color: #5D4037; background-color: #E3F2FD; padding: 4px 8px; border-radius: 4px;")
        right_compare_layout.addWidget(lbl_extracted_header)

        self.txt_extracted = QTextEdit()
        self.txt_extracted.setReadOnly(True)
        self.txt_extracted.setPlaceholderText("AI 提取的文案将显示在这里...\n\n点击上方「🚀 极速核对（单任务）」或「📚 全任务一键核对」即可并发核对并自动切除首尾气口。")
        self.txt_extracted.setStyleSheet("""
            QTextEdit {
                background-color: #FAFAFA;
                border: 1px solid #BBDEFB;
                border-radius: 4px;
                font-family: "Segoe UI", sans-serif;
                font-size: 13px;
                color: #3E2723;
                padding: 8px;
            }
        """)
        right_compare_layout.addWidget(self.txt_extracted)
        compare_splitter.addWidget(right_compare)
        compare_splitter.setSizes([280, 280])

        right_layout.addWidget(compare_splitter, stretch=1)

        # Similarity score & Streamlined 3 Core Actions Bar (调整时长 / 替换重跑核对 / 直接删除)
        action_layout = QHBoxLayout()
        action_layout.setSpacing(6)

        self.lbl_similarity = QLabel("相似度: —")
        self.lbl_similarity.setStyleSheet("font-size: 13px; font-weight: bold; color: #8D6E63; padding: 2px 4px;")
        action_layout.addWidget(self.lbl_similarity)

        action_layout.addStretch()

        # Core Action: Replace / Re-verify current segment (自动归位新生成的视频并重新核对切气口)
        self.btn_extract_single = QPushButton("🔄 替换 / 重新核对本段")
        self.btn_extract_single.setStyleSheet("background-color: #0D9488; color: white; padding: 6px 10px;")
        self.btn_extract_single.setEnabled(False)
        self.btn_extract_single.setToolTip(
            "【时间线核心操作：替换】\n"
            "• 如果您刚用 JSON 重新生成了这一段的新视频，点击即可自动将新视频归位替换老视频，并重新跑一遍 AI 核对与气口剪切！\n"
            "• 如果视频已在本地，点击将强制重新跑一遍本段 AI 语音核对与气口剪切。"
        )
        self.btn_extract_single.clicked.connect(self.replace_or_reverify_current_segment)
        action_layout.addWidget(self.btn_extract_single)

        # Core Action: Direct Delete current wrong video (直接删除错误视频，方便直接复制 JSON 重新生成)
        self.btn_delete_single_now = QPushButton("🗑️ 直接删除此视频")
        self.btn_delete_single_now.setStyleSheet("background-color: #DC2626; color: white; padding: 6px 10px;")
        self.btn_delete_single_now.setToolTip(
            "【时间线核心操作：删除】\n"
            "发现当前片段字幕错了或画面不对时，一键删除当前错误视频并重置为【❌ 缺失】状态。\n"
            "删除后可直接复制 JSON 重新生成新视频，生成完再点左侧【🔄 替换 / 重新核对本段】即可！"
        )
        self.btn_delete_single_now.clicked.connect(self.delete_current_segment_video_immediately)
        action_layout.addWidget(self.btn_delete_single_now)

        self.btn_mark_checked = QPushButton("✅ 标记核对无误")
        self.btn_mark_checked.setStyleSheet("background-color: #10B981; color: white; padding: 6px 10px;")
        self.btn_mark_checked.clicked.connect(self.mark_checked)
        action_layout.addWidget(self.btn_mark_checked)

        self.btn_mark_unchecked = QPushButton("↩ 取消核对")
        self.btn_mark_unchecked.setStyleSheet("background-color: #B0BEC5; color: #37474F; padding: 6px 8px;")
        self.btn_mark_unchecked.clicked.connect(self.mark_unchecked)
        action_layout.addWidget(self.btn_mark_unchecked)

        self.btn_mark_delete = QPushButton("🚩 标记待删")
        self.btn_mark_delete.setObjectName("btn_mark_delete")
        self.btn_mark_delete.setStyleSheet("""
            QPushButton#btn_mark_delete {
                background-color: #F97316;
                color: white;
                padding: 6px 8px;
            }
            QPushButton#btn_mark_delete:hover {
                background-color: #EA580C;
            }
        """)
        self.btn_mark_delete.setToolTip("先打上待删除标记，稍后可用顶部【🗑️ 一键删除标记视频】批量清理")
        self.btn_mark_delete.clicked.connect(self.toggle_mark_delete)
        action_layout.addWidget(self.btn_mark_delete)

        right_layout.addLayout(action_layout)

        main_splitter.addWidget(right_widget)

        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setStretchFactor(2, 2)
        main_splitter.setSizes([230, 380, 560])
        root_layout.addWidget(main_splitter, stretch=1)

        if _HAS_MULTIMEDIA and self.media_player:
            self.media_player.positionChanged.connect(self.update_position)
            self.media_player.durationChanged.connect(self.update_duration)
            self.media_player.playbackStateChanged.connect(self.update_play_button)

        self._current_video_path = None
        self._duration_ms = 0

    # ═══════════════════════════════════════════════════════
    # PUBLIC: Set project data
    # ═══════════════════════════════════════════════════════
    def set_project(self, project_model, project_path, config_manager=None):
        """Called when project is loaded/changed. Populates all data."""
        self.cleanup()
        self.project_model = project_model
        self.project_path = Path(project_path) if project_path else None
        self.config_manager = config_manager
        self.current_segment_index = -1
        self._current_video_path = None
        self._last_merged_result = None
        self._sync_pad_defaults_from_config()

        self.refresh_data()

    def _get_cfg_pad_defaults(self):
        """Returns (pad_before, pad_after) defaults from 规则设置 (config), or built-in fallbacks."""
        cfg = self.config_manager
        if cfg is None:
            main_win = self.window()
            cfg = getattr(main_win, "config_manager", None) if main_win is not self else None
        pb = getattr(cfg, "breath_pad_before", self.DEFAULT_PAD_BEFORE) if cfg is not None else self.DEFAULT_PAD_BEFORE
        pa = getattr(cfg, "breath_pad_after", self.DEFAULT_PAD_AFTER) if cfg is not None else self.DEFAULT_PAD_AFTER
        try:
            return round(float(pb), 3), round(float(pa), 3)
        except (TypeError, ValueError):
            return self.DEFAULT_PAD_BEFORE, self.DEFAULT_PAD_AFTER

    def _sync_pad_defaults_from_config(self):
        """Applies the 规则设置 前留白/后留白 defaults to the spinboxes when they changed in config.
        Session tweaks made directly in this tab are kept until the configured defaults change."""
        if not hasattr(self, "spin_pad_before") or not hasattr(self, "spin_pad_after"):
            return
        pads = self._get_cfg_pad_defaults()
        if pads != self._applied_cfg_pads:
            self.spin_pad_before.setValue(pads[0])
            self.spin_pad_after.setValue(pads[1])
            self._applied_cfg_pads = pads

    def showEvent(self, event):
        super().showEvent(event)
        try:
            self._sync_pad_defaults_from_config()
        except Exception:
            pass

    def cleanup(self):
        """Stops media player and active background worker threads cleanly."""
        self._continuous_preview_active = False
        if hasattr(self, "btn_preview_all_timeline") and self.btn_preview_all_timeline:
            self.btn_preview_all_timeline.setText("🔗 跨片段联播预览")

        if hasattr(self, "media_player") and self.media_player:
            try:
                self.media_player.stop()
                self.media_player.setSource(QUrl())
            except Exception:
                pass

        if hasattr(self, "_extraction_worker") and self._extraction_worker:
            try:
                if self._extraction_worker.isRunning():
                    self._extraction_worker.stop()
            except Exception:
                pass
            self._extraction_worker = None

        if hasattr(self, "_splice_worker") and self._splice_worker:
            try:
                if self._splice_worker.isRunning():
                    self._splice_worker.cancel()
                    self._splice_worker.wait(2000)
            except Exception:
                pass
            self._splice_worker = None

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)

    def hideEvent(self, event):
        self._continuous_preview_active = False
        if hasattr(self, "media_player") and self.media_player:
            try:
                self.media_player.stop()
            except Exception:
                pass
        super().hideEvent(event)

    def _get_base_storage_path(self):
        main_win = self.window()
        if hasattr(main_win, "storage_manager") and main_win.storage_manager:
            return main_win.storage_manager.get_base_path()
        if self.project_path:
            return Path(self.project_path).parent
        return None

    def refresh_data(self):
        """Re-runs video check, updates similarity scores with Spanish number equivalence, and refreshes UI."""
        if not self.project_model or not self.project_path:
            self._clear_all()
            return

        from services.video_checker import VideoChecker
        from services.speech_extractor import SpeechExtractor

        # Recalculate similarity for already-extracted segments so Spanish number words (e.g. catorce <-> 14)
        # immediately reflect 100% equivalence without needing to re-call the API
        modified_sim = False
        for seg in (self.project_model.spanish_segments or []):
            ext_txt = seg.get("extracted_text", "")
            orig_txt = seg.get("text", "")
            if ext_txt and orig_txt:
                new_sim = SpeechExtractor.calculate_similarity(orig_txt, ext_txt)
                old_sim = float(seg.get("similarity_score", 0.0) or 0.0)
                if abs(new_sim - old_sim) >= 0.1:
                    seg["similarity_score"] = new_sim
                    if new_sim >= 90 and not seg.get("marked_for_deletion", False):
                        seg["checked"] = True
                        seg["auto_checked"] = True
                        seg["mismatch_flagged"] = False
                    modified_sim = True
        if modified_sim:
            try:
                self.project_model.save()
            except Exception:
                pass

        base_storage_path = self._get_base_storage_path()
        self.video_report = VideoChecker.check_project_videos(
            self.project_model, self.project_path,
            base_storage_path=base_storage_path
        )

        self._populate_segment_list()
        self._update_summary()

        if self.current_segment_index >= 0 and self.current_segment_index < self.list_segments.count():
            self.list_segments.setCurrentRow(self.current_segment_index)
        elif self.list_segments.count() > 0:
            self.list_segments.setCurrentRow(0)
        else:
            self._clear_detail()

    def _clear_all(self):
        """Clears all UI when no project is loaded."""
        self.list_segments.clear()
        self.lbl_total.setText("总片段: 0")
        self.lbl_checked.setText("✅ 已核对: 0")
        self.lbl_unchecked.setText("⚪ 待核对: 0")
        self.lbl_missing.setText("❌ 缺失: 0")
        self.lbl_marked_delete.setText("🗑️ 待删除: 0")
        if hasattr(self, "btn_delete_marked") and self.btn_delete_marked:
            self.btn_delete_marked.setEnabled(False)
            self.btn_delete_marked.setText("🗑️ 一键删除标记视频")
        self.progress_bar.setValue(0)
        self._clear_detail()

    def _clear_detail(self):
        """Clears the right detail panel."""
        self.txt_original.clear()
        self.txt_extracted.clear()
        self.lbl_segment_info.setText("请在左侧选择一个句段")
        self.lbl_similarity.setText("相似度: —")
        self.lbl_video_info.setText("未选择视频文件")
        self.lbl_video_time.setText("00:00 / 00:00")
        self.lbl_kept_duration.setText("时长: 0.00s")
        self.timeline_bar.set_timeline_data(0.0, 0.0, 0.0, [])
        if hasattr(self, "btn_mark_delete") and self.btn_mark_delete:
            self.btn_mark_delete.setText("🚩 标记待删")
            self.btn_mark_delete.setEnabled(False)
        if hasattr(self, "btn_delete_single_now") and self.btn_delete_single_now:
            self.btn_delete_single_now.setEnabled(False)
        if self.media_player:
            self.media_player.stop()
        self._current_video_path = None

    # ═══════════════════════════════════════════════════════
    # Populate segment list
    # ═══════════════════════════════════════════════════════
    def _populate_segment_list(self):
        """Fills the left segment navigation list from video_report."""
        self.list_segments.blockSignals(True)
        self.list_segments.clear()

        if not self.video_report:
            self.list_segments.blockSignals(False)
            return

        segments = self.project_model.spanish_segments if self.project_model else []
        details = self.video_report.get("segments_detail", [])
        current_filter = self.combo_filter.currentData()

        for i, detail in enumerate(details):
            seg_data = segments[i] if i < len(segments) else {}

            is_found = detail.get("found", False)
            is_relocated = detail.get("already_in_target", False)
            is_missing = not is_found
            is_checked = seg_data.get("checked", False)
            is_marked_delete = seg_data.get("marked_for_deletion", False)
            is_flagged = seg_data.get("mismatch_flagged", False)
            similarity = seg_data.get("similarity_score", 0)
            has_extracted = bool(seg_data.get("extracted_text", ""))

            if current_filter == "marked_delete" and not is_marked_delete:
                continue
            elif current_filter == "relocated" and not is_relocated:
                continue
            elif current_filter == "unchecked" and (is_checked or is_missing):
                continue
            elif current_filter == "checked" and not is_checked:
                continue
            elif current_filter == "flagged" and not (is_flagged or (has_extracted and similarity < 70)):
                continue
            elif current_filter == "missing" and not is_missing:
                continue

            seq_num = detail.get("index", i + 1)
            text = detail.get("text", "")
            truncated = text[:28] + "..." if len(text) > 28 else text

            if is_marked_delete:
                video_icon = "🗑️"
                check_icon = "[待删]"
            elif is_missing:
                video_icon = "❌"
                check_icon = "—"
            elif is_relocated:
                video_icon = "✅"
                if is_checked:
                    check_icon = "🟢"
                elif is_flagged or (has_extracted and 0 < similarity < 70):
                    check_icon = "🔴"
                elif has_extracted and similarity >= 70:
                    check_icon = "🟡"
                else:
                    check_icon = "⚪"
            else:
                video_icon = "⚠️待归位"
                check_icon = "⚪"

            sim_label = f" ({similarity:.0f}%)" if has_extracted and similarity > 0 else ""
            cut_in = seg_data.get("cut_in")
            cut_out = seg_data.get("cut_out")
            dur_tag = ""
            if cut_in is not None and cut_out is not None and float(cut_out) > float(cut_in):
                dur_tag = f" [{float(cut_out) - float(cut_in):.1f}s]"

            label = f"{seq_num:02d} {video_icon}{check_icon} {truncated}{sim_label}{dur_tag}"

            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, i)

            from services.theme_manager import ThemeManager
            is_dark = ThemeManager.is_dark()
            if is_marked_delete:
                item.setForeground(QColor("#F87171" if is_dark else "#DC2626"))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            elif is_missing:
                item.setForeground(QColor("#F87171" if is_dark else "#C62828"))
            elif is_flagged or (has_extracted and 0 < similarity < 70):
                item.setForeground(QColor("#F87171" if is_dark else "#C62828"))
            elif is_checked:
                item.setForeground(QColor("#4ADE80" if is_dark else "#2E7D32"))
            elif is_relocated:
                item.setForeground(ThemeManager.get_default_item_fg())
            else:
                item.setForeground(QColor("#FBBF24" if is_dark else "#D97706"))

            self.list_segments.addItem(item)

        self.list_segments.blockSignals(False)

    def _update_summary(self):
        """Updates the top summary statistics bar."""
        if not self.video_report or not self.project_model:
            return

        segments = self.project_model.spanish_segments
        total = len(segments)
        checked_count = sum(1 for s in segments if s.get("checked", False))
        marked_delete_count = sum(1 for s in segments if s.get("marked_for_deletion", False))
        pending_relocate_count = self.video_report.get("pending_count", 0)

        missing = self.video_report.get("missing_count", 0)
        unchecked = max(0, total - checked_count - missing)

        self.lbl_total.setText(f"总片段: {total}")
        self.lbl_checked.setText(f"✅ 已核对: {checked_count}")
        self.lbl_unchecked.setText(f"⚪ 待核对: {unchecked}")
        self.lbl_missing.setText(f"❌ 缺失: {missing}")
        self.lbl_marked_delete.setText(f"🗑️ 待删除: {marked_delete_count}")

        if hasattr(self, "btn_delete_marked") and self.btn_delete_marked:
            self.btn_delete_marked.setEnabled(marked_delete_count > 0)
            if marked_delete_count > 0:
                self.btn_delete_marked.setText(f"🗑️ 一键删除标记 ({marked_delete_count})")
            else:
                self.btn_delete_marked.setText("🗑️ 一键删除标记视频")

        pct = int(checked_count / total * 100) if total > 0 else 0
        self.progress_bar.setValue(pct)
        self.progress_bar.setFormat(f"{pct}%")

    # ═══════════════════════════════════════════════════════
    # Segment selection & Timeline loading
    # ═══════════════════════════════════════════════════════
    def on_segment_selected(self, row):
        if row < 0:
            self._clear_detail()
            return

        item = self.list_segments.item(row)
        if not item:
            return

        real_index = item.data(Qt.ItemDataRole.UserRole)
        self.current_segment_index = real_index
        self._load_segment_detail(real_index)

    def _load_segment_detail(self, index):
        """Loads video + timeline cut handles + text comparison for the given segment index."""
        if not self.video_report or not self.project_model:
            return

        details = self.video_report.get("segments_detail", [])
        segments = self.project_model.spanish_segments

        if index < 0 or index >= len(details) or index >= len(segments):
            return

        detail = details[index]
        seg = segments[index]
        seq_num = detail.get("index", index + 1)
        text = seg.get("text", "")
        char_count = len(text)

        duration_label = ""
        if self.config_manager:
            is_edge = (index == 0 or index == len(segments) - 1)
            duration_label = f" | 预期时长: {self.config_manager.get_duration_label(char_count, is_edge=is_edge)}"

        self.lbl_segment_info.setText(f"序号 {seq_num:02d} | {char_count} 字符{duration_label}")
        self.txt_original.setPlainText(text)

        extracted = seg.get("extracted_text", "")
        if extracted:
            orig_html, ext_html = self._build_diff_html(text, extracted)
            self.txt_original.setHtml(orig_html)
            self.txt_extracted.setHtml(ext_html)

            similarity = seg.get("similarity_score", 0)
            if similarity > 0:
                if similarity >= 90:
                    color, icon = "#2E7D32", "🟢"
                elif similarity >= 70:
                    color, icon = "#F57F17", "🟡"
                else:
                    color, icon = "#C62828", "🔴"
                self.lbl_similarity.setText(f"相似度: {similarity:.1f}% {icon}")
                self.lbl_similarity.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {color}; padding: 2px 8px;")
            else:
                self.lbl_similarity.setText("相似度: —")
                self.lbl_similarity.setStyleSheet("font-size: 13px; font-weight: bold; color: #8D6E63; padding: 2px 8px;")
        else:
            self.txt_extracted.clear()
            self.lbl_similarity.setText("相似度: —")
            self.lbl_similarity.setStyleSheet("font-size: 13px; font-weight: bold; color: #8D6E63; padding: 2px 8px;")

        # Update mark delete button
        if hasattr(self, "btn_mark_delete") and self.btn_mark_delete:
            self.btn_mark_delete.setEnabled(True)
            is_marked = seg.get("marked_for_deletion", False)
            if is_marked:
                self.btn_mark_delete.setText("↩ 取消待删")
            else:
                self.btn_mark_delete.setText("🚩 标记待删")

        # Load video & populate timeline bar
        is_found = detail.get("found", False)
        source_path = detail.get("source_path")

        if is_found and source_path and Path(str(source_path)).exists():
            video_path = Path(str(source_path))
            self._current_video_path = video_path
            file_size = detail.get("file_size", "未知")
            status = detail.get("status_text", "")
            self.lbl_video_info.setText(f"{status} | {video_path.name} | {file_size}")

            from services.ffmpeg_helper import FFmpegHelper
            vid_dur = float(seg.get("video_duration", 0.0) or 0.0)
            if vid_dur <= 0:
                vid_dur = FFmpegHelper.get_media_duration(video_path)
                if vid_dur > 0:
                    seg["video_duration"] = round(vid_dur, 3)

            cut_in = float(seg.get("cut_in", 0.0) or 0.0)
            cut_out = float(seg.get("cut_out", 0.0) or 0.0)
            if cut_out <= cut_in + 0.05:
                cut_in = 0.0
                cut_out = vid_dur if vid_dur > 0 else 5.0

            words = seg.get("word_timings", []) or []
            speech_start = float(seg.get("speech_start", cut_in) or cut_in)
            speech_end = float(seg.get("speech_end", cut_out) or cut_out)

            self._sync_cut_controls(vid_dur, cut_in, cut_out, words, speech_start, speech_end)

            if self.media_player:
                self.media_player.stop()
                self.media_player.setSource(QUrl.fromLocalFile(str(video_path)))
            self.btn_play.setEnabled(_HAS_MULTIMEDIA)
            self.btn_extract_single.setEnabled(True)
            self.btn_delete_single_now.setEnabled(True)
        else:
            self._current_video_path = None
            self.lbl_video_info.setText("❌ 视频文件缺失（如已在 Flow 重新生成，请点击右下方【🔄 替换 / 重新核对本段】自动归位并核对）")
            self._sync_cut_controls(0.0, 0.0, 0.0, [], 0.0, 0.0)
            if self.media_player:
                self.media_player.stop()
                self.media_player.setSource(QUrl())
            self.btn_play.setEnabled(False)
            # Even if missing in downloads/videos, allow clicking Replace to scan Flow/ folder!
            self.btn_extract_single.setEnabled(True)
            self.btn_delete_single_now.setEnabled(False)

    def _sync_cut_controls(self, vid_dur: float, cut_in: float, cut_out: float, words: list, speech_start: float = 0.0, speech_end: float = 0.0):
        """Updates the spinboxes and SegmentTimelineBar without feedback loops."""
        self.spin_cut_in.blockSignals(True)
        self.spin_cut_out.blockSignals(True)
        max_d = max(1.0, vid_dur if vid_dur > 0 else 600.0)
        self.spin_cut_in.setRange(0.0, max_d)
        self.spin_cut_out.setRange(0.0, max_d)
        self.spin_cut_in.setValue(cut_in)
        self.spin_cut_out.setValue(cut_out)
        self.spin_cut_in.blockSignals(False)
        self.spin_cut_out.blockSignals(False)

        kept = max(0.0, cut_out - cut_in)
        self.lbl_kept_duration.setText(f"保留: {kept:.2f}s / 原长: {vid_dur:.2f}s")
        self.timeline_bar.set_timeline_data(vid_dur, cut_in, cut_out, words, speech_start, speech_end)

    def _on_timeline_bar_cut_changed(self, new_in: float, new_out: float):
        """Called when user drags the Cyan In-Handle or Yellow Out-Handle on the timeline bar."""
        self.spin_cut_in.blockSignals(True)
        self.spin_cut_out.blockSignals(True)
        self.spin_cut_in.setValue(new_in)
        self.spin_cut_out.setValue(new_out)
        self.spin_cut_in.blockSignals(False)
        self.spin_cut_out.blockSignals(False)
        self._save_current_segment_cut(new_in, new_out)

    def _on_spin_cut_changed(self):
        """Called when user edits cut_in / cut_out spinboxes."""
        new_in = self.spin_cut_in.value()
        new_out = self.spin_cut_out.value()
        if new_out <= new_in + 0.15:
            new_out = new_in + 0.20
            self.spin_cut_out.blockSignals(True)
            self.spin_cut_out.setValue(new_out)
            self.spin_cut_out.blockSignals(False)
        self.timeline_bar.cut_in = new_in
        self.timeline_bar.cut_out = new_out
        self.timeline_bar.update()
        self._save_current_segment_cut(new_in, new_out)

    def _save_current_segment_cut(self, cut_in: float, cut_out: float):
        if not self.project_model or self.current_segment_index < 0:
            return
        segments = self.project_model.spanish_segments
        if self.current_segment_index < len(segments):
            seg = segments[self.current_segment_index]
            seg["cut_in"] = round(float(cut_in), 3)
            seg["cut_out"] = round(float(cut_out), 3)
            seg["manual_cut_adjusted"] = True
            vid_dur = float(seg.get("video_duration", self.timeline_bar.duration) or 0.0)
            kept = max(0.0, cut_out - cut_in)
            self.lbl_kept_duration.setText(f"保留: {kept:.2f}s / 原长: {vid_dur:.2f}s")
            self.project_model.save()
            # Update current list item label
            cur_row = self.list_segments.currentRow()
            self._populate_segment_list()
            if cur_row >= 0 and cur_row < self.list_segments.count():
                self.list_segments.blockSignals(True)
                self.list_segments.setCurrentRow(cur_row)
                self.list_segments.blockSignals(False)

    def _on_timeline_bar_seek(self, time_sec: float):
        if self.media_player:
            self.media_player.setPosition(int(round(time_sec * 1000)))

    def reset_current_segment_breath_cut(self):
        """Recalculates and restores AI breath cut points for the current segment."""
        if not self.project_model or self.current_segment_index < 0:
            return
        segments = self.project_model.spanish_segments
        if self.current_segment_index >= len(segments):
            return
        seg = segments[self.current_segment_index]
        words = seg.get("word_timings", []) or []
        vid_dur = float(seg.get("video_duration", self.timeline_bar.duration) or 0.0)
        from services.speech_extractor import SpeechExtractor
        cut_info = SpeechExtractor.compute_breath_cut_range(
            words=words,
            original_text=seg.get("text", ""),
            video_duration=vid_dur,
            pad_before=self.spin_pad_before.value(),
            pad_after=self.spin_pad_after.value(),
        )
        seg["cut_in"] = cut_info["cut_in"]
        seg["cut_out"] = cut_info["cut_out"]
        seg["speech_start"] = cut_info["speech_start"]
        seg["speech_end"] = cut_info["speech_end"]
        seg["manual_cut_adjusted"] = False
        self.project_model.save()
        self._sync_cut_controls(
            vid_dur, cut_info["cut_in"], cut_info["cut_out"],
            words, cut_info["speech_start"], cut_info["speech_end"]
        )

    def recalculate_all_breath_cuts(self):
        """Applies current spin_pad_before / spin_pad_after to all segments with word_timings."""
        if not self.project_model:
            return
        from services.speech_extractor import SpeechExtractor
        pad_b = self.spin_pad_before.value()
        pad_a = self.spin_pad_after.value()
        updated = 0
        for seg in self.project_model.spanish_segments:
            words = seg.get("word_timings", [])
            vid_dur = float(seg.get("video_duration", 0.0) or 0.0)
            if words or vid_dur > 0:
                cut_info = SpeechExtractor.compute_breath_cut_range(
                    words=words,
                    original_text=seg.get("text", ""),
                    video_duration=vid_dur,
                    pad_before=pad_b,
                    pad_after=pad_a,
                )
                seg["cut_in"] = cut_info["cut_in"]
                seg["cut_out"] = cut_info["cut_out"]
                seg["speech_start"] = cut_info["speech_start"]
                seg["speech_end"] = cut_info["speech_end"]
                seg["manual_cut_adjusted"] = False
                updated += 1
        self.project_model.save()
        if self.current_segment_index >= 0:
            self._load_segment_detail(self.current_segment_index)
        self._populate_segment_list()
        QMessageBox.information(
            self, "重算完成",
            f"⚡ 已按【前留白 {pad_b:.2f}s / 后留白 {pad_a:.2f}s】重新计算 {updated} 个片段的气口切点！"
        )

    # ═══════════════════════════════════════════════════════
    # Video player & Seamless Cross-Clip Timeline Preview
    # ═══════════════════════════════════════════════════════
    def toggle_play(self):
        if not self.media_player:
            self.play_external()
            return
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._continuous_preview_active = False
            self.btn_preview_all_timeline.setText("🔗 跨片段联播预览")
            self.media_player.pause()
        else:
            if self.chk_play_trimmed_only.isChecked():
                cut_in_ms = int(round(self.spin_cut_in.value() * 1000))
                cut_out_ms = int(round(self.spin_cut_out.value() * 1000))
                cur_pos = self.media_player.position()
                if cur_pos < cut_in_ms or (cut_out_ms > cut_in_ms and cur_pos >= cut_out_ms - 80):
                    self.media_player.setPosition(cut_in_ms)
            self.media_player.play()

    def toggle_continuous_timeline_preview(self):
        """Seamless NLE-style playback across all segments using each segment's [cut_in, cut_out]."""
        if not self.media_player:
            return
        if self._continuous_preview_active:
            self._continuous_preview_active = False
            self.btn_preview_all_timeline.setText("🔗 跨片段联播预览")
            self.media_player.pause()
            return

        self._continuous_preview_active = True
        self.chk_play_trimmed_only.setChecked(True)
        self.btn_preview_all_timeline.setText("⏹ 停止联播预览")
        if self.list_segments.currentRow() < 0 and self.list_segments.count() > 0:
            self.list_segments.setCurrentRow(0)
        cut_in_ms = int(round(self.spin_cut_in.value() * 1000))
        self.media_player.setPosition(cut_in_ms)
        self.media_player.play()

    def update_play_button(self, state):
        if not _HAS_MULTIMEDIA:
            return
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.btn_play.setText("⏸ 暂停")
        else:
            self.btn_play.setText("▶ 播放")

    def update_position(self, position):
        total = self._duration_ms
        pos_sec = position / 1000.0
        self.timeline_bar.set_playhead(pos_sec)
        pos_str = self._format_time(position)
        dur_str = self._format_time(total)
        self.lbl_video_time.setText(f"{pos_str} / {dur_str}")

        # Enforce cut_out boundary when chk_play_trimmed_only or continuous preview is active
        if self.chk_play_trimmed_only.isChecked() and self.media_player:
            cut_out_sec = self.spin_cut_out.value()
            cut_in_sec = self.spin_cut_in.value()
            if cut_out_sec > cut_in_sec + 0.1 and pos_sec >= cut_out_sec:
                if self._continuous_preview_active:
                    next_row = self.list_segments.currentRow() + 1
                    if next_row < self.list_segments.count():
                        self.list_segments.setCurrentRow(next_row)
                        next_in_ms = int(round(self.spin_cut_in.value() * 1000))
                        self.media_player.setPosition(next_in_ms)
                        self.media_player.play()
                        return
                    else:
                        self._continuous_preview_active = False
                        self.btn_preview_all_timeline.setText("🔗 跨片段联播预览")
                self.media_player.pause()
                self.media_player.setPosition(int(round(cut_in_sec * 1000)))

    def update_duration(self, duration):
        self._duration_ms = duration
        if duration > 0 and self.timeline_bar.duration <= 0.01:
            dur_s = round(duration / 1000.0, 3)
            self._sync_cut_controls(dur_s, 0.0, dur_s, [])

    def change_speed(self):
        speed = self.combo_speed.currentData()
        if speed and self.media_player:
            self.media_player.setPlaybackRate(speed)

    def open_current_video_file(self):
        if self._current_video_path and self._current_video_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._current_video_path.parent)))

    def play_external(self):
        if self._current_video_path and self._current_video_path.exists():
            if sys.platform == 'win32':
                os.startfile(str(self._current_video_path))
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(self._current_video_path)])
            else:
                subprocess.Popen(['xdg-open', str(self._current_video_path)])
        else:
            QMessageBox.warning(self, "提示", "没有可播放的视频文件。")

    @staticmethod
    def _format_time(ms):
        s = ms // 1000
        m = s // 60
        s = s % 60
        return f"{m:02d}:{s:02d}"

    @staticmethod
    def _clean_word_for_display(word):
        import re
        import unicodedata
        w = word.lower().strip()
        def _is_word_char(c):
            return c != '_' and (bool(re.match(r'\w', c)) or unicodedata.category(c) in ('Mn', 'Mc', 'Me'))
        start = 0
        end = len(w)
        while start < end and not _is_word_char(w[start]):
            start += 1
        while end > start and not _is_word_char(w[end - 1]):
            end -= 1
        return w[start:end]

    @staticmethod
    def _normalize_word_for_compare(word):
        from services.speech_extractor import SpeechExtractor
        return SpeechExtractor._normalize_word_for_compare(word)

    @staticmethod
    def _build_diff_html(original, extracted):
        import difflib
        import html as html_module
        from services.speech_extractor import SpeechExtractor

        base_style = 'font-family:"Segoe UI",sans-serif; font-size:13px; line-height:1.6;'

        if not original and not extracted:
            return "", ""
        if not original:
            clean_ext = " ".join([VideoCompareWidget._clean_word_for_display(w) for w in extracted.split() if VideoCompareWidget._clean_word_for_display(w)])
            return "", f'<div style="{base_style}"><span style="color:#3E2723;">{html_module.escape(clean_ext)}</span></div>'
        if not extracted:
            clean_orig = " ".join([VideoCompareWidget._clean_word_for_display(w) for w in original.split() if VideoCompareWidget._clean_word_for_display(w)])
            return f'<div style="{base_style}"><span style="color:#3E2723;">{html_module.escape(clean_orig)}</span></div>', ""

        orig_tokens = SpeechExtractor.collapse_and_normalize_tokens(original)
        ext_tokens = SpeechExtractor.collapse_and_normalize_tokens(extracted)

        orig_words = [t["display"] for t in orig_tokens]
        ext_words = [t["display"] for t in ext_tokens]
        orig_norm = [t["norm"] for t in orig_tokens]
        ext_norm = [t["norm"] for t in ext_tokens]

        from services.theme_manager import ThemeManager
        is_dark = ThemeManager.is_dark()
        base_fg = "#F4F4F5" if is_dark else "#3E2723"
        rep_bg, rep_fg = ("#451A1A", "#FCA5A5") if is_dark else ("#FFCDD2", "#B71C1C")
        del_bg, del_fg = ("#422D0B", "#FDE68A") if is_dark else ("#FFECB3", "#E65100")
        ins_bg, ins_fg = ("#143326", "#6EE7B7") if is_dark else ("#C8E6C9", "#1B5E20")

        sm = difflib.SequenceMatcher(None, orig_norm, ext_norm)
        ext_parts = []

        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == 'equal':
                text_e = " ".join(ext_words[j1:j2])
                ext_parts.append(f'<span style="color:{base_fg};">{html_module.escape(text_e)}</span>')
            elif tag == 'replace':
                text_e = " ".join(ext_words[j1:j2])
                ext_parts.append(
                    f'<span style="background-color:{rep_bg}; color:{rep_fg}; '
                    f'font-weight:bold; border-radius:2px; padding:1px 2px;">'
                    f'{html_module.escape(text_e)}</span>'
                )
            elif tag == 'delete':
                text_o = " ".join(orig_words[i1:i2])
                ext_parts.append(
                    f'<span style="background-color:{del_bg}; color:{del_fg}; '
                    f'font-weight:bold; font-style:italic; border-radius:2px; padding:1px 3px;">'
                    f'[缺失: {html_module.escape(text_o)}]</span>'
                )
            elif tag == 'insert':
                text_e = " ".join(ext_words[j1:j2])
                ext_parts.append(
                    f'<span style="background-color:{ins_bg}; color:{ins_fg}; '
                    f'font-weight:bold; border-radius:2px; padding:1px 2px;">'
                    f'{html_module.escape(text_e)}</span>'
                )

        orig_clean_str = " ".join(orig_words)
        orig_html = f'<div style="{base_style}"><span style="color:{base_fg};">{html_module.escape(orig_clean_str)}</span></div>'
        ext_html = f'<div style="{base_style}">{" ".join(ext_parts)}</div>'
        return orig_html, ext_html

    # ═══════════════════════════════════════════════════════
    # Streamlined Timeline Actions: Check, Delete, Replace & Re-verify
    # ═══════════════════════════════════════════════════════
    def mark_checked(self):
        if self.current_segment_index < 0 or not self.project_model:
            return
        segments = self.project_model.spanish_segments
        if self.current_segment_index < len(segments):
            segments[self.current_segment_index]["checked"] = True
            segments[self.current_segment_index]["marked_for_deletion"] = False
            self.project_model.save()
            self._populate_segment_list()
            self._update_summary()
            self._advance_to_next_unchecked()

    def mark_unchecked(self):
        if self.current_segment_index < 0 or not self.project_model:
            return
        segments = self.project_model.spanish_segments
        if self.current_segment_index < len(segments):
            segments[self.current_segment_index]["checked"] = False
            self.project_model.save()
            self._populate_segment_list()
            self._update_summary()
            for i in range(self.list_segments.count()):
                item = self.list_segments.item(i)
                if item and item.data(Qt.ItemDataRole.UserRole) == self.current_segment_index:
                    self.list_segments.setCurrentRow(i)
                    break

    def toggle_mark_delete(self):
        if self.current_segment_index < 0 or not self.project_model:
            return
        segments = self.project_model.spanish_segments
        if self.current_segment_index < len(segments):
            seg = segments[self.current_segment_index]
            new_state = not seg.get("marked_for_deletion", False)
            seg["marked_for_deletion"] = new_state
            if new_state:
                seg["checked"] = False
                seg["auto_checked"] = False
            self.project_model.save()
            self._populate_segment_list()
            self._update_summary()
            if new_state:
                self._advance_to_next_unchecked()
            else:
                self._load_segment_detail(self.current_segment_index)

    def delete_current_segment_video_immediately(self):
        """Streamlined Action 2 (🗑️ 直接删除此视频):
        Deletes the wrong video file on disk for the current segment immediately and resets status to Missing,
        so the user can copy JSON in FlowCue to regenerate it.
        """
        if self.current_segment_index < 0 or not self.project_model or not self.project_path:
            return
        idx = self.current_segment_index
        seq_num = idx + 1

        reply = QMessageBox.question(
            self, "确认删除当前片段视频",
            f"确定要直接删除第 {seq_num:02d} 段的视频文件吗？\n\n"
            f"• 删除后该段将变为【❌ 缺失】状态\n"
            f"• 您可以直接在【📝 文案、切分与提示词】点击「📋 导出批量生成 JSON」重新生成该段视频\n"
            f"• 新视频生成完后，回到此处点击【🔄 替换 / 重新核对本段】即可自动归位并重新核对！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        if hasattr(self, "media_player") and self.media_player:
            try:
                self.media_player.stop()
                self.media_player.setSource(QUrl())
            except Exception:
                pass

        if self._current_video_path:
            from services.speech_extractor import SpeechExtractor
            SpeechExtractor.invalidate_cache(self._current_video_path)

        from services.video_checker import VideoChecker
        base_storage_path = self._get_base_storage_path()
        VideoChecker.delete_segment_video_files(
            self.project_model, self.project_path, [idx], base_storage_path=base_storage_path
        )

        # Also clear cut points
        seg = self.project_model.spanish_segments[idx]
        for k in ("cut_in", "cut_out", "speech_start", "speech_end", "word_timings", "video_duration"):
            seg.pop(k, None)
        self.project_model.save()

        self.videos_deleted.emit()
        self.refresh_data()

    def replace_or_reverify_current_segment(self):
        """Streamlined Action 3 (🔄 替换 / 重新核对本段):
        Automatically checks if a newly generated video exists in Flow download dir (relocates it to replace old video),
        invalidates cache, and re-runs AI speech verification + breath cut calculation!
        """
        if self.current_segment_index < 0 or not self.project_model or not self.project_path:
            return

        idx = self.current_segment_index
        from services.video_checker import VideoChecker
        from services.speech_extractor import SpeechExtractor

        # Stop player to release file lock before relocating/replacing
        if hasattr(self, "media_player") and self.media_player:
            try:
                self.media_player.stop()
                self.media_player.setSource(QUrl())
            except Exception:
                pass

        base_storage_path = self._get_base_storage_path()
        fresh_report = VideoChecker.check_project_videos(
            self.project_model, self.project_path, base_storage_path=base_storage_path
        )

        details = fresh_report.get("segments_detail", [])
        if idx >= len(details):
            return

        detail = details[idx]
        # Also check if there is a newer file in pre_relocate_dir even if an old file exists in target!
        pre_dir = fresh_report.get("pre_relocate_dir", "")
        post_dir = Path(fresh_report.get("post_relocate_dir", str(self.project_path / "downloads" / "videos")))
        expected_name = detail.get("download_name", f"{idx + 1:02d}.mp4")
        relocated_new = False

        if pre_dir and Path(pre_dir).exists():
            candidate_in_flow = Path(pre_dir) / expected_name
            if candidate_in_flow.exists():
                post_dir.mkdir(parents=True, exist_ok=True)
                target_file = post_dir / expected_name
                try:
                    import shutil
                    if target_file.exists():
                        target_file.unlink()
                    shutil.move(str(candidate_in_flow), str(target_file))
                    relocated_new = True
                except Exception:
                    pass

        if not relocated_new and detail.get("found") and not detail.get("already_in_target"):
            VideoChecker.relocate_found_videos(fresh_report)
            relocated_new = True

        # Re-check after potential relocation
        self.video_report = VideoChecker.check_project_videos(
            self.project_model, self.project_path, base_storage_path=base_storage_path
        )
        details = self.video_report.get("segments_detail", [])
        detail = details[idx]

        if not detail.get("found") or not detail.get("source_path"):
            QMessageBox.warning(
                self, "未检测到新视频",
                f"第 {idx + 1:02d} 段目前未找到已下载的视频文件 ({expected_name})。\n\n"
                f"请先在 Google Flow 生成下载该视频，再点击【🔄 替换 / 重新核对本段】。"
            )
            return

        video_path = str(detail["source_path"])
        SpeechExtractor.invalidate_cache(video_path)
        self.extract_single_text(force_refresh=True)

    def replace_and_reverify_pending_videos(self):
        """Top-bar one-click button: relocates all newly generated videos from Flow/ and re-verifies them."""
        if not self.project_model or not self.project_path:
            return

        if hasattr(self, "media_player") and self.media_player:
            try:
                self.media_player.stop()
                self.media_player.setSource(QUrl())
            except Exception:
                pass

        from services.video_checker import VideoChecker
        from services.speech_extractor import SpeechExtractor

        base_storage_path = self._get_base_storage_path()
        fresh_report = VideoChecker.check_project_videos(
            self.project_model, self.project_path, base_storage_path=base_storage_path
        )

        # Also check if any files exist in pre_relocate_dir that should overwrite existing ones
        pre_dir = fresh_report.get("pre_relocate_dir", "")
        post_dir = Path(fresh_report.get("post_relocate_dir", str(self.project_path / "downloads" / "videos")))
        replaced_indices = set()

        if pre_dir and Path(pre_dir).exists():
            import shutil
            post_dir.mkdir(parents=True, exist_ok=True)
            for i, d in enumerate(fresh_report.get("segments_detail", [])):
                exp_name = d.get("download_name", f"{i + 1:02d}.mp4")
                cand = Path(pre_dir) / exp_name
                if cand.exists():
                    target = post_dir / exp_name
                    try:
                        if target.exists():
                            target.unlink()
                        shutil.move(str(cand), str(target))
                        SpeechExtractor.invalidate_cache(target)
                        replaced_indices.add(i)
                    except Exception:
                        pass

        reloc_res = VideoChecker.relocate_found_videos(fresh_report)
        self.video_report = VideoChecker.check_project_videos(
            self.project_model, self.project_path, base_storage_path=base_storage_path
        )
        self._populate_segment_list()
        self._update_summary()

        # Find all segments that were either just replaced or haven't been extracted yet
        segments = self.project_model.spanish_segments
        details = self.video_report.get("segments_detail", [])
        to_verify = []
        for i, d in enumerate(details):
            if d.get("found") and d.get("source_path"):
                seg = segments[i] if i < len(segments) else {}
                if i in replaced_indices or not seg.get("extracted_text"):
                    vp = str(d["source_path"])
                    if i in replaced_indices:
                        SpeechExtractor.invalidate_cache(vp)
                    to_verify.append({
                        "segment_index": i,
                        "video_path": vp,
                        "original_text": seg.get("text", ""),
                        "force_refresh": (i in replaced_indices),
                    })

        if not to_verify:
            QMessageBox.information(
                self, "提示",
                "所有已存在的视频均已完成核对，且下载目录中没有新的待替换视频。\n"
                "如需强制重新核对某一段，请选中该段点击右下方【🔄 替换 / 重新核对本段】。"
            )
            return

        self._start_extraction_worker(to_verify)

    def batch_delete_marked_videos(self):
        """Batch deletes local video files on disk for all segments marked for deletion."""
        if not self.project_model or not self.project_path:
            return

        segments = self.project_model.spanish_segments
        marked_indices = [i for i, s in enumerate(segments) if s.get("marked_for_deletion", False)]

        if not marked_indices:
            QMessageBox.information(self, "提示", "当前没有标记待删除的视频片段。")
            return

        indices_str = "、".join([f"{i+1:02d}" for i in marked_indices[:8]])
        if len(marked_indices) > 8:
            indices_str += f" 等共 {len(marked_indices)} 句"
        else:
            indices_str = f"第 {indices_str} 句（共 {len(marked_indices)} 句）"

        reply = QMessageBox.question(
            self, "确认一键删除",
            f"确定要删除已标记的 {len(marked_indices)} 个视频片段吗？\n\n"
            f"涉及句段: {indices_str}\n\n"
            f"• 本地视频文件将被彻底删除\n"
            f"• 对应句段状态将重置为【❌ 缺失】\n"
            f"• 在【文案、切分与提示词】导出批量生成 JSON 时将自动重新包含这些句段\n\n"
            f"⚠️ 此操作不可逆，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        if hasattr(self, "media_player") and self.media_player:
            try:
                self.media_player.stop()
                self.media_player.setSource(QUrl())
            except Exception:
                pass

        from services.video_checker import VideoChecker
        base_storage_path = self._get_base_storage_path()

        res = VideoChecker.delete_segment_video_files(
            self.project_model, self.project_path, marked_indices, base_storage_path=base_storage_path
        )

        deleted_count = res.get("deleted_count", 0)
        errors = res.get("errors", [])

        self.videos_deleted.emit()
        self.refresh_data()

        error_msg = ""
        if errors:
            error_msg = "\n\n⚠️ 部分文件删除出现警告:\n" + "\n".join(errors[:5])

        QMessageBox.information(
            self, "删除完成",
            f"✅ 成功清理了 {deleted_count} 个本地视频文件！\n"
            f"已重置对应句段状态为【缺失】。\n\n"
            f"💡 您可以前往第一标签页【文案、切分与提示词】点击「导出批量生成 JSON」重新导出生成。"
            f"{error_msg}"
        )

    def _advance_to_next_unchecked(self):
        if not self.project_model:
            return
        segments = self.project_model.spanish_segments
        details = self.video_report.get("segments_detail", []) if self.video_report else []

        start = self.current_segment_index + 1
        for i in range(start, len(segments)):
            if not segments[i].get("checked", False):
                if i < len(details) and details[i].get("found", False):
                    for row in range(self.list_segments.count()):
                        item = self.list_segments.item(row)
                        if item and item.data(Qt.ItemDataRole.UserRole) == i:
                            self.list_segments.setCurrentRow(row)
                            return

        for i in range(0, start):
            if not segments[i].get("checked", False):
                if i < len(details) and details[i].get("found", False):
                    for row in range(self.list_segments.count()):
                        item = self.list_segments.item(row)
                        if item and item.data(Qt.ItemDataRole.UserRole) == i:
                            self.list_segments.setCurrentRow(row)
                            return

    def apply_filter(self):
        self._populate_segment_list()

    # ═══════════════════════════════════════════════════════
    # High-Speed Concurrent Speech Extraction & Breath Trimming
    # ═══════════════════════════════════════════════════════
    def extract_all_texts(self):
        """Batch extraction: launches high-concurrency worker thread to extract text & trim breath."""
        if not self.project_model or not self.video_report:
            return

        engine = self.combo_engine.currentData()
        if not self.config_manager:
            QMessageBox.warning(self, "提示", "未找到配置管理器，请重新打开项目。")
            return

        if engine == "gladia" and not self.config_manager.gladia_api_keys:
            QMessageBox.warning(self, "缺少 API Key",
                "未配置 Gladia API Key！\n\n请点击主界面的「⚙️ 规则设置」按钮，\n在第 4 区域添加至少一个 Gladia API Key。")
            return
        elif engine == "elevenlabs" and not self.config_manager.elevenlabs_api_keys:
            QMessageBox.warning(self, "缺少 API Key",
                "未配置 ElevenLabs API Key！\n\n请点击主界面的「⚙️ 规则设置」按钮，\n在第 4 区域添加至少一个 ElevenLabs API Key。")
            return

        # Automatically relocate any pending or replacement videos from Flow/ before extracting
        from services.video_checker import VideoChecker
        from services.speech_extractor import SpeechExtractor

        if hasattr(self, "media_player") and self.media_player:
            try:
                self.media_player.stop()
                self.media_player.setSource(QUrl())
            except Exception:
                pass

        base_storage_path = self._get_base_storage_path()
        fresh_report = VideoChecker.check_project_videos(
            self.project_model, self.project_path, base_storage_path=base_storage_path
        )
        pre_dir = fresh_report.get("pre_relocate_dir", "")
        post_dir = Path(fresh_report.get("post_relocate_dir", str(self.project_path / "downloads" / "videos")))
        replaced_indices = set()

        if pre_dir and Path(pre_dir).exists():
            import shutil
            post_dir.mkdir(parents=True, exist_ok=True)
            for i, d in enumerate(fresh_report.get("segments_detail", [])):
                exp_name = d.get("download_name", f"{i + 1:02d}.mp4")
                cand = Path(pre_dir) / exp_name
                if cand.exists():
                    target = post_dir / exp_name
                    try:
                        if target.exists():
                            target.unlink()
                        shutil.move(str(cand), str(target))
                        SpeechExtractor.invalidate_cache(target)
                        replaced_indices.add(i)
                    except Exception:
                        pass

        if fresh_report.get("pending_count", 0) > 0:
            VideoChecker.relocate_found_videos(fresh_report)

        self.video_report = VideoChecker.check_project_videos(
            self.project_model, self.project_path, base_storage_path=base_storage_path
        )

        segments = self.project_model.spanish_segments
        details = self.video_report.get("segments_detail", [])

        segments_to_process = []
        for i, detail in enumerate(details):
            if detail.get("found", False) and detail.get("source_path"):
                video_path = str(detail["source_path"])
                if i in replaced_indices:
                    SpeechExtractor.invalidate_cache(video_path)
                original_text = segments[i].get("text", "") if i < len(segments) else ""
                segments_to_process.append({
                    "segment_index": i,
                    "video_path": video_path,
                    "original_text": original_text,
                    "force_refresh": (i in replaced_indices),
                })

        if not segments_to_process:
            QMessageBox.information(self, "提示", "没有可提取的视频文件。请先确保视频已生成并归位。")
            return

        self._start_extraction_worker(segments_to_process)

    def _start_extraction_worker(self, segments_to_process: list):
        engine = self.combo_engine.currentData()
        self.btn_extract_all.setEnabled(False)
        self.btn_extract_all.setText("⏳ 极速并发提取中...")
        self.btn_extract_single.setEnabled(False)
        self.btn_refresh.setEnabled(False)

        from services.speech_extractor import ExtractionWorker

        if hasattr(self, "_extraction_worker") and self._extraction_worker:
            try:
                if self._extraction_worker.isRunning():
                    self._extraction_worker.stop()
            except Exception:
                pass
            self._extraction_worker = None

        language = getattr(self.config_manager, "speech_language", "es")
        pad_b = self.spin_pad_before.value()
        pad_a = self.spin_pad_after.value()
        # 分段并行数 (shared with 全任务一键核对 setting); actual concurrency capped by keys * 3 in the worker
        seg_parallel = int(getattr(self.config_manager, "verify_parallel_segments", 10) or 10)

        self._extraction_worker = ExtractionWorker(
            segments_to_process,
            engine,
            self.config_manager,
            language=language,
            pad_before=pad_b,
            pad_after=pad_a,
            use_cache=True,
            max_workers=seg_parallel,
        )
        self._extraction_worker.progress.connect(self._on_extraction_progress)
        self._extraction_worker.segment_detail_done.connect(self._on_segment_detail_extracted)
        self._extraction_worker.segment_done.connect(self._on_segment_extracted)
        self._extraction_worker.finished.connect(self._on_extraction_finished)
        self._extraction_worker.finished.connect(self._extraction_worker.deleteLater)
        self._extraction_worker.start()

    def _on_extraction_progress(self, current, total, status_msg):
        pct = int(current / total * 100) if total > 0 else 0
        self.progress_bar.setValue(pct)
        self.progress_bar.setFormat(f"核对 {current}/{total}")
        self.lbl_video_info.setText(status_msg)

    def _on_segment_detail_extracted(self, segment_index: int, detail_dict: dict):
        """Stores word-level timestamps and automatic breath cut points [cut_in, cut_out]."""
        if not self.project_model:
            return
        segments = self.project_model.spanish_segments
        if segment_index < len(segments):
            seg = segments[segment_index]
            seg["word_timings"] = detail_dict.get("words", [])
            seg["video_duration"] = detail_dict.get("video_duration", 0.0)
            seg["speech_start"] = detail_dict.get("speech_start", 0.0)
            seg["speech_end"] = detail_dict.get("speech_end", 0.0)
            if not seg.get("manual_cut_adjusted", False):
                seg["cut_in"] = detail_dict.get("cut_in", 0.0)
                seg["cut_out"] = detail_dict.get("cut_out", seg["video_duration"])

    def _on_segment_extracted(self, segment_index, extracted_text, similarity_score):
        """Saves extracted text & similarity score, and auto-marks >=90% as checked."""
        if not self.project_model:
            return

        segments = self.project_model.spanish_segments
        if segment_index < len(segments):
            seg = segments[segment_index]
            seg["extracted_text"] = extracted_text
            seg["similarity_score"] = similarity_score
            seg["extraction_engine"] = self.combo_engine.currentData()
            seg["extraction_time"] = datetime.datetime.now().isoformat()

            if extracted_text:
                if similarity_score >= 90:
                    seg["checked"] = True
                    seg["auto_checked"] = True
                    seg["mismatch_flagged"] = False
                    seg["marked_for_deletion"] = False
                elif similarity_score < 70:
                    seg["checked"] = False
                    seg["mismatch_flagged"] = True
                else:
                    seg["checked"] = False
                    seg["mismatch_flagged"] = False

            self.project_model.save()

        if self.current_segment_index == segment_index:
            self._load_segment_detail(segment_index)

    def _on_extraction_finished(self, success_count, total_count, errors):
        self.btn_extract_all.setEnabled(True)
        self.btn_extract_all.setText(self.BTN_TEXT_EXTRACT_ALL)
        self.btn_extract_single.setEnabled(True)
        self.btn_refresh.setEnabled(True)

        self._populate_segment_list()
        self._update_summary()

        segments = self.project_model.spanish_segments if self.project_model else []
        auto_checked = sum(1 for s in segments if s.get("auto_checked", False))
        flagged = sum(1 for s in segments if s.get("mismatch_flagged", False))

        error_text = ""
        if errors:
            error_text = "\n\n❌ 失败详情:\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                error_text += f"\n... 及其他 {len(errors) - 10} 个错误"

        auto_mark_info = (
            f"\n\n🤖 自动核对与气口剪切结果:\n"
            f"✅ 相似度≥90% 自动通过: {auto_checked} 段\n"
            f"🔴 相似度<70% 差异标红: {flagged} 段\n"
            f"✂️ 已自动根据首尾发音词切除前后气口（可在时间线拖拽 🔵入场 / 🟡出场 微调时长）"
        )

        QMessageBox.information(
            self, "极速核对完成",
            f"✅ 成功核对: {success_count}/{total_count}\n"
            f"❌ 失败: {total_count - success_count}/{total_count}"
            f"{auto_mark_info}"
            f"{error_text}"
        )
        self._extraction_worker = None

    def extract_single_text(self, force_refresh=False):
        """Extracts text and calculates breath cut range for the currently selected segment."""
        if self.current_segment_index < 0 or not self.project_model or not self.video_report:
            return

        engine = self.combo_engine.currentData()
        engine_name = "Gladia API" if engine == "gladia" else "ElevenLabs"

        if not self.config_manager:
            QMessageBox.warning(self, "提示", "未找到配置管理器。")
            return

        if engine == "gladia" and not self.config_manager.gladia_api_keys:
            QMessageBox.warning(self, "缺少 API Key", "未配置 Gladia API Key！\n请在「⚙️ 规则设置」中添加。")
            return
        elif engine == "elevenlabs" and not self.config_manager.elevenlabs_api_keys:
            QMessageBox.warning(self, "缺少 API Key", "未配置 ElevenLabs API Key！\n请在「⚙️ 规则设置」中添加。")
            return

        details = self.video_report.get("segments_detail", [])
        segments = self.project_model.spanish_segments

        idx = self.current_segment_index
        if idx >= len(details) or idx >= len(segments):
            return

        detail = details[idx]
        if not detail.get("found", False) or not detail.get("source_path"):
            QMessageBox.warning(self, "提示", "当前句段的视频文件缺失，无法提取。")
            return

        video_path = str(detail["source_path"])
        original_text = segments[idx].get("text", "")

        self._start_extraction_worker([{
            "segment_index": idx,
            "video_path": video_path,
            "original_text": original_text,
            "force_refresh": bool(force_refresh),
        }])

    # ═══════════════════════════════════════════════════════
    # Video Splicing & One-Click Send to Batch Reels
    # ═══════════════════════════════════════════════════════
    def _build_splice_plan(self) -> list:
        """Builds ordered list of valid segments with their [cut_in, cut_out] for concatenation."""
        if not self.project_model or not self.video_report:
            return []

        segments = self.project_model.spanish_segments
        details = self.video_report.get("segments_detail", [])
        plan = []

        for i, detail in enumerate(details):
            if not detail.get("found") or not detail.get("source_path"):
                continue
            seg = segments[i] if i < len(segments) else {}
            if seg.get("marked_for_deletion", False):
                continue
            vp = Path(str(detail["source_path"]))
            if not vp.exists():
                continue

            from services.ffmpeg_helper import FFmpegHelper
            vid_dur = float(seg.get("video_duration", 0.0) or 0.0)
            if vid_dur <= 0:
                vid_dur = FFmpegHelper.get_media_duration(vp)
                seg["video_duration"] = round(vid_dur, 3)

            cut_in = float(seg.get("cut_in", 0.0) or 0.0)
            cut_out = float(seg.get("cut_out", 0.0) or 0.0)
            if cut_out <= cut_in + 0.05:
                cut_in = 0.0
                cut_out = vid_dur if vid_dur > 0 else 5.0

            plan.append({
                "segment_index": i,
                "seq_num": detail.get("index", i + 1),
                "video_path": str(vp),
                "text": seg.get("text", ""),
                "cut_in": cut_in,
                "cut_out": cut_out,
                "video_duration": vid_dur,
                "words": seg.get("word_timings", []) or [],
            })
        return plan

    def export_spliced_video(self, send_to_reels_after=False):
        """Trims each segment to [cut_in, cut_out], concatenates into final MP4, and exports synchronized SRT."""
        if not self.project_model or not self.project_path:
            return

        plan = self._build_splice_plan()
        if not plan:
            QMessageBox.warning(self, "提示", "没有可合并拼接的视频片段（请先确保视频已归位且未被标记删除）。")
            return

        total_segs = len(self.project_model.spanish_segments)
        if len(plan) < total_segs:
            missing_cnt = total_segs - len(plan)
            reply = QMessageBox.question(
                self, "部分片段缺失提醒",
                f"当前项目共 {total_segs} 段，其中有 {missing_cnt} 段缺失或已标记删除。\n\n"
                f"是否仅合并现有的 {len(plan)} 个有效视频片段？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        output_dir = self.project_path / "merged_output"
        output_dir.mkdir(parents=True, exist_ok=True)
        proj_name = self.project_model.project_id or self.project_path.name
        output_video_path = output_dir / f"{proj_name}_成片.mp4"

        self.btn_splice_export.setEnabled(False)
        self.btn_splice_export.setText("⏳ 正在合并拼接...")
        self._send_to_reels_after_splice = bool(send_to_reels_after)

        from services.video_splice_service import VideoSpliceWorker
        self._splice_worker = VideoSpliceWorker(
            segments_plan=plan,
            output_video_path=str(output_video_path),
            project_path=str(self.project_path),
            parent=self,
        )
        self._splice_worker.progress.connect(self._on_splice_progress)
        self._splice_worker.finished.connect(self._on_splice_finished)
        self._splice_worker.finished.connect(self._splice_worker.deleteLater)
        self._splice_worker.start()

    def _on_splice_progress(self, pct: int, msg: str):
        self.progress_bar.setValue(pct)
        self.progress_bar.setFormat(f"合成 {pct}%")
        self.lbl_video_info.setText(msg)

    def _on_splice_finished(self, success: bool, result: dict):
        self.btn_splice_export.setEnabled(True)
        self.btn_splice_export.setText(self.BTN_TEXT_SPLICE_EXPORT)
        self._splice_worker = None

        if not success:
            QMessageBox.critical(self, "合并拼接失败", result.get("error", "未知错误"))
            return

        self._last_merged_result = result
        video_path = result.get("video_path", "")
        srt_path = result.get("srt_path", "")
        total_clips = result.get("total_clips", 0)
        cache_hits = result.get("cache_hits", 0)
        total_dur = result.get("total_duration", 0.0)

        if getattr(self, "_send_to_reels_after_splice", False):
            self._send_to_reels_after_splice = False
            self._emit_send_to_reels(result)
            return

        reply = QMessageBox.question(
            self, "🎬 视频合并拼接完成",
            f"🎉 成功合并 {total_clips} 个片段（复用裁切缓存 {cache_hits} 段）！\n"
            f"⏱️ 成片总时长: {total_dur:.2f} 秒\n\n"
            f"📹 成片路径:\n{video_path}\n\n"
            f"📝 同步字幕:\n{srt_path}\n\n"
            f"是否立即将成片与字幕送入【🎬 批量Reels】添加动态字幕样式与媒体卡片？\n"
            f"（点击 Yes 送入批量Reels，点击 No 打开成片所在文件夹）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._emit_send_to_reels(result)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(video_path).parent)))

    def send_current_project_to_reels(self):
        """Sends merged video + SRT to Batch Reels tab (splicing first if not yet spliced)."""
        if self._last_merged_result and Path(self._last_merged_result.get("video_path", "")).exists():
            self._emit_send_to_reels(self._last_merged_result)
        else:
            self.export_spliced_video(send_to_reels_after=True)

    def _emit_send_to_reels(self, result: dict):
        proj_name = self.project_model.project_id if self.project_model else "FlowCue_Project"
        payload = {
            "project_name": proj_name,
            "video_path": result.get("video_path", ""),
            "srt_path": result.get("srt_path", ""),
            "manifest_path": result.get("manifest_path", ""),
            "words": result.get("merged_words", []),
            "duration": result.get("total_duration", 0.0),
            "segments": result.get("clips", []),
        }
        self.send_to_reels_requested.emit(payload)
        main_win = self.window()
        if hasattr(main_win, "open_in_batch_reels"):
            main_win.open_in_batch_reels(payload)

    def open_batch_all_tasks_splice_dialog(self):
        """Opens the multi-task batch splice dialog to splice selected tasks one-by-one and send all to Batch Reels."""
        # Save current project's trim/breath adjustments first
        if self.project_model and self.project_path:
            try:
                self.project_model.save()
            except Exception:
                pass

        main_win = self.window()
        storage_mgr = getattr(main_win, "storage_manager", None)
        if not storage_mgr:
            QMessageBox.warning(self, "提示", "未找到存储管理器，请先在主界面设置存储路径。")
            return

        dlg = BatchAllTasksSpliceDialog(
            storage_manager=storage_mgr,
            main_window=main_win,
            parent=self,
            config_manager=self.config_manager or getattr(main_win, "config_manager", None),
        )
        dlg.exec()

        # Reload current project's last merged result if it was spliced
        if self.project_model and self.project_path:
            merged_dir = Path(self.project_path) / "merged_output"
            proj_name = self.project_model.project_id or Path(self.project_path).name
            manifest_path = merged_dir / f"{proj_name}_成片-工程" / "处理片段" / "处理片段清单.json"
            if manifest_path.exists():
                try:
                    import json as _json
                    m_data = _json.loads(manifest_path.read_text(encoding="utf-8"))
                    self._last_merged_result = {
                        "video_path": m_data.get("output_path", str(merged_dir / f"{proj_name}_成片.mp4")),
                        "srt_path": m_data.get("srt_path", str(merged_dir / f"{proj_name}_成片.srt")),
                        "manifest_path": str(manifest_path),
                        "total_duration": m_data.get("total_duration", 0.0),
                        "merged_words": m_data.get("merged_words", []),
                        "clips": m_data.get("clips", []),
                    }
                except Exception:
                    pass

    def open_batch_all_tasks_verify_dialog(self):
        """Opens the parallel multi-task batch subtitle verification dialog (up to 4 tasks in parallel)."""
        main_win = self.window()
        storage_mgr = getattr(main_win, "storage_manager", None)
        cfg_mgr = self.config_manager or getattr(main_win, "config_manager", None)
        if not storage_mgr:
            QMessageBox.warning(self, "提示", "未找到存储管理器，请先在主界面设置存储路径。")
            return
        if not cfg_mgr:
            QMessageBox.warning(self, "提示", "未找到配置管理器。")
            return

        dlg = BatchAllTasksVerifyDialog(
            storage_manager=storage_mgr,
            config_manager=cfg_mgr,
            default_engine=self.combo_engine.currentData() if hasattr(self, "combo_engine") else "gladia",
            default_pad_before=self.spin_pad_before.value() if hasattr(self, "spin_pad_before") else 0.10,
            default_pad_after=self.spin_pad_after.value() if hasattr(self, "spin_pad_after") else 0.15,
            parent=self,
        )
        dlg.exec()

        # Reload current project model from disk in case it was updated by batch verification
        if self.project_model and self.project_path:
            try:
                self.project_model.load()
            except Exception:
                pass
            self.refresh_data()

        if hasattr(main_win, "refresh_project_list"):
            try:
                main_win.refresh_project_list()
            except Exception:
                pass


class BatchAllTasksVerifyDialog(QDialog):
    """Dialog for batch verifying subtitles & breath cut points across all FlowCue tasks in parallel.

    任务并行数 (1..4) × 分段并行数 (1..40) → theoretical max 160 concurrent requests,
    automatically capped by the number of API keys (each key ≤ 3 concurrent requests).
    """

    def __init__(
        self,
        storage_manager,
        config_manager,
        default_engine="gladia",
        default_pad_before=None,
        default_pad_after=None,
        parent=None,
    ):
        super().__init__(parent)
        self.storage_manager = storage_manager
        self.config_manager = config_manager
        self.default_engine = default_engine
        # Fall back to 规则设置 (config) 前留白/后留白 defaults when not explicitly provided
        if default_pad_before is None:
            default_pad_before = getattr(config_manager, "breath_pad_before", 0.10)
        if default_pad_after is None:
            default_pad_after = getattr(config_manager, "breath_pad_after", 0.15)
        try:
            self.default_pad_before = float(default_pad_before)
        except (TypeError, ValueError):
            self.default_pad_before = 0.10
        try:
            self.default_pad_after = float(default_pad_after)
        except (TypeError, ValueError):
            self.default_pad_after = 0.15
        self._worker = None
        self._projects_data = []
        self._row_by_proj_id = {}

        self.setWindowTitle("📚 全任务一键核对 (任务并行 × 分段并行 · 多 Key 自动限流)")
        self.resize(980, 640)
        self.init_ui()
        self.load_projects_table()

    def init_ui(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #FAF6F0;
                color: #5D4037;
                font-family: "Segoe UI", sans-serif;
            }
            QLabel {
                font-size: 13px;
                color: #5D4037;
                font-weight: bold;
            }
            QPushButton {
                background-color: #E0A96D;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #D2904C;
            }
            QPushButton:disabled {
                background-color: #D7CCC8;
                color: #A1887F;
            }
            QTableWidget {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 6px;
                font-size: 12px;
                color: #3E2723;
                gridline-color: #EFEBE9;
            }
            QHeaderView::section {
                background-color: #EFEBE9;
                color: #5D4037;
                font-weight: bold;
                font-size: 12px;
                padding: 6px;
                border: none;
                border-bottom: 1px solid #D7CCC8;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # Top Config Frame
        cfg_frame = QFrame()
        cfg_frame.setStyleSheet("""
            QFrame {
                background-color: #EFEBE9;
                border: 1px solid #D7CCC8;
                border-radius: 6px;
                padding: 6px;
            }
        """)
        cfg_vbox = QVBoxLayout(cfg_frame)
        cfg_vbox.setContentsMargins(10, 8, 10, 8)
        cfg_vbox.setSpacing(8)

        row1 = QHBoxLayout()
        row1.setSpacing(10)

        lbl_parallel = QLabel("🔀 任务并行数:")
        lbl_parallel.setStyleSheet("color: #6D28D9; font-weight: bold; font-size: 13px;")
        row1.addWidget(lbl_parallel)

        self.spin_parallel_tasks = QSpinBox()
        self.spin_parallel_tasks.setRange(1, 4)
        self.spin_parallel_tasks.setValue(
            max(1, min(4, int(getattr(self.config_manager, "verify_parallel_tasks", 4) or 4)))
        )
        self.spin_parallel_tasks.setSuffix(" 个任务")
        self.spin_parallel_tasks.setFixedWidth(100)
        self.spin_parallel_tasks.setToolTip("同时并列核对的任务数量（范围 1 ~ 4，最大为 4）")
        row1.addWidget(self.spin_parallel_tasks)

        lbl_seg_parallel = QLabel("🧩 分段并行数:")
        lbl_seg_parallel.setStyleSheet("color: #6D28D9; font-weight: bold; font-size: 13px;")
        row1.addWidget(lbl_seg_parallel)

        self.spin_parallel_segments = QSpinBox()
        self.spin_parallel_segments.setRange(1, 40)
        self.spin_parallel_segments.setValue(
            max(1, min(40, int(getattr(self.config_manager, "verify_parallel_segments", 10) or 10)))
        )
        self.spin_parallel_segments.setSuffix(" 段/任务")
        self.spin_parallel_segments.setFixedWidth(100)
        self.spin_parallel_segments.setToolTip(
            "每个任务内同时核对的片段数量（范围 1 ~ 40）\n"
            "理论最大并发 = 任务并行数 × 分段并行数（最大 4 × 40 = 160）\n"
            "实际并发受 Key 数量限制：每个 Key 最多 3 个并发请求（N 个 Key 最多 3N）\n"
            "「🚀 极速核对（单任务）」也使用此分段并行数"
        )
        row1.addWidget(self.spin_parallel_segments)

        self.lbl_concurrency_info = QLabel("")
        self.lbl_concurrency_info.setWordWrap(True)
        self.lbl_concurrency_info.setStyleSheet("color: #0F766E; font-size: 12px; font-weight: bold;")
        row1.addWidget(self.lbl_concurrency_info, stretch=1)
        cfg_vbox.addLayout(row1)

        row1b = QHBoxLayout()
        row1b.setSpacing(10)
        row1b.addWidget(QLabel("🔊 语音引擎:"))
        self.combo_engine = QComboBox()
        self.combo_engine.addItem("Gladia 极速并发", "gladia")
        self.combo_engine.addItem("ElevenLabs", "elevenlabs")
        if self.default_engine == "elevenlabs":
            self.combo_engine.setCurrentIndex(1)
        self.combo_engine.setFixedWidth(140)
        row1b.addWidget(self.combo_engine)

        row1b.addSpacing(8)
        row1b.addWidget(QLabel("✂️ 前留白:"))
        self.spin_pad_before = QDoubleSpinBox()
        self.spin_pad_before.setRange(0.0, 2.0)
        self.spin_pad_before.setSingleStep(0.05)
        self.spin_pad_before.setDecimals(2)
        self.spin_pad_before.setValue(self.default_pad_before)
        self.spin_pad_before.setSuffix("s")
        self.spin_pad_before.setFixedWidth(70)
        row1b.addWidget(self.spin_pad_before)

        row1b.addWidget(QLabel("后留白:"))
        self.spin_pad_after = QDoubleSpinBox()
        self.spin_pad_after.setRange(0.0, 2.0)
        self.spin_pad_after.setSingleStep(0.05)
        self.spin_pad_after.setDecimals(2)
        self.spin_pad_after.setValue(self.default_pad_after)
        self.spin_pad_after.setSuffix("s")
        self.spin_pad_after.setFixedWidth(70)
        row1b.addWidget(self.spin_pad_after)

        row1b.addStretch()
        cfg_vbox.addLayout(row1b)

        self.spin_parallel_tasks.valueChanged.connect(self._update_concurrency_info)
        self.spin_parallel_segments.valueChanged.connect(self._update_concurrency_info)
        self.combo_engine.currentIndexChanged.connect(self._update_concurrency_info)
        self._update_concurrency_info()

        row2 = QHBoxLayout()
        row2.setSpacing(12)

        self.chk_skip_checked = QCheckBox("跳过已核对通过的句段 (仅核对未核对/新归位视频)")
        self.chk_skip_checked.setChecked(True)
        self.chk_skip_checked.setStyleSheet("font-size: 12px; color: #0F766E; font-weight: bold;")
        row2.addWidget(self.chk_skip_checked)

        self.chk_force_no_cache = QCheckBox("强制忽略本地音频缓存重跑 API")
        self.chk_force_no_cache.setChecked(False)
        self.chk_force_no_cache.setStyleSheet("font-size: 12px; color: #B45309;")
        row2.addWidget(self.chk_force_no_cache)

        row2.addStretch()

        self.btn_sel_all = QPushButton("☑️ 全选")
        self.btn_sel_all.setStyleSheet("background-color: #64748B; color: white; padding: 4px 10px;")
        self.btn_sel_all.clicked.connect(self._select_all_rows)
        row2.addWidget(self.btn_sel_all)

        self.btn_sel_pending = QPushButton("⚡ 仅选含待核对的任务")
        self.btn_sel_pending.setStyleSheet("background-color: #0284C7; color: white; padding: 4px 10px;")
        self.btn_sel_pending.clicked.connect(self._select_pending_rows)
        row2.addWidget(self.btn_sel_pending)

        self.btn_sel_none = QPushButton("⏹️ 清空选择")
        self.btn_sel_none.setStyleSheet("background-color: #94A3B8; color: white; padding: 4px 10px;")
        self.btn_sel_none.clicked.connect(self._deselect_all_rows)
        row2.addWidget(self.btn_sel_none)

        cfg_vbox.addLayout(row2)
        layout.addWidget(cfg_frame)

        # Projects Table
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "选择", "任务名称 (Project)", "总句段", "视频就绪 / 缺失", "当前核对状态", "批量核对实时进度"
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 54)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 74)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(3, 130)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(4, 175)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, stretch=1)

        # Progress & Bottom Buttons
        prog_row = QHBoxLayout()
        self.lbl_overall_status = QLabel("就绪：请勾选要批量核对的任务，点击右侧【🚀 开始并列核对】")
        self.lbl_overall_status.setStyleSheet("font-size: 12px; color: #5D4037;")
        prog_row.addWidget(self.lbl_overall_status, stretch=1)

        self.overall_bar = QProgressBar()
        self.overall_bar.setRange(0, 100)
        self.overall_bar.setValue(0)
        self.overall_bar.setFixedWidth(220)
        prog_row.addWidget(self.overall_bar)
        layout.addLayout(prog_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.btn_start = QPushButton("🚀 开始并列核对选中任务")
        self.btn_start.setStyleSheet("""
            QPushButton {
                background-color: #7C3AED;
                color: white;
                font-size: 13px;
                font-weight: bold;
                padding: 8px 20px;
                border-radius: 5px;
            }
            QPushButton:hover { background-color: #6D28D9; }
            QPushButton:disabled { background-color: #D7CCC8; color: #A1887F; }
        """)
        self.btn_start.clicked.connect(self.start_batch_verify)
        btn_row.addWidget(self.btn_start)

        self.btn_stop = QPushButton("⏹ 停止")
        self.btn_stop.setStyleSheet("background-color: #DC2626; color: white; padding: 8px 16px;")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_batch_verify)
        btn_row.addWidget(self.btn_stop)

        self.btn_close = QPushButton("关闭")
        self.btn_close.setStyleSheet("background-color: #8D6E63; color: white; padding: 8px 16px;")
        self.btn_close.clicked.connect(self.close)
        btn_row.addWidget(self.btn_close)

        layout.addLayout(btn_row)

    def load_projects_table(self):
        from models.project_model import ProjectModel
        from services.video_checker import VideoChecker
        from services.speech_extractor import SpeechExtractor

        self.table.setRowCount(0)
        self._projects_data = []
        self._row_by_proj_id = {}

        projects = self.storage_manager.list_projects() if self.storage_manager else []
        base_dir = self.storage_manager.get_base_path() if self.storage_manager else None

        for row_idx, p_info in enumerate(projects):
            p_id = str(p_info.get("id", ""))
            p_path = Path(p_info["path"])
            try:
                model = ProjectModel(p_path)
                # Refresh similarity with Spanish number-word equivalence
                changed = False
                for seg in (model.spanish_segments or []):
                    if seg.get("extracted_text") and seg.get("text"):
                        new_s = SpeechExtractor.calculate_similarity(seg["text"], seg["extracted_text"])
                        if abs(float(seg.get("similarity_score", 0.0) or 0.0) - new_s) >= 0.1:
                            seg["similarity_score"] = new_s
                            if new_s >= 90 and not seg.get("marked_for_deletion", False):
                                seg["checked"] = True
                                seg["auto_checked"] = True
                                seg["mismatch_flagged"] = False
                            changed = True
                if changed:
                    model.save()

                report = VideoChecker.check_project_videos(model, p_path, base_storage_path=base_dir)
                segs = model.spanish_segments or []
                total_segs = len(segs)
                found_cnt = report.get("already_count", 0) + report.get("pending_count", 0)
                missing_cnt = report.get("missing_count", 0)
                checked_cnt = sum(1 for s in segs if s.get("checked", False))
                flagged_cnt = sum(
                    1
                    for s in segs
                    if s.get("mismatch_flagged", False)
                    or (s.get("extracted_text") and 0 < float(s.get("similarity_score", 0) or 0) < 70)
                )
            except Exception:
                total_segs = 0
                found_cnt = 0
                missing_cnt = 0
                checked_cnt = 0
                flagged_cnt = 0

            has_work = found_cnt > 0 and checked_cnt < total_segs
            self._projects_data.append({
                "id": p_id,
                "path": p_path,
                "total_segs": total_segs,
                "found_cnt": found_cnt,
                "missing_cnt": missing_cnt,
                "checked_cnt": checked_cnt,
                "has_work": has_work,
            })
            self._row_by_proj_id[p_id] = row_idx

            self.table.insertRow(row_idx)

            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            chk_item.setCheckState(Qt.CheckState.Checked if found_cnt > 0 else Qt.CheckState.Unchecked)
            self.table.setItem(row_idx, 0, chk_item)

            self.table.setItem(row_idx, 1, QTableWidgetItem(p_id))

            it_total = QTableWidgetItem(str(total_segs))
            it_total.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row_idx, 2, it_total)

            it_vid = QTableWidgetItem(f"✅ {found_cnt} / ❌ {missing_cnt}")
            it_vid.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row_idx, 3, it_vid)

            status_str = f"🟢 已过 {checked_cnt}/{total_segs}"
            if flagged_cnt > 0:
                status_str += f" (🔴告警 {flagged_cnt})"
            it_chk = QTableWidgetItem(status_str)
            it_chk.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row_idx, 4, it_chk)

            prog_txt = "⏳ 等待核对" if found_cnt > 0 else "⚠️ 无可核对视频"
            self.table.setItem(row_idx, 5, QTableWidgetItem(prog_txt))

    def _select_all_rows(self):
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it:
                it.setCheckState(Qt.CheckState.Checked)

    def _deselect_all_rows(self):
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it:
                it.setCheckState(Qt.CheckState.Unchecked)

    def _select_pending_rows(self):
        for r, p_data in enumerate(self._projects_data):
            it = self.table.item(r, 0)
            if it:
                it.setCheckState(Qt.CheckState.Checked if p_data.get("has_work") else Qt.CheckState.Unchecked)

    def _current_engine_keys(self) -> list:
        engine = self.combo_engine.currentData() if hasattr(self, "combo_engine") else "gladia"
        if self.config_manager is None:
            return []
        if hasattr(self.config_manager, "get_speech_keys"):
            return self.config_manager.get_speech_keys(engine)
        if engine == "elevenlabs":
            return list(getattr(self.config_manager, "elevenlabs_api_keys", []) or [])
        return list(getattr(self.config_manager, "gladia_api_keys", []) or [])

    def _compute_concurrency_plan(self) -> dict:
        from services.speech_extractor import compute_concurrency_plan
        per_key = int(getattr(self.config_manager, "SPEECH_MAX_CONCURRENT_PER_KEY", 3) or 3)
        return compute_concurrency_plan(
            len(self._current_engine_keys()),
            self.spin_parallel_tasks.value(),
            self.spin_parallel_segments.value(),
            per_key_limit=per_key,
        )

    def _update_concurrency_info(self, *args):
        if not hasattr(self, "lbl_concurrency_info"):
            return
        try:
            plan = self._compute_concurrency_plan()
        except Exception as exc:
            self.lbl_concurrency_info.setText(f"⚠️ 无法计算并发: {exc}")
            return
        icon = "⚠️" if plan.get("adjusted") else "✅"
        color = "#B45309" if plan.get("adjusted") else "#0F766E"
        self.lbl_concurrency_info.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: bold;")
        self.lbl_concurrency_info.setText(f"{icon} {plan.get('note', '')}")

    def _persist_parallel_settings(self):
        """Saves 任务并行数 / 分段并行数 to config so they are remembered next time."""
        cfg = self.config_manager
        if cfg is None:
            return
        try:
            cfg.verify_parallel_tasks = int(self.spin_parallel_tasks.value())
            cfg.verify_parallel_segments = int(self.spin_parallel_segments.value())
            if hasattr(cfg, "save"):
                cfg.save()
        except Exception as exc:
            print(f"Error saving verify parallel settings: {exc}")

    def start_batch_verify(self):
        engine = self.combo_engine.currentData()
        if engine == "gladia" and not self.config_manager.gladia_api_keys:
            QMessageBox.warning(self, "缺少 API Key", "未配置 Gladia API Key！请先在「⚙️ 规则设置」中添加。")
            return
        if engine == "elevenlabs" and not self.config_manager.elevenlabs_api_keys:
            QMessageBox.warning(self, "缺少 API Key", "未配置 ElevenLabs API Key！请先在「⚙️ 规则设置」中添加。")
            return

        selected_projects = []
        for r, p_data in enumerate(self._projects_data):
            it = self.table.item(r, 0)
            if it and it.checkState() == Qt.CheckState.Checked:
                selected_projects.append({"id": p_data["id"], "path": p_data["path"]})

        if not selected_projects:
            QMessageBox.information(self, "提示", "请至少勾选一个要核对的任务。")
            return

        parallel_cnt = min(4, max(1, self.spin_parallel_tasks.value()))
        seg_parallel_cnt = min(40, max(1, self.spin_parallel_segments.value()))
        self._persist_parallel_settings()
        plan = self._compute_concurrency_plan()
        self._update_concurrency_info()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.spin_parallel_tasks.setEnabled(False)
        self.spin_parallel_segments.setEnabled(False)
        self.combo_engine.setEnabled(False)
        self.overall_bar.setValue(0)
        self.lbl_overall_status.setText(f"🚀 正在启动… {plan.get('note', '')}")

        from services.speech_extractor import BatchMultiProjectVerifyWorker
        base_dir = self.storage_manager.get_base_path() if self.storage_manager else None

        self._worker = BatchMultiProjectVerifyWorker(
            projects_list=selected_projects,
            engine=engine,
            config_manager=self.config_manager,
            base_storage_path=base_dir,
            max_parallel_tasks=parallel_cnt,
            pad_before=self.spin_pad_before.value(),
            pad_after=self.spin_pad_after.value(),
            skip_already_checked=self.chk_skip_checked.isChecked(),
            force_no_cache=self.chk_force_no_cache.isChecked(),
            parent=self,
            max_parallel_segments=seg_parallel_cnt,
        )
        self._worker.task_started.connect(self._on_task_started)
        self._worker.task_progress.connect(self._on_task_progress)
        self._worker.task_finished.connect(self._on_task_finished)
        self._worker.overall_progress.connect(self._on_overall_progress)
        self._worker.all_finished.connect(self._on_all_finished)
        self._worker.concurrency_note.connect(self._on_concurrency_note)
        self._worker.start()

    def _on_concurrency_note(self, note: str):
        if hasattr(self, "lbl_concurrency_info") and note:
            self.lbl_concurrency_info.setText(f"⚙️ 运行中: {note}")

    def stop_batch_verify(self):
        if self._worker and self._worker.isRunning():
            self.lbl_overall_status.setText("⏳ 正在停止并列任务...")
            self._worker.cancel()

    def _on_task_started(self, proj_id: str):
        r = self._row_by_proj_id.get(proj_id)
        if r is not None:
            it = self.table.item(r, 5)
            if it:
                it.setText("🔄 正在启动核对...")
                it.setForeground(QColor("#0284C7"))

    def _on_task_progress(self, proj_id: str, done_cnt: int, total_cnt: int, msg: str):
        r = self._row_by_proj_id.get(proj_id)
        if r is not None:
            it = self.table.item(r, 5)
            if it:
                it.setText(msg)
                it.setForeground(QColor("#0284C7"))

    def _on_task_finished(self, proj_id: str, summary: dict):
        r = self._row_by_proj_id.get(proj_id)
        if r is None:
            return
        total_segs = summary.get("total_segments", 0)
        checked_cnt = summary.get("auto_checked_count", 0)
        flagged_cnt = summary.get("flagged_count", 0)
        errs = summary.get("errors", [])

        status_str = f"🟢 已过 {checked_cnt}/{total_segs}"
        if flagged_cnt > 0:
            status_str += f" (🔴告警 {flagged_cnt})"
        it_chk = self.table.item(r, 4)
        if it_chk:
            it_chk.setText(status_str)

        it_prog = self.table.item(r, 5)
        if it_prog:
            if summary.get("cancelled"):
                it_prog.setText("⛔ 已取消")
                it_prog.setForeground(QColor("#DC2626"))
            elif errs:
                it_prog.setText(f"⚠️ 完成但有 {len(errs)} 处错误: {errs[0]}")
                it_prog.setForeground(QColor("#D97706"))
            else:
                it_prog.setText(f"✅ 核对完成 (通过 {checked_cnt}/{total_segs}，告警 {flagged_cnt})")
                it_prog.setForeground(QColor("#15803D"))

    def _on_overall_progress(self, done_tasks: int, total_tasks: int, msg: str):
        pct = int(done_tasks / total_tasks * 100) if total_tasks > 0 else 0
        self.overall_bar.setValue(pct)
        self.lbl_overall_status.setText(msg)

    def _on_all_finished(self, success_tasks: int, total_tasks: int, all_results: list):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.spin_parallel_tasks.setEnabled(True)
        self.spin_parallel_segments.setEnabled(True)
        self.combo_engine.setEnabled(True)
        self.overall_bar.setValue(100)
        self._update_concurrency_info()

        total_checked = sum(r.get("auto_checked_count", 0) for r in all_results if isinstance(r, dict))
        total_flagged = sum(r.get("flagged_count", 0) for r in all_results if isinstance(r, dict))
        self.lbl_overall_status.setText(
            f"🎉 批量并列核对完成！共完成 {total_tasks} 个任务（累计通过 {total_checked} 段，差异告警 {total_flagged} 段）"
        )
        QMessageBox.information(
            self,
            "全任务一键核对完成",
            f"🎉 已完成 {total_tasks} 个任务的批量并列核对！\n\n"
            f"• 完全成功任务: {success_tasks} / {total_tasks}\n"
            f"• 累计核对通过句段 (≥90%): {total_checked} 段\n"
            f"• 累计差异告警句段 (<70%): {total_flagged} 段\n"
            f"• 所有已核对片段均已自动完成首尾气口剪切！",
        )

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
        super().closeEvent(event)


class BatchAllTasksSpliceDialog(QDialog):
    """Dialog for selecting multiple/all FlowCue tasks, splicing them (up to 4 in parallel), and sending all to Batch Reels."""

    def __init__(self, storage_manager, main_window=None, parent=None, config_manager=None):
        super().__init__(parent)
        self.storage_manager = storage_manager
        self.main_window = main_window
        self.config_manager = config_manager or getattr(main_window, "config_manager", None)
        self._worker = None
        self._projects_data = []
        self._row_by_proj_id = {}

        self.setWindowTitle("📚 所有任务一键拼接成片 (+SRT) 并全部送入批量Reels")
        self.resize(940, 620)
        self.init_ui()
        self.load_projects_table()

    def init_ui(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #FAF6F0;
                color: #5D4037;
                font-family: "Segoe UI", sans-serif;
            }
            QLabel {
                font-size: 13px;
                color: #5D4037;
                font-weight: bold;
            }
            QPushButton {
                background-color: #E0A96D;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #D2904C;
            }
            QPushButton:disabled {
                background-color: #D7CCC8;
                color: #A1887F;
            }
            QTableWidget {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 6px;
                font-size: 12px;
                color: #3E2723;
                gridline-color: #EFEBE9;
            }
            QHeaderView::section {
                background-color: #EFEBE9;
                color: #5D4037;
                font-weight: bold;
                font-size: 12px;
                padding: 6px;
                border: none;
                border-bottom: 1px solid #D7CCC8;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # Top Options Bar
        cfg_frame = QFrame()
        cfg_frame.setStyleSheet("""
            QFrame {
                background-color: #EFEBE9;
                border: 1px solid #D7CCC8;
                border-radius: 6px;
                padding: 6px;
            }
        """)
        cfg_vbox = QVBoxLayout(cfg_frame)
        cfg_vbox.setContentsMargins(10, 8, 10, 8)
        cfg_vbox.setSpacing(8)

        row1 = QHBoxLayout()
        row1.setSpacing(14)

        self.chk_auto_send_reels = QCheckBox("✅ 全部拼接完成后，自动将所有成片 (+SRT与逐词时间轴) 全部送入【🎬 批量Reels】")
        self.chk_auto_send_reels.setChecked(True)
        self.chk_auto_send_reels.setStyleSheet("font-size: 13px; color: #0F766E; font-weight: bold;")
        row1.addWidget(self.chk_auto_send_reels)

        self.chk_reuse_existing = QCheckBox("⚡ 若已存在合成片则直接复用 (不勾选也会自动复用 SHA-256 片段缓存)")
        self.chk_reuse_existing.setChecked(False)
        self.chk_reuse_existing.setStyleSheet("font-size: 12px; color: #6D28D9; font-weight: bold;")
        row1.addWidget(self.chk_reuse_existing)

        row1.addStretch()
        cfg_vbox.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(10)

        lbl_splice_parallel = QLabel("🔀 并行线程数:")
        lbl_splice_parallel.setStyleSheet("color: #6D28D9; font-weight: bold; font-size: 13px;")
        row2.addWidget(lbl_splice_parallel)

        self.spin_parallel_splice = QSpinBox()
        self.spin_parallel_splice.setRange(1, 4)
        self.spin_parallel_splice.setValue(
            max(1, min(4, int(getattr(self.config_manager, "splice_parallel_tasks", 4) or 4)))
        )
        self.spin_parallel_splice.setSuffix(" 个任务")
        self.spin_parallel_splice.setFixedWidth(100)
        self.spin_parallel_splice.setToolTip("同时并行合并拼接的任务数量（范围 1 ~ 4；1 = 逐个拼接）")
        row2.addWidget(self.spin_parallel_splice)

        lbl_hint = QLabel("💡 请勾选需要合并拼接的任务（支持任意多选或全选，多任务并行无缝拼接导出 MP4 + SRT）：")
        lbl_hint.setStyleSheet("font-size: 12px; color: #5D4037;")
        row2.addWidget(lbl_hint)

        row2.addStretch()

        self.btn_sel_all = QPushButton("☑️ 全选")
        self.btn_sel_all.setStyleSheet("background-color: #64748B; color: white; padding: 4px 10px;")
        self.btn_sel_all.clicked.connect(self._select_all_rows)
        row2.addWidget(self.btn_sel_all)

        self.btn_sel_ready = QPushButton("⚡ 仅选含就绪视频的任务")
        self.btn_sel_ready.setStyleSheet("background-color: #0284C7; color: white; padding: 4px 10px;")
        self.btn_sel_ready.clicked.connect(self._select_ready_rows)
        row2.addWidget(self.btn_sel_ready)

        self.btn_sel_none = QPushButton("⏹️ 清空选择")
        self.btn_sel_none.setStyleSheet("background-color: #94A3B8; color: white; padding: 4px 10px;")
        self.btn_sel_none.clicked.connect(self._deselect_all_rows)
        row2.addWidget(self.btn_sel_none)

        cfg_vbox.addLayout(row2)
        layout.addWidget(cfg_frame)

        # Projects Table
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "选择", "任务名称 (Project)", "总句段", "视频就绪 / 缺失", "已有合成片状态", "批量拼接实时进度"
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 54)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 74)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(3, 130)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(4, 165)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, stretch=1)

        # Progress & Bottom Buttons
        prog_row = QHBoxLayout()
        self.lbl_overall_status = QLabel("就绪：请勾选需要拼接的任务，点击右下角【🎬 开始拼接并送入批量Reels】")
        self.lbl_overall_status.setStyleSheet("font-size: 12px; color: #5D4037;")
        prog_row.addWidget(self.lbl_overall_status, stretch=1)

        self.overall_bar = QProgressBar()
        self.overall_bar.setRange(0, 100)
        self.overall_bar.setValue(0)
        self.overall_bar.setFixedWidth(220)
        prog_row.addWidget(self.overall_bar)
        layout.addLayout(prog_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.btn_start = QPushButton("🎬 开始拼接并送入批量Reels")
        self.btn_start.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: white;
                font-size: 13px;
                font-weight: bold;
                padding: 8px 20px;
                border-radius: 5px;
            }
            QPushButton:hover { background-color: #059669; }
            QPushButton:disabled { background-color: #D7CCC8; color: #A1887F; }
        """)
        self.btn_start.clicked.connect(self.start_batch_splice)
        btn_row.addWidget(self.btn_start)

        self.btn_stop = QPushButton("⏹ 停止")
        self.btn_stop.setStyleSheet("background-color: #DC2626; color: white; padding: 8px 16px;")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_batch_splice)
        btn_row.addWidget(self.btn_stop)

        self.btn_close = QPushButton("关闭")
        self.btn_close.setStyleSheet("background-color: #8D6E63; color: white; padding: 8px 16px;")
        self.btn_close.clicked.connect(self.close)
        btn_row.addWidget(self.btn_close)

        layout.addLayout(btn_row)

    def load_projects_table(self):
        from models.project_model import ProjectModel
        from services.video_checker import VideoChecker

        self.table.setRowCount(0)
        self._projects_data = []
        self._row_by_proj_id = {}

        projects = self.storage_manager.list_projects() if self.storage_manager else []
        base_dir = self.storage_manager.get_base_path() if self.storage_manager else None

        for row_idx, p_info in enumerate(projects):
            p_id = str(p_info.get("id", ""))
            p_path = Path(p_info["path"])
            try:
                model = ProjectModel(p_path)
                report = VideoChecker.check_project_videos(model, p_path, base_storage_path=base_dir)
                segs = model.spanish_segments or []
                total_segs = len(segs)
                found_cnt = report.get("already_count", 0) + report.get("pending_count", 0)
                missing_cnt = report.get("missing_count", 0)
            except Exception:
                total_segs = 0
                found_cnt = 0
                missing_cnt = 0

            merged_dir = p_path / "merged_output"
            mp4_files = sorted(merged_dir.glob("*_成片.mp4")) if merged_dir.exists() else []
            has_merged = len(mp4_files) > 0

            self._projects_data.append({
                "id": p_id,
                "path": p_path,
                "total_segs": total_segs,
                "found_cnt": found_cnt,
                "missing_cnt": missing_cnt,
                "has_merged": has_merged,
            })
            self._row_by_proj_id[p_id] = row_idx

            self.table.insertRow(row_idx)

            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            chk_item.setCheckState(Qt.CheckState.Checked if found_cnt > 0 else Qt.CheckState.Unchecked)
            self.table.setItem(row_idx, 0, chk_item)

            self.table.setItem(row_idx, 1, QTableWidgetItem(p_id))

            it_total = QTableWidgetItem(str(total_segs))
            it_total.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row_idx, 2, it_total)

            it_vid = QTableWidgetItem(f"✅ {found_cnt} / ❌ {missing_cnt}")
            it_vid.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row_idx, 3, it_vid)

            merged_str = "🟢 已有合成片" if has_merged else "⚪ 未合成"
            it_m = QTableWidgetItem(merged_str)
            it_m.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row_idx, 4, it_m)

            prog_txt = "⏳ 等待拼接" if found_cnt > 0 else "⚠️ 无可用视频片段"
            self.table.setItem(row_idx, 5, QTableWidgetItem(prog_txt))

    def _select_all_rows(self):
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it:
                it.setCheckState(Qt.CheckState.Checked)

    def _deselect_all_rows(self):
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it:
                it.setCheckState(Qt.CheckState.Unchecked)

    def _select_ready_rows(self):
        for r, p_data in enumerate(self._projects_data):
            it = self.table.item(r, 0)
            if it:
                it.setCheckState(Qt.CheckState.Checked if p_data.get("found_cnt", 0) > 0 else Qt.CheckState.Unchecked)

    def start_batch_splice(self):
        selected_projects = []
        for r, p_data in enumerate(self._projects_data):
            it = self.table.item(r, 0)
            if it and it.checkState() == Qt.CheckState.Checked:
                selected_projects.append({"id": p_data["id"], "path": p_data["path"]})

        if not selected_projects:
            QMessageBox.information(self, "提示", "请至少勾选一个要合并拼接的任务。")
            return

        parallel_cnt = max(1, min(4, int(self.spin_parallel_splice.value())))
        # Persist 并行线程数 so it is remembered next time
        if self.config_manager is not None:
            try:
                self.config_manager.splice_parallel_tasks = parallel_cnt
                if hasattr(self.config_manager, "save"):
                    self.config_manager.save()
            except Exception as exc:
                print(f"Error saving splice parallel setting: {exc}")

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.spin_parallel_splice.setEnabled(False)
        self.overall_bar.setValue(0)

        from services.video_splice_service import BatchMultiProjectSpliceWorker
        base_dir = self.storage_manager.get_base_path() if self.storage_manager else None

        self._worker = BatchMultiProjectSpliceWorker(
            projects_list=selected_projects,
            base_storage_path=base_dir,
            skip_already_merged=self.chk_reuse_existing.isChecked(),
            parent=self,
            max_parallel_tasks=parallel_cnt,
        )
        self._worker.task_started.connect(self._on_task_started)
        self._worker.task_progress.connect(self._on_task_progress)
        self._worker.task_finished.connect(self._on_task_finished)
        self._worker.overall_progress.connect(self._on_overall_progress)
        self._worker.all_finished.connect(self._on_all_finished)
        self._worker.start()

    def stop_batch_splice(self):
        if self._worker and self._worker.isRunning():
            self.lbl_overall_status.setText("⏳ 正在停止批量拼接任务（终止所有运行中的 FFmpeg 进程）...")
            self._worker.cancel()

    def _on_task_started(self, proj_id: str):
        r = self._row_by_proj_id.get(proj_id)
        if r is not None:
            it = self.table.item(r, 5)
            if it:
                it.setText("🔄 正在裁切并合并片段...")
                it.setForeground(QColor("#0284C7"))

    def _on_task_progress(self, proj_id: str, pct: int, msg: str):
        r = self._row_by_proj_id.get(proj_id)
        if r is not None:
            it = self.table.item(r, 5)
            if it:
                it.setText(f"[{pct}%] {msg}")
                it.setForeground(QColor("#0284C7"))

    def _on_task_finished(self, proj_id: str, success: bool, result: dict):
        r = self._row_by_proj_id.get(proj_id)
        if r is None:
            return
        it_m = self.table.item(r, 4)
        it_prog = self.table.item(r, 5)
        if success:
            if it_m:
                it_m.setText("🟢 已有合成片")
            if it_prog:
                clips_cnt = result.get("total_clips", 0)
                dur = float(result.get("total_duration", 0.0) or 0.0)
                reused = " (复用已有成片)" if result.get("reused_existing") else f" (缓存复用 {result.get('cache_hits', 0)} 段)"
                it_prog.setText(f"✅ 合成完成: {clips_cnt} 段 · {dur:.1f}s{reused}")
                it_prog.setForeground(QColor("#15803D"))
        else:
            if it_prog:
                it_prog.setText(f"❌ 失败: {result.get('error', '未知错误')}")
                it_prog.setForeground(QColor("#DC2626"))

    def _on_overall_progress(self, done_tasks: int, total_tasks: int, msg: str):
        pct = int(done_tasks / total_tasks * 100) if total_tasks > 0 else 0
        self.overall_bar.setValue(pct)
        self.lbl_overall_status.setText(msg)

    def _on_all_finished(self, success_tasks: int, total_tasks: int, completed_payloads: list):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        if hasattr(self, "spin_parallel_splice"):
            self.spin_parallel_splice.setEnabled(True)
        self.overall_bar.setValue(100)

        self.lbl_overall_status.setText(
            f"🎉 批量拼接完成！成功合成 {success_tasks} / {total_tasks} 个任务。"
        )

        if self.chk_auto_send_reels.isChecked() and completed_payloads:
            if self.main_window and hasattr(self.main_window, "open_batch_in_batch_reels"):
                self.main_window.open_batch_in_batch_reels(completed_payloads)
                QMessageBox.information(
                    self,
                    "批量拼接并送入 Reels 完成",
                    f"🎉 已完成 {success_tasks} / {total_tasks} 个任务的合并拼接 (+SRT)，\n"
                    f"并已将全部 {len(completed_payloads)} 个成片一键送入【🎬 批量Reels】！",
                )
                self.accept()
                return

        QMessageBox.information(
            self,
            "批量拼接完成",
            f"🎉 已完成 {success_tasks} / {total_tasks} 个任务的合并拼接 (+SRT)！",
        )

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(5000)
        super().closeEvent(event)


