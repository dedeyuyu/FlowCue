# -*- coding: utf-8 -*-
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QSpinBox, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QMessageBox, QGroupBox, QAbstractItemView, 
                             QLineEdit, QComboBox, QTextEdit, QScrollArea, QWidget,
                             QCheckBox, QGridLayout, QDoubleSpinBox, QSizePolicy)
from PyQt6.QtCore import Qt, QTimer


class NoWheelSpinBox(QSpinBox):
    """QSpinBox that ignores mouse wheel events so scrolling the dialog never accidentally modifies values."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):
        event.ignore()


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox that ignores mouse wheel events so scrolling the dialog never accidentally modifies values."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):
        event.ignore()


class NoWheelComboBox(QComboBox):
    """QComboBox that ignores mouse wheel events so scrolling the dialog never accidentally modifies options."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):
        event.ignore()


class SettingsDialog(QDialog):
    """Dialog for configuring app-wide rules (batch points, duration rules, points rules)."""
    
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self.cm = config_manager
        if self.cm:
            self.cm.load()
        self.init_ui()
        self.load_data()

    def init_ui(self):
        self.setWindowTitle("⚙️ 系统规则与积分设置 (Rules & Points Settings)")
        self.resize(740, 760)
        self.setMinimumSize(420, 480)
        self._current_import_cols_per_row = 0
        self.import_col_labels = []
        self.import_col_combos = []
        
        self.setStyleSheet("""
            QDialog {
                background-color: #FAF6F0;
                color: #5D4037;
                font-family: "Segoe UI", sans-serif;
            }
            QGroupBox {
                font-weight: bold;
                font-size: 13px;
                border: 1px solid #D7CCC8;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 15px;
                background-color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
                color: #5D4037;
            }
            QLabel {
                font-size: 13px;
                color: #5D4037;
            }
            QSpinBox, QDoubleSpinBox {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 13px;
            }
            QTableWidget {
                background-color: white;
                border: 1px solid #EFEBE9;
                border-radius: 4px;
                font-size: 12px;
            }
            QHeaderView::section {
                background-color: #EFEBE9;
                color: #5D4037;
                font-weight: bold;
                padding: 4px;
                border: 1px solid #D7CCC8;
            }
            QPushButton {
                background-color: #E0A96D;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 14px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #D2904C;
            }
            QPushButton:pressed {
                background-color: #B87635;
            }
            QPushButton#btn_reset {
                background-color: #B0BEC5;
                color: #37474F;
            }
            QPushButton#btn_reset:hover {
                background-color: #90A4AE;
            }
        """)
        
        # Use a scroll area so the dialog doesn't overflow on small screens
        scroll_area = QScrollArea(self)
        self.scroll_area = scroll_area
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("QScrollArea { border: none; background-color: #FAF6F0; }")
        scroll_content = QWidget()
        main_layout = QVBoxLayout(scroll_content)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        # Section 0: UI Theme Mode (Light / Dark)
        group_theme = QGroupBox("0. 界面显示主题 (UI Theme Mode)")
        theme_layout = QHBoxLayout(group_theme)
        theme_layout.setContentsMargins(12, 12, 12, 12)
        theme_layout.addWidget(QLabel("🎨 界面外观模式:"))
        self.combo_theme_mode = NoWheelComboBox()
        from models.config_manager import ConfigManager as _CM
        for t_code, t_label in _CM.SUPPORTED_THEME_MODES:
            self.combo_theme_mode.addItem(t_label, t_code)
        self.combo_theme_mode.setMinimumWidth(140)
        self.combo_theme_mode.setMaximumWidth(210)
        self.combo_theme_mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo_theme_mode.setMinimumContentsLength(6)
        self.combo_theme_mode.currentIndexChanged.connect(self._on_theme_combo_changed)
        theme_layout.addWidget(self.combo_theme_mode)
        lbl_theme_hint = QLabel("(* 支持一键切换亮色模式与暗色模式，也可直接在主窗口右上角快捷切换)")
        lbl_theme_hint.setWordWrap(True)
        lbl_theme_hint.setStyleSheet("color: #8D6E63; font-style: italic; font-size: 11px;")
        theme_layout.addWidget(lbl_theme_hint, stretch=1)
        main_layout.addWidget(group_theme)
        
        # Section 1: Batch Points Budget, Max Subtasks & Forced Split Marker
        group_points = QGroupBox("1. 单批次最高积分上限、子任务上限与强制断句标记 (Batch Settings)")
        pts_outer_layout = QVBoxLayout(group_points)
        pts_outer_layout.setContentsMargins(12, 12, 12, 12)
        pts_outer_layout.setSpacing(6)

        pts_layout = QHBoxLayout()
        pts_layout.addWidget(QLabel("每批次导出上限:"))
        self.spin_max_points = NoWheelSpinBox()
        self.spin_max_points.setRange(1, 1000)
        self.spin_max_points.setSuffix(" 积分")
        pts_layout.addWidget(self.spin_max_points)

        pts_layout.addSpacing(12)

        pts_layout.addWidget(QLabel("单任务子任务上限:"))
        self.spin_max_subtasks = NoWheelSpinBox()
        self.spin_max_subtasks.setRange(0, 100)
        self.spin_max_subtasks.setSuffix(" 个")
        self.spin_max_subtasks.setSpecialValueText("不限")
        self.spin_max_subtasks.setToolTip(
            "「🤖 全局托管」分配任务时，限制单个批次/单个账号分配的子任务（分镜）数量上限（默认 10 个，设为 0 表示不限制）"
        )
        pts_layout.addWidget(self.spin_max_subtasks)
        
        pts_layout.addSpacing(12)
        
        pts_layout.addWidget(QLabel("强制断句标记:"))
        self.txt_marker = QLineEdit()
        self.txt_marker.setFixedWidth(70)
        self.txt_marker.setPlaceholderText("///")
        pts_layout.addWidget(self.txt_marker)
        pts_layout.addStretch(1)
        pts_outer_layout.addLayout(pts_layout)
        
        lbl_hint = QLabel("(* 单任务子任务上限默认 10 个，与「🤖 全局托管」实时联动，设为 0 表示不限制；出现强制断句标记处强制切断)")
        lbl_hint.setWordWrap(True)
        lbl_hint.setStyleSheet("color: #8D6E63; font-style: italic; font-size: 11px;")
        pts_outer_layout.addWidget(lbl_hint)
        
        main_layout.addWidget(group_points)
        
        # Section 1.5: Minimum segment characters
        group_min_chars = QGroupBox("1.5 分段最小字符数 (Minimum Segment Characters)")
        min_chars_layout = QHBoxLayout(group_min_chars)
        min_chars_layout.setContentsMargins(12, 12, 12, 12)
        
        min_chars_layout.addWidget(QLabel("分段最小字符数:"))
        self.spin_min_segment_chars = NoWheelSpinBox()
        self.spin_min_segment_chars.setRange(0, 500)
        self.spin_min_segment_chars.setSuffix(" 字符")
        self.spin_min_segment_chars.setToolTip("最高优先级规则（仅次于 /// 强制分段）。分段时任何片段的字符数都不会低于此值，过短片段会自动与上下相邻段合并或均分重组。")
        min_chars_layout.addWidget(self.spin_min_segment_chars)
        
        lbl_min_hint = QLabel("(* 除 /// 强制断句外最高权重；过短片段自动与相邻段合并或均分为中等段落)")
        lbl_min_hint.setWordWrap(True)
        lbl_min_hint.setStyleSheet("color: #8D6E63; font-style: italic; font-size: 11px;")
        min_chars_layout.addWidget(lbl_min_hint, stretch=1)
        
        main_layout.addWidget(group_min_chars)
        
        # Section 2: Character count -> Duration rules
        group_char_dur = QGroupBox("2. 字符数与时长对应规则 (Char Count -> Seconds)")
        char_layout = QVBoxLayout(group_char_dur)
        char_layout.setContentsMargins(12, 12, 12, 12)
        
        self.table_char_dur = QTableWidget()
        self.table_char_dur.setColumnCount(2)
        self.table_char_dur.setHorizontalHeaderLabels(["字符上限 (≤ 字符数)", "对应时长 (秒)"])
        self.table_char_dur.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_char_dur.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        char_layout.addWidget(self.table_char_dur)
        
        btn_char_layout = QHBoxLayout()
        btn_add_char = QPushButton("＋ 添加行")
        btn_add_char.clicked.connect(self.add_char_row)
        btn_del_char = QPushButton("－ 删除行")
        btn_del_char.clicked.connect(self.del_char_row)
        btn_char_layout.addWidget(btn_add_char)
        btn_char_layout.addWidget(btn_del_char)
        btn_char_layout.addStretch()
        char_layout.addLayout(btn_char_layout)

        edge_dur_layout = QHBoxLayout()
        edge_dur_layout.setContentsMargins(0, 6, 0, 0)
        edge_dur_layout.addWidget(QLabel("⏱️ 首尾分段扩余时间:"))
        self.spin_edge_extra_duration = NoWheelSpinBox()
        self.spin_edge_extra_duration.setRange(0, 10)
        self.spin_edge_extra_duration.setSuffix(" 秒")
        self.spin_edge_extra_duration.setFixedWidth(95)
        self.spin_edge_extra_duration.setToolTip(
            "每个项目的第 1 个分段和最后一个分段在原本时长基础上额外增加的秒数（例如原本 6 秒加 2 秒变为 8 秒；若原本已达最大 10 秒则不再增加；设为 0 表示不增加）"
        )
        edge_dur_layout.addWidget(self.spin_edge_extra_duration)
        lbl_edge_dur_hint = QLabel("(* 每个任务的第1个分段与最后一个分段自动加此秒数，最高不超过10秒；已满10秒的不加)")
        lbl_edge_dur_hint.setWordWrap(True)
        lbl_edge_dur_hint.setStyleSheet("color: #8D6E63; font-style: italic; font-size: 11px;")
        edge_dur_layout.addWidget(lbl_edge_dur_hint, stretch=1)
        char_layout.addLayout(edge_dur_layout)
        
        main_layout.addWidget(group_char_dur)
        
        # Section 3: Duration -> Points cost rules
        group_dur_pts = QGroupBox("3. 时长与积分消耗对应规则 (Seconds -> Points Cost)")
        dur_pts_layout = QVBoxLayout(group_dur_pts)
        dur_pts_layout.setContentsMargins(12, 12, 12, 12)
        
        self.table_dur_pts = QTableWidget()
        self.table_dur_pts.setColumnCount(2)
        self.table_dur_pts.setHorizontalHeaderLabels(["时长 (秒)", "消耗积分"])
        self.table_dur_pts.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_dur_pts.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        dur_pts_layout.addWidget(self.table_dur_pts)
        
        btn_pts_layout = QHBoxLayout()
        btn_add_pts = QPushButton("＋ 添加行")
        btn_add_pts.clicked.connect(self.add_pts_row)
        btn_del_pts = QPushButton("－ 删除行")
        btn_del_pts.clicked.connect(self.del_pts_row)
        btn_pts_layout.addWidget(btn_add_pts)
        btn_pts_layout.addWidget(btn_del_pts)
        btn_pts_layout.addStretch()
        dur_pts_layout.addLayout(btn_pts_layout)
        
        main_layout.addWidget(group_dur_pts)
        
        # Section 4: Speech Extraction API Keys & Language
        group_api = QGroupBox("4. 语音提取 API 密钥与语言设置 (Speech API Keys & Language)")
        api_layout = QVBoxLayout(group_api)
        api_layout.setContentsMargins(12, 12, 12, 12)
        api_layout.setSpacing(8)
        
        # Language selector
        lang_layout = QHBoxLayout()
        lang_layout.addWidget(QLabel("🌐 识别语言:"))
        self.combo_language = NoWheelComboBox()
        self.combo_language.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo_language.setMinimumContentsLength(6)
        self.combo_language.setMinimumWidth(110)
        from models.config_manager import ConfigManager
        for code, label in ConfigManager.SUPPORTED_LANGUAGES:
            self.combo_language.addItem(label, code)
        lang_layout.addWidget(self.combo_language, stretch=1)
        
        lbl_lang_hint = QLabel("(* 用于语音转文字核对字幕；选择尼泊尔语时文案断行自动按尼泊尔语标点 । 和 ॥ 切分)")
        lbl_lang_hint.setWordWrap(True)
        lbl_lang_hint.setStyleSheet("color: #8D6E63; font-style: italic; font-size: 11px;")
        lang_layout.addWidget(lbl_lang_hint, stretch=2)
        api_layout.addLayout(lang_layout)
        
        # Gladia API Keys
        lbl_gladia_hdr = QLabel("🔑 Gladia API Keys (每行一个，多个 Key 并行使用，每个 Key 最多 3 个并发请求):")
        lbl_gladia_hdr.setWordWrap(True)
        api_layout.addWidget(lbl_gladia_hdr)
        self.txt_gladia_keys = QTextEdit()
        self.txt_gladia_keys.setMaximumHeight(88)
        self.txt_gladia_keys.setPlaceholderText("粘贴 Gladia API Key，每行一个...\n例: gla_xxxxxxxxxxxxxxxxxxxx\ngla_yyyyyyyyyyyyyyyyyyyy")
        self.txt_gladia_keys.textChanged.connect(self._update_gladia_key_count_label)
        self.txt_gladia_keys.setStyleSheet("""
            QTextEdit {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                font-family: Consolas, monospace;
                font-size: 12px;
                color: #5D4037;
                padding: 4px;
            }
        """)
        api_layout.addWidget(self.txt_gladia_keys)

        self.lbl_gladia_key_count = QLabel("")
        self.lbl_gladia_key_count.setWordWrap(True)
        self.lbl_gladia_key_count.setStyleSheet("color: #0F766E; font-size: 11px; font-weight: bold;")
        api_layout.addWidget(self.lbl_gladia_key_count)
        
        # ElevenLabs API Keys
        lbl_eleven_hdr = QLabel("🔑 ElevenLabs API Keys (每行一个，自动轮询):")
        lbl_eleven_hdr.setWordWrap(True)
        api_layout.addWidget(lbl_eleven_hdr)
        self.txt_elevenlabs_keys = QTextEdit()
        self.txt_elevenlabs_keys.setMaximumHeight(72)
        self.txt_elevenlabs_keys.setPlaceholderText("粘贴 ElevenLabs API Key，每行一个...\n例: sk_xxxxxxxxxxxxxxxxxxxx\nsk_yyyyyyyyyyyyyyyyyyyy")
        self.txt_elevenlabs_keys.setStyleSheet("""
            QTextEdit {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                font-family: Consolas, monospace;
                font-size: 12px;
                color: #5D4037;
                padding: 4px;
            }
        """)
        api_layout.addWidget(self.txt_elevenlabs_keys)
        
        lbl_api_hint = QLabel("💡 提示: 支持多个 Key 并行核对（每个 Key ≤3 个并发请求，N 个 Key 最多同时 3N 个请求）；某个 Key 失效或超限时自动切换其他 Key 重试")
        lbl_api_hint.setWordWrap(True)
        lbl_api_hint.setStyleSheet("color: #0284C7; font-style: italic; font-size: 11px; font-weight: normal;")
        api_layout.addWidget(lbl_api_hint)

        # Auto breath-trimming default padding (前留白 / 后留白)
        pad_layout = QHBoxLayout()
        pad_layout.setContentsMargins(0, 6, 0, 0)
        pad_layout.addWidget(QLabel("✂️ 自动切气口默认留白:  前留白"))
        self.spin_breath_pad_before = NoWheelDoubleSpinBox()
        self.spin_breath_pad_before.setRange(0.0, 2.0)
        self.spin_breath_pad_before.setSingleStep(0.05)
        self.spin_breath_pad_before.setDecimals(2)
        self.spin_breath_pad_before.setSuffix(" 秒")
        self.spin_breath_pad_before.setFixedWidth(90)
        self.spin_breath_pad_before.setToolTip("每个视频片段第一句发音前保留的气口缓冲时间（默认 0.10 秒）")
        pad_layout.addWidget(self.spin_breath_pad_before)
        pad_layout.addSpacing(10)
        pad_layout.addWidget(QLabel("后留白"))
        self.spin_breath_pad_after = NoWheelDoubleSpinBox()
        self.spin_breath_pad_after.setRange(0.0, 2.0)
        self.spin_breath_pad_after.setSingleStep(0.05)
        self.spin_breath_pad_after.setDecimals(2)
        self.spin_breath_pad_after.setSuffix(" 秒")
        self.spin_breath_pad_after.setFixedWidth(90)
        self.spin_breath_pad_after.setToolTip("每个视频片段最后发音结束后保留的气口缓冲时间（默认 0.15 秒）")
        pad_layout.addWidget(self.spin_breath_pad_after)
        lbl_pad_hint = QLabel("(* 「🎬 视频与文案比对」及批量核对自动切气口的默认值)")
        lbl_pad_hint.setWordWrap(True)
        lbl_pad_hint.setStyleSheet("color: #8D6E63; font-style: italic; font-size: 11px;")
        pad_layout.addWidget(lbl_pad_hint, stretch=1)
        api_layout.addLayout(pad_layout)
        
        main_layout.addWidget(group_api)
        
        # Section 5: End Frame Settings
        group_end_frame = QGroupBox("5. 视频首尾帧联动设置 (First & End Frame Settings)")
        end_frame_layout = QVBoxLayout(group_end_frame)
        end_frame_layout.setContentsMargins(12, 12, 12, 12)
        end_frame_layout.setSpacing(6)
        
        self.chk_default_enable_end_frame = QCheckBox("新建或加载项目时默认启用尾帧关联 (Enable End Frame by Default)")
        self.chk_default_enable_end_frame.setStyleSheet("font-size: 13px; color: #5D4037; font-weight: bold;")
        end_frame_layout.addWidget(self.chk_default_enable_end_frame)
        
        lbl_end_frame_hint = QLabel("💡 开启后，支持为每条分句文案关联尾帧图片，并将前一句的尾帧自动联动填充为后一句的首帧；导出任务时将附带尾帧数据。")
        lbl_end_frame_hint.setWordWrap(True)
        lbl_end_frame_hint.setStyleSheet("color: #8D6E63; font-style: italic; font-size: 11px;")
        end_frame_layout.addWidget(lbl_end_frame_hint)
        
        main_layout.addWidget(group_end_frame)
        
        # Section 6: Video Generation Default Rules & Task Interval
        group_gen_rules = QGroupBox("6. 视频生成默认参数与间隔设置 (Default Video Generation Rules)")
        gen_rules_layout = QVBoxLayout(group_gen_rules)
        gen_rules_layout.setContentsMargins(12, 12, 12, 12)
        gen_rules_layout.setSpacing(10)
        
        combo_style = """
            QComboBox {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 13px;
                color: #5D4037;
            }
        """
        
        # Row 1: Task Interval & Generation Mode
        row1_layout = QHBoxLayout()
        row1_layout.addWidget(QLabel("⏱️ 任务完成间隔时间:"))
        self.spin_task_interval = NoWheelSpinBox()
        self.spin_task_interval.setRange(0, 300)
        self.spin_task_interval.setSuffix(" 秒")
        self.spin_task_interval.setFixedWidth(95)
        self.spin_task_interval.setToolTip("每个任务完成之后等待多少秒再开始下一个任务（例如 3 秒、5 秒，设为 0 则无额外等待）")
        row1_layout.addWidget(self.spin_task_interval)
        
        row1_layout.addSpacing(20)
        
        row1_layout.addWidget(QLabel("🎬 默认生成模式:"))
        self.combo_default_mode = NoWheelComboBox()
        self.combo_default_mode.setStyleSheet(combo_style)
        self.combo_default_mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo_default_mode.setMinimumContentsLength(6)
        self.combo_default_mode.setMinimumWidth(110)
        for mode_code, mode_label in ConfigManager.SUPPORTED_GENERATION_MODES:
            self.combo_default_mode.addItem(mode_label, mode_code)
        row1_layout.addWidget(self.combo_default_mode, stretch=1)
        gen_rules_layout.addLayout(row1_layout)
        
        # Row 2: Project Management Aspect Ratio & Batch Generate Aspect Ratio
        row2_layout = QHBoxLayout()
        row2_layout.addWidget(QLabel("📐 项目管理尺寸比例:"))
        self.combo_default_aspect = NoWheelComboBox()
        self.combo_default_aspect.setStyleSheet(combo_style)
        self.combo_default_aspect.setFixedWidth(135)
        self.combo_default_aspect.setToolTip("用于「📋 项目管理」和「🤖 全局托管」导出的画面尺寸比例")
        for aspect_code, aspect_label in ConfigManager.SUPPORTED_ASPECT_RATIOS:
            self.combo_default_aspect.addItem(aspect_label, aspect_code)
        row2_layout.addWidget(self.combo_default_aspect)
        
        row2_layout.addSpacing(12)
        
        # 批量生成尺寸已改为在「🚀 批量生成」中按每个任务单独设置；此处仅保留隐藏控件以兼容旧配置
        self.combo_batch_default_aspect = NoWheelComboBox()
        self.combo_batch_default_aspect.setVisible(False)
        for aspect_code, aspect_label in ConfigManager.SUPPORTED_ASPECT_RATIOS:
            self.combo_batch_default_aspect.addItem(aspect_label, aspect_code)
        lbl_batch_aspect_hint = QLabel("💡 批量生成的尺寸请在「🚀 批量生成」中为每个任务单独设置")
        lbl_batch_aspect_hint.setWordWrap(True)
        lbl_batch_aspect_hint.setStyleSheet("color: #8D6E63; font-size: 12px; font-weight: normal;")
        row2_layout.addWidget(lbl_batch_aspect_hint, stretch=1)
        gen_rules_layout.addLayout(row2_layout)

        # Row 3: Video Model
        row3_layout = QHBoxLayout()
        row3_layout.addWidget(QLabel("🤖 默认生成模型:"))
        self.combo_default_model = NoWheelComboBox()
        self.combo_default_model.setStyleSheet(combo_style)
        self.combo_default_model.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo_default_model.setMinimumContentsLength(6)
        self.combo_default_model.setMinimumWidth(110)
        for model_code, model_label in ConfigManager.SUPPORTED_VIDEO_MODELS:
            self.combo_default_model.addItem(model_label, model_code)
        row3_layout.addWidget(self.combo_default_model, stretch=1)
        gen_rules_layout.addLayout(row3_layout)
        
        lbl_gen_rules_hint = QLabel("💡 提示: 「项目管理尺寸比例」与「批量生成尺寸比例」已独立分开配置；此处设置的间隔时间、生成模式、各自尺寸比例及模型将在复制/导出任务时自动同步给浏览器插件严格执行。")
        lbl_gen_rules_hint.setWordWrap(True)
        lbl_gen_rules_hint.setStyleSheet("color: #0284C7; font-style: italic; font-size: 11px;")
        gen_rules_layout.addWidget(lbl_gen_rules_hint)
        
        main_layout.addWidget(group_gen_rules)
        
        # Section 7: New Import Columns Mapping (自适应宽度自动换行 + 下拉框自动缩窄)
        group_import_cols = QGroupBox("7. 新建导入表格列设置 (New Import Columns Mapping)")
        import_cols_layout = QVBoxLayout(group_import_cols)
        import_cols_layout.setContentsMargins(12, 12, 12, 12)
        import_cols_layout.setSpacing(8)

        top_col_bar = QHBoxLayout()
        top_col_bar.setSpacing(6)
        top_col_bar.addWidget(QLabel("📊 表格总列数:"))
        self.spin_import_col_count = NoWheelSpinBox()
        self.spin_import_col_count.setRange(4, 20)
        self.spin_import_col_count.setSuffix(" 列")
        self.spin_import_col_count.setFixedWidth(85)
        self.spin_import_col_count.valueChanged.connect(self._on_import_col_count_changed)
        top_col_bar.addWidget(self.spin_import_col_count)

        btn_add_import_col = QPushButton("＋ 增加一列")
        btn_add_import_col.setStyleSheet("padding: 4px 10px; font-size: 12px;")
        btn_add_import_col.clicked.connect(lambda: self.spin_import_col_count.setValue(self.spin_import_col_count.value() + 1))
        top_col_bar.addWidget(btn_add_import_col)

        btn_del_import_col = QPushButton("－ 减少一列")
        btn_del_import_col.setStyleSheet("padding: 4px 10px; font-size: 12px;")
        btn_del_import_col.clicked.connect(lambda: self.spin_import_col_count.setValue(self.spin_import_col_count.value() - 1))
        top_col_bar.addWidget(btn_del_import_col)

        btn_reset_import_col = QPushButton("🔄 恢复默认8列")
        btn_reset_import_col.setStyleSheet("background-color: #8D6E63; color: white; padding: 4px 10px; font-size: 12px;")
        btn_reset_import_col.clicked.connect(self._reset_import_columns_to_default)
        top_col_bar.addWidget(btn_reset_import_col)
        top_col_bar.addStretch()
        import_cols_layout.addLayout(top_col_bar)

        self.lbl_import_col_status = QLabel("")
        self.lbl_import_col_status.setWordWrap(True)
        import_cols_layout.addWidget(self.lbl_import_col_status)

        self.import_cols_container = QWidget()
        self.import_cols_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.grid_import_cols = QGridLayout(self.import_cols_container)
        self.grid_import_cols.setContentsMargins(0, 4, 0, 4)
        self.grid_import_cols.setHorizontalSpacing(8)
        self.grid_import_cols.setVerticalSpacing(8)
        import_cols_layout.addWidget(self.import_cols_container)

        lbl_import_cols_hint = QLabel(
            "💡 规则说明：无论设置多少列，必须包含【名字、中文、原文、链接】这 4 项必填列。\n"
            "• 多列设为「名字」时会自动合并作为任务名称（例如第1列名字+第7列名字补充，或第1、2列都设为名字）。\n"
            "• 设为「✂️ 断行文本」的列（默认第8列，选填）在导入时会自动保存为该任务的自定义 SRT 断行字幕文案，在最终合并拼接视频时自动按此断行生成 SRT 字幕。\n"
            "• 设为「空列」的列在复制表格导入时会自动跳过不读取，方便匹配您自己的表格列习惯。"
        )
        lbl_import_cols_hint.setWordWrap(True)
        lbl_import_cols_hint.setStyleSheet("color: #0284C7; font-style: italic; font-size: 11px;")
        import_cols_layout.addWidget(lbl_import_cols_hint)

        main_layout.addWidget(group_import_cols)
        
        # Bottom Buttons
        bottom_layout = QHBoxLayout()
        btn_reset = QPushButton("🔄 恢复默认设置")
        btn_reset.setObjectName("btn_reset")
        btn_reset.clicked.connect(self.reset_defaults)
        bottom_layout.addWidget(btn_reset)
        
        bottom_layout.addStretch()
        
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        bottom_layout.addWidget(btn_cancel)
        
        btn_save = QPushButton("💾 保存设置")
        btn_save.setStyleSheet("background-color: #10B981; color: white; font-weight: bold;")
        btn_save.clicked.connect(self.save_settings)
        bottom_layout.addWidget(btn_save)
        
        main_layout.addLayout(bottom_layout)
        
        # Finalize scroll area
        scroll_content.setLayout(main_layout)
        scroll_area.setWidget(scroll_content)
        
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(scroll_area)

    def _compute_import_cols_per_row(self) -> int:
        """根据当前窗口可用宽度自动计算每行放置几列（支持 1 / 2 / 3 / 4 列自动换行）。"""
        avail_w = 0
        if hasattr(self, "import_cols_container") and self.import_cols_container is not None:
            avail_w = self.import_cols_container.width()
        if avail_w <= 100:
            avail_w = max(200, self.width() - 68)
        if avail_w >= 860:
            return 4
        if avail_w >= 540:
            return 3
        if avail_w >= 350:
            return 2
        return 1

    def _relayout_import_col_combos(self, force: bool = False):
        """当窗口宽度变化时自动重排各列下拉框，实现响应式自动换行且下拉框自动缩窄。"""
        if not self.import_col_combos or not self.import_col_labels:
            return
        cols_per_row = self._compute_import_cols_per_row()
        if not force and cols_per_row == self._current_import_cols_per_row:
            return
        self._current_import_cols_per_row = cols_per_row

        # Clear layout items without deleting widgets
        while self.grid_import_cols.count():
            self.grid_import_cols.takeAt(0)

        # Reset stretches on all possible columns (up to 8 grid columns)
        for c in range(8):
            self.grid_import_cols.setColumnStretch(c, 0)

        for idx, (lbl, cb) in enumerate(zip(self.import_col_labels, self.import_col_combos)):
            row = idx // cols_per_row
            col_group = (idx % cols_per_row) * 2
            self.grid_import_cols.addWidget(lbl, row, col_group)
            self.grid_import_cols.addWidget(cb, row, col_group + 1)

        for g in range(cols_per_row):
            self.grid_import_cols.setColumnStretch(g * 2 + 1, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_import_col_combos(force=False)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, lambda: self._relayout_import_col_combos(force=True))

    def _rebuild_import_col_combos(self, col_types):
        """Rebuilds the responsive grid of NoWheelComboBox widgets for import columns."""
        from models.config_manager import ConfigManager

        while self.grid_import_cols.count():
            item = self.grid_import_cols.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.import_col_labels = []
        self.import_col_combos = []

        combo_style = """
            QComboBox {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 4px 6px;
                font-size: 12px;
                color: #5D4037;
            }
        """
        for idx, c_type in enumerate(col_types):
            lbl = QLabel(f"第 {idx + 1} 列:")
            lbl.setStyleSheet("font-weight: bold; font-size: 12px; color: #5D4037;")
            lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
            cb = NoWheelComboBox()
            cb.setStyleSheet(combo_style)
            cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(4)
            cb.setMinimumWidth(75)
            cb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            for code, label in ConfigManager.SUPPORTED_IMPORT_COLUMN_TYPES:
                cb.addItem(label, code)
            found_idx = cb.findData(c_type)
            cb.setCurrentIndex(found_idx if found_idx >= 0 else cb.findData("empty"))
            cb.currentIndexChanged.connect(self._update_import_cols_status)
            self.import_col_labels.append(lbl)
            self.import_col_combos.append(cb)

        self._relayout_import_col_combos(force=True)
        self._update_import_cols_status()
        try:
            from services.theme_manager import ThemeManager
            ThemeManager.refresh_widget_style(self.import_cols_container, recursive=True)
        except Exception:
            pass

    def _on_theme_combo_changed(self):
        try:
            from services.theme_manager import ThemeManager
            mode = self.combo_theme_mode.currentData() or "light"
            ThemeManager.apply_theme(mode)
        except Exception:
            pass

    def reject(self):
        try:
            from services.theme_manager import ThemeManager
            orig_mode = getattr(self.cm, "theme_mode", "light") if self.cm else "light"
            if ThemeManager.get_mode() != orig_mode:
                ThemeManager.apply_theme(orig_mode)
        except Exception:
            pass
        super().reject()

    def _on_import_col_count_changed(self, new_count):
        cur_types = [cb.currentData() for cb in self.import_col_combos]
        if new_count > len(cur_types):
            cur_types.extend(["empty"] * (new_count - len(cur_types)))
        else:
            cur_types = cur_types[:new_count]
        self._rebuild_import_col_combos(cur_types)

    def _reset_import_columns_to_default(self):
        from models.config_manager import ConfigManager
        default_cols = list(ConfigManager.DEFAULT_IMPORT_COLUMNS)
        self.spin_import_col_count.blockSignals(True)
        self.spin_import_col_count.setValue(len(default_cols))
        self.spin_import_col_count.blockSignals(False)
        self._rebuild_import_col_combos(default_cols)

    def _get_missing_import_column_names(self):
        from models.config_manager import ConfigManager
        selected = {cb.currentData() for cb in self.import_col_combos}
        missing = [label for code, label in ConfigManager.REQUIRED_IMPORT_COLUMN_TYPES if code not in selected]
        return missing

    def _update_import_cols_status(self):
        missing = self._get_missing_import_column_names()
        if not missing:
            self.lbl_import_col_status.setText("✅ 已包含全部 4 项必填列（名字、中文、原文、链接）")
            self.lbl_import_col_status.setStyleSheet("color: #059669; font-weight: bold; font-size: 12px;")
        else:
            self.lbl_import_col_status.setText(f"⚠️ 缺少必填列：{'、'.join(missing)}")
            self.lbl_import_col_status.setStyleSheet("color: #DC2626; font-weight: bold; font-size: 12px;")

    def load_data(self):
        if hasattr(self, "combo_theme_mode"):
            theme_val = getattr(self.cm, "theme_mode", "light")
            t_idx = self.combo_theme_mode.findData(theme_val)
            self.combo_theme_mode.blockSignals(True)
            self.combo_theme_mode.setCurrentIndex(t_idx if t_idx >= 0 else 0)
            self.combo_theme_mode.blockSignals(False)

        self.spin_max_points.setValue(self.cm.max_batch_points)
        self.spin_max_subtasks.setValue(int(getattr(self.cm, "max_subtasks_per_batch", 10)))
        self.txt_marker.setText(getattr(self.cm, "forced_split_marker", "///"))
        self.spin_min_segment_chars.setValue(getattr(self.cm, "min_segment_chars", 0))
        self.spin_edge_extra_duration.setValue(getattr(self.cm, "edge_extra_duration", 2))
        
        # Load char -> duration rules
        self.table_char_dur.setRowCount(0)
        for r in self.cm.char_duration_rules:
            row = self.table_char_dur.rowCount()
            self.table_char_dur.insertRow(row)
            self.table_char_dur.setItem(row, 0, QTableWidgetItem(str(r["max_chars"])))
            self.table_char_dur.setItem(row, 1, QTableWidgetItem(str(r["duration"])))
            
        # Load duration -> points rules
        self.table_dur_pts.setRowCount(0)
        for r in self.cm.duration_points_rules:
            row = self.table_dur_pts.rowCount()
            self.table_dur_pts.insertRow(row)
            self.table_dur_pts.setItem(row, 0, QTableWidgetItem(str(r["duration"])))
            self.table_dur_pts.setItem(row, 1, QTableWidgetItem(str(r["points"])))
        
        # Load API keys
        self.txt_gladia_keys.setPlainText("\n".join(self.cm.gladia_api_keys))
        self.txt_elevenlabs_keys.setPlainText("\n".join(self.cm.elevenlabs_api_keys))
        self._update_gladia_key_count_label()

        # Load auto breath-trimming default padding (前留白 / 后留白)
        from models.config_manager import ConfigManager as _CMPad
        self.spin_breath_pad_before.setValue(
            float(getattr(self.cm, "breath_pad_before", _CMPad.DEFAULT_BREATH_PAD_BEFORE))
        )
        self.spin_breath_pad_after.setValue(
            float(getattr(self.cm, "breath_pad_after", _CMPad.DEFAULT_BREATH_PAD_AFTER))
        )
        
        # Load language selection
        lang_code = getattr(self.cm, "speech_language", "es")
        idx = self.combo_language.findData(lang_code)
        if idx >= 0:
            self.combo_language.setCurrentIndex(idx)
        else:
            self.combo_language.setCurrentIndex(0)  # Default to Spanish
            
        # Load end frame setting
        self.chk_default_enable_end_frame.setChecked(getattr(self.cm, "enable_end_frame", False))
        
        # Load video generation default rules
        self.spin_task_interval.setValue(getattr(self.cm, "task_interval", 5))
        
        mode_code = getattr(self.cm, "default_generation_mode", "VIDEO_FRAMES")
        idx_mode = self.combo_default_mode.findData(mode_code)
        self.combo_default_mode.setCurrentIndex(idx_mode if idx_mode >= 0 else 0)
        
        aspect_code = getattr(self.cm, "default_aspect_ratio", "9:16")
        idx_aspect = self.combo_default_aspect.findData(aspect_code)
        self.combo_default_aspect.setCurrentIndex(idx_aspect if idx_aspect >= 0 else 0)

        batch_aspect_code = getattr(self.cm, "batch_default_aspect_ratio", aspect_code)
        idx_batch_aspect = self.combo_batch_default_aspect.findData(batch_aspect_code)
        self.combo_batch_default_aspect.setCurrentIndex(idx_batch_aspect if idx_batch_aspect >= 0 else 0)
        
        model_code = getattr(self.cm, "default_video_model", "omni_1_1_flash")
        idx_model = self.combo_default_model.findData(model_code)
        self.combo_default_model.setCurrentIndex(idx_model if idx_model >= 0 else 0)

        # Load import columns mapping
        from models.config_manager import ConfigManager
        import_cols = list(getattr(self.cm, "import_columns", None) or ConfigManager.DEFAULT_IMPORT_COLUMNS)
        self.spin_import_col_count.blockSignals(True)
        self.spin_import_col_count.setValue(len(import_cols))
        self.spin_import_col_count.blockSignals(False)
        self._rebuild_import_col_combos(import_cols)

    def add_char_row(self):
        row = self.table_char_dur.rowCount()
        self.table_char_dur.insertRow(row)
        self.table_char_dur.setItem(row, 0, QTableWidgetItem("200"))
        self.table_char_dur.setItem(row, 1, QTableWidgetItem("12"))

    @staticmethod
    def _parse_key_lines(text: str) -> list:
        """Parses one-key-per-line text into a de-duplicated key list (order preserved)."""
        keys = []
        for k in str(text or "").splitlines():
            k = k.strip()
            if k and k not in keys:
                keys.append(k)
        return keys

    def _update_gladia_key_count_label(self):
        if not hasattr(self, "lbl_gladia_key_count"):
            return
        n = len(self._parse_key_lines(self.txt_gladia_keys.toPlainText()))
        if n <= 0:
            self.lbl_gladia_key_count.setText("⚠️ 未填写 Gladia Key")
        else:
            self.lbl_gladia_key_count.setText(f"✅ 已填写 {n} 个 Gladia Key → 文案核对最多同时 {n * 3} 个请求并行")

    def del_char_row(self):
        r = self.table_char_dur.currentRow()
        if r >= 0:
            self.table_char_dur.removeRow(r)

    def add_pts_row(self):
        row = self.table_dur_pts.rowCount()
        self.table_dur_pts.insertRow(row)
        self.table_dur_pts.setItem(row, 0, QTableWidgetItem("12"))
        self.table_dur_pts.setItem(row, 1, QTableWidgetItem("18"))

    def del_pts_row(self):
        r = self.table_dur_pts.currentRow()
        if r >= 0:
            self.table_dur_pts.removeRow(r)

    def reset_defaults(self):
        res = QMessageBox.question(self, "确认", "确定要恢复系统默认的积分与时长规则吗？", 
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if res == QMessageBox.StandardButton.Yes:
            self.cm.reset_to_defaults()
            self.load_data()

    def save_settings(self):
        # Commit any in-progress cell editor in tables
        self.table_char_dur.clearFocus()
        self.table_dur_pts.clearFocus()
        self.setFocus()
        
        # Validate import columns first
        missing_import_cols = self._get_missing_import_column_names()
        if missing_import_cols:
            QMessageBox.warning(
                self,
                "新建导入列设置不完整",
                f"新建导入表格列必须包含【名字、中文、原文、链接】这 4 项必填列！\n\n"
                f"当前缺少：{'、'.join(missing_import_cols)}\n"
                f"请在「7. 新建导入表格列设置」中补充后再保存。"
            )
            return

        # Read max batch points, max subtasks & forced split marker
        self.cm.max_batch_points = self.spin_max_points.value()
        self.cm.max_subtasks_per_batch = self.spin_max_subtasks.value()
        self.cm.forced_split_marker = self.txt_marker.text().strip() or "///"
        self.cm.min_segment_chars = self.spin_min_segment_chars.value()
        self.cm.edge_extra_duration = self.spin_edge_extra_duration.value()
        
        # Read char -> duration rules
        new_char_rules = []
        for r in range(self.table_char_dur.rowCount()):
            c_item = self.table_char_dur.item(r, 0)
            d_item = self.table_char_dur.item(r, 1)
            try:
                max_c = int(c_item.text().strip()) if c_item else 0
                dur = int(d_item.text().strip()) if d_item else 0
                if max_c > 0 and dur > 0:
                    new_char_rules.append({"max_chars": max_c, "duration": dur})
            except ValueError:
                pass
                
        if not new_char_rules:
            QMessageBox.warning(self, "警告", "字符数与时长规则不能为空！")
            return
            
        new_char_rules.sort(key=lambda x: x["max_chars"])
        self.cm.char_duration_rules = new_char_rules
        
        # Read duration -> points rules
        new_pts_rules = []
        for r in range(self.table_dur_pts.rowCount()):
            d_item = self.table_dur_pts.item(r, 0)
            p_item = self.table_dur_pts.item(r, 1)
            try:
                dur = int(d_item.text().strip()) if d_item else 0
                pts = int(p_item.text().strip()) if p_item else 0
                if dur > 0 and pts > 0:
                    new_pts_rules.append({"duration": dur, "points": pts})
            except ValueError:
                pass
                
        if not new_pts_rules:
            QMessageBox.warning(self, "警告", "时长与积分对应规则不能为空！")
            return
            
        self.cm.duration_points_rules = new_pts_rules
        
        # Read API keys (filter empty lines, de-duplicate while preserving order)
        gladia_text = self.txt_gladia_keys.toPlainText().strip()
        self.cm.gladia_api_keys = self._parse_key_lines(gladia_text)
        
        elevenlabs_text = self.txt_elevenlabs_keys.toPlainText().strip()
        self.cm.elevenlabs_api_keys = self._parse_key_lines(elevenlabs_text)

        # Read auto breath-trimming default padding (前留白 / 后留白)
        self.cm.breath_pad_before = round(float(self.spin_breath_pad_before.value()), 3)
        self.cm.breath_pad_after = round(float(self.spin_breath_pad_after.value()), 3)
        
        # Read language
        self.cm.speech_language = self.combo_language.currentData() or "es"
        
        # Read end frame setting
        self.cm.enable_end_frame = self.chk_default_enable_end_frame.isChecked()
        
        # Read video generation default rules
        self.cm.task_interval = self.spin_task_interval.value()
        self.cm.default_generation_mode = self.combo_default_mode.currentData() or "VIDEO_FRAMES"
        self.cm.default_aspect_ratio = self.combo_default_aspect.currentData() or "9:16"
        self.cm.batch_default_aspect_ratio = self.combo_batch_default_aspect.currentData() or "9:16"
        self.cm.default_video_model = self.combo_default_model.currentData() or "omni_1_1_flash"
        self.cm.import_columns = [cb.currentData() for cb in self.import_col_combos]
        if hasattr(self, "combo_theme_mode"):
            self.cm.theme_mode = self.combo_theme_mode.currentData() or "light"
        
        if self.cm.save():
            QMessageBox.information(self, "成功", "设置保存成功！已按新规则生效。")
            self.accept()
        else:
            QMessageBox.critical(self, "错误", "保存配置文件失败。")
