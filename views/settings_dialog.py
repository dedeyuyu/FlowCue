# -*- coding: utf-8 -*-
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QSpinBox, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QMessageBox, QGroupBox, QAbstractItemView, 
                             QLineEdit, QComboBox, QTextEdit, QScrollArea, QWidget,
                             QCheckBox, QGridLayout)
from PyQt6.QtCore import Qt


class NoWheelSpinBox(QSpinBox):
    """QSpinBox that ignores mouse wheel events so scrolling the dialog never accidentally modifies values."""
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
        self.resize(680, 750)
        
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
            QSpinBox {
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
        scroll_area.setWidgetResizable(True)
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
        self.combo_theme_mode.setFixedWidth(210)
        self.combo_theme_mode.currentIndexChanged.connect(self._on_theme_combo_changed)
        theme_layout.addWidget(self.combo_theme_mode)
        lbl_theme_hint = QLabel("(* 支持一键切换亮色模式与暗色模式，也可直接在主窗口右上角快捷切换)")
        lbl_theme_hint.setStyleSheet("color: #8D6E63; font-style: italic; font-size: 11px;")
        theme_layout.addWidget(lbl_theme_hint, stretch=1)
        main_layout.addWidget(group_theme)
        
        # Section 1: Batch Points Budget & Forced Split Marker
        group_points = QGroupBox("1. 单批次最高积分上限与强制断句标记 (Batch Settings)")
        pts_layout = QHBoxLayout(group_points)
        pts_layout.setContentsMargins(12, 12, 12, 12)
        
        pts_layout.addWidget(QLabel("每批次导出上限:"))
        self.spin_max_points = NoWheelSpinBox()
        self.spin_max_points.setRange(1, 1000)
        self.spin_max_points.setSuffix(" 积分")
        pts_layout.addWidget(self.spin_max_points)
        
        pts_layout.addSpacing(15)
        
        pts_layout.addWidget(QLabel("强制断句标记:"))
        self.txt_marker = QLineEdit()
        self.txt_marker.setFixedWidth(70)
        self.txt_marker.setPlaceholderText("///")
        pts_layout.addWidget(self.txt_marker)
        
        lbl_hint = QLabel("(* 出现此标记处强制切断)")
        lbl_hint.setStyleSheet("color: #8D6E63; font-style: italic; font-size: 11px;")
        pts_layout.addWidget(lbl_hint, stretch=1)
        
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
        from models.config_manager import ConfigManager
        for code, label in ConfigManager.SUPPORTED_LANGUAGES:
            self.combo_language.addItem(label, code)
        lang_layout.addWidget(self.combo_language, stretch=1)
        
        lbl_lang_hint = QLabel("(* 用于语音转文字时指定目标语言)")
        lbl_lang_hint.setStyleSheet("color: #8D6E63; font-style: italic; font-size: 11px;")
        lang_layout.addWidget(lbl_lang_hint)
        api_layout.addLayout(lang_layout)
        
        # Gladia API Keys
        api_layout.addWidget(QLabel("🔑 Gladia API Keys (每行一个，自动轮询):"))
        self.txt_gladia_keys = QTextEdit()
        self.txt_gladia_keys.setMaximumHeight(72)
        self.txt_gladia_keys.setPlaceholderText("粘贴 Gladia API Key，每行一个...\n例: gla_xxxxxxxxxxxxxxxxxxxx\ngla_yyyyyyyyyyyyyyyyyyyy")
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
        
        # ElevenLabs API Keys
        api_layout.addWidget(QLabel("🔑 ElevenLabs API Keys (每行一个，自动轮询):"))
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
        
        lbl_api_hint = QLabel("💡 提示: 支持多个 Key 轮询，当一个 Key 用量超限时自动切换下一个")
        lbl_api_hint.setStyleSheet("color: #0284C7; font-style: italic; font-size: 11px; font-weight: normal;")
        api_layout.addWidget(lbl_api_hint)
        
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
        for mode_code, mode_label in ConfigManager.SUPPORTED_GENERATION_MODES:
            self.combo_default_mode.addItem(mode_label, mode_code)
        row1_layout.addWidget(self.combo_default_mode, stretch=1)
        gen_rules_layout.addLayout(row1_layout)
        
        # Row 2: Aspect Ratio & Video Model
        row2_layout = QHBoxLayout()
        row2_layout.addWidget(QLabel("📐 默认画面尺寸:"))
        self.combo_default_aspect = NoWheelComboBox()
        self.combo_default_aspect.setStyleSheet(combo_style)
        self.combo_default_aspect.setFixedWidth(135)
        for aspect_code, aspect_label in ConfigManager.SUPPORTED_ASPECT_RATIOS:
            self.combo_default_aspect.addItem(aspect_label, aspect_code)
        row2_layout.addWidget(self.combo_default_aspect)
        
        row2_layout.addSpacing(20)
        
        row2_layout.addWidget(QLabel("🤖 默认生成模型:"))
        self.combo_default_model = NoWheelComboBox()
        self.combo_default_model.setStyleSheet(combo_style)
        for model_code, model_label in ConfigManager.SUPPORTED_VIDEO_MODELS:
            self.combo_default_model.addItem(model_label, model_code)
        row2_layout.addWidget(self.combo_default_model, stretch=1)
        gen_rules_layout.addLayout(row2_layout)
        
        lbl_gen_rules_hint = QLabel("💡 提示: 此处设置的间隔时间、生成模式（帧模式/素材模式）、尺寸比例（9:16/16:9）及模型（默认 Omni 1.1 Flash）将在复制/导出任务时自动同步给浏览器插件严格执行。")
        lbl_gen_rules_hint.setWordWrap(True)
        lbl_gen_rules_hint.setStyleSheet("color: #0284C7; font-style: italic; font-size: 11px;")
        gen_rules_layout.addWidget(lbl_gen_rules_hint)
        
        main_layout.addWidget(group_gen_rules)
        
        # Section 7: New Import Columns Mapping
        group_import_cols = QGroupBox("7. 新建导入表格列设置 (New Import Columns Mapping)")
        import_cols_layout = QVBoxLayout(group_import_cols)
        import_cols_layout.setContentsMargins(12, 12, 12, 12)
        import_cols_layout.setSpacing(10)

        top_col_bar = QHBoxLayout()
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

        btn_reset_import_col = QPushButton("🔄 恢复默认7列")
        btn_reset_import_col.setStyleSheet("background-color: #8D6E63; color: white; padding: 4px 10px; font-size: 12px;")
        btn_reset_import_col.clicked.connect(self._reset_import_columns_to_default)
        top_col_bar.addWidget(btn_reset_import_col)

        top_col_bar.addStretch()
        self.lbl_import_col_status = QLabel("")
        top_col_bar.addWidget(self.lbl_import_col_status)
        import_cols_layout.addLayout(top_col_bar)

        self.import_cols_container = QWidget()
        self.grid_import_cols = QGridLayout(self.import_cols_container)
        self.grid_import_cols.setContentsMargins(0, 4, 0, 4)
        self.grid_import_cols.setHorizontalSpacing(14)
        self.grid_import_cols.setVerticalSpacing(8)
        import_cols_layout.addWidget(self.import_cols_container)
        self.import_col_combos = []

        lbl_import_cols_hint = QLabel(
            "💡 规则说明：无论设置多少列，必须包含【名字、中文、原文、链接】这 4 项必填列。\n"
            "• 多列设为「名字」时会自动合并作为任务名称（例如第1列名字+第7列名字补充，或第1、2列都设为名字）。\n"
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

    def _rebuild_import_col_combos(self, col_types):
        """Rebuilds the grid of NoWheelComboBox widgets for import columns."""
        from models.config_manager import ConfigManager

        while self.grid_import_cols.count():
            item = self.grid_import_cols.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.import_col_combos = []

        combo_style = """
            QComboBox {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
                color: #5D4037;
            }
        """
        for idx, c_type in enumerate(col_types):
            row = idx // 3
            col_group = (idx % 3) * 2
            lbl = QLabel(f"第 {idx + 1} 列:")
            lbl.setStyleSheet("font-weight: bold; font-size: 12px; color: #5D4037;")
            cb = NoWheelComboBox()
            cb.setStyleSheet(combo_style)
            for code, label in ConfigManager.SUPPORTED_IMPORT_COLUMN_TYPES:
                cb.addItem(label, code)
            found_idx = cb.findData(c_type)
            cb.setCurrentIndex(found_idx if found_idx >= 0 else cb.findData("empty"))
            cb.currentIndexChanged.connect(self._update_import_cols_status)
            self.grid_import_cols.addWidget(lbl, row, col_group)
            self.grid_import_cols.addWidget(cb, row, col_group + 1)
            self.grid_import_cols.setColumnStretch(col_group + 1, 1)
            self.import_col_combos.append(cb)

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
        self.txt_marker.setText(getattr(self.cm, "forced_split_marker", "///"))
        self.spin_min_segment_chars.setValue(getattr(self.cm, "min_segment_chars", 0))
        
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

        # Read max batch points & forced split marker
        self.cm.max_batch_points = self.spin_max_points.value()
        self.cm.forced_split_marker = self.txt_marker.text().strip() or "///"
        self.cm.min_segment_chars = self.spin_min_segment_chars.value()
        
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
        
        # Read API keys (filter empty lines)
        gladia_text = self.txt_gladia_keys.toPlainText().strip()
        self.cm.gladia_api_keys = [k.strip() for k in gladia_text.split("\n") if k.strip()]
        
        elevenlabs_text = self.txt_elevenlabs_keys.toPlainText().strip()
        self.cm.elevenlabs_api_keys = [k.strip() for k in elevenlabs_text.split("\n") if k.strip()]
        
        # Read language
        self.cm.speech_language = self.combo_language.currentData() or "es"
        
        # Read end frame setting
        self.cm.enable_end_frame = self.chk_default_enable_end_frame.isChecked()
        
        # Read video generation default rules
        self.cm.task_interval = self.spin_task_interval.value()
        self.cm.default_generation_mode = self.combo_default_mode.currentData() or "VIDEO_FRAMES"
        self.cm.default_aspect_ratio = self.combo_default_aspect.currentData() or "9:16"
        self.cm.default_video_model = self.combo_default_model.currentData() or "omni_1_1_flash"
        self.cm.import_columns = [cb.currentData() for cb in self.import_col_combos]
        if hasattr(self, "combo_theme_mode"):
            self.cm.theme_mode = self.combo_theme_mode.currentData() or "light"
        
        if self.cm.save():
            QMessageBox.information(self, "成功", "设置保存成功！已按新规则生效。")
            self.accept()
        else:
            QMessageBox.critical(self, "错误", "保存配置文件失败。")
