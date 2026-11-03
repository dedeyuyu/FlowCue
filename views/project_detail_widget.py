# -*- coding: utf-8 -*-
"""项目管理详情页（入口）。

具体功能按模块拆分在 views/project_detail/ 下：
  - segments_mixin.py   分句表格
  - property_mixin.py   片段属性面板
  - bulk_mixin.py       多选批量设置 / 复制为表格
  - media_mixin.py      素材管理页
  - dispatch_mixin.py   拆批 / 导出 / 自动分发
  - batch_export_dialog.py 批量导出对话框
"""
from views.project_detail.common import *  # noqa: F401,F403
from views.project_detail.common import (logger, NoWheelComboBox,  # noqa: F401  (保持旧的导入路径可用)
                                         flip_image_horizontally_replace, encode_image_to_data_url)
from views.project_detail.segments_mixin import SegmentsTableMixin
from views.project_detail.property_mixin import PropertyPanelMixin
from views.project_detail.bulk_mixin import BulkEditMixin
from views.project_detail.media_mixin import MediaTabMixin
from views.project_detail.dispatch_mixin import DispatchMixin
from views.project_detail.batch_export_dialog import BatchExportDialog  # noqa: F401


class ProjectDetailWidget(SegmentsTableMixin, PropertyPanelMixin, BulkEditMixin,
                          MediaTabMixin, DispatchMixin, QWidget):
    """Widget displaying detail and editing options for a selected project."""
    
    project_saved_signal = pyqtSlot() # To trigger sidebar reload if names change (not needed in v1, but good to have)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project_path = None
        self.project_model = None
        self.download_thread = None
        self.template_manager = None
        self.config_manager = None
        self.plugin_server = None
        self.copied_rows = set()
        self.dispatched_indices = set()
        self.is_auto_polling_active = False
        self.polling_timer = None
        self.active_batch_dialog = None
        self.enable_end_frame = False
        self.current_prop_row = -1
        self.init_ui()

    def set_template_manager(self, tm):
        self.template_manager = tm

    def set_config_manager(self, cm):
        self.config_manager = cm

    def set_plugin_server(self, ps):
        self.plugin_server = ps
        if self.plugin_server:
            self.plugin_server.report_received_signal.connect(self.on_plugin_report_received)
            self.plugin_server.client_connected_signal.connect(self.on_plugin_clients_changed)
            self.plugin_server.client_disconnected_signal.connect(self.on_plugin_clients_changed)
            self.plugin_server.client_updated_signal.connect(self.on_plugin_clients_changed)

    def on_plugin_clients_changed(self, info=None):
        if self.active_batch_dialog and self.active_batch_dialog.isVisible():
            self.active_batch_dialog.refresh_workers_list()

    def init_ui(self):
        # Base styling for warm theme
        self.setStyleSheet("""
            QWidget#detail_root {
                background-color: #FAF6F0;
            }
            QLabel#lbl_proj_title {
                font-size: 16px;
                font-weight: bold;
                color: #5D4037;
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
            QPushButton:pressed {
                background-color: #B87635;
            }
            QPushButton#btn_delete_segment {
                background-color: #E57373;
            }
            QPushButton#btn_delete_segment:hover {
                background-color: #EF5350;
            }
            QPushButton#btn_open_folder {
                background-color: #D7CCC8;
                color: #5D4037;
            }
            QPushButton#btn_open_folder:hover {
                background-color: #BCAAA4;
            }
            QTextEdit {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                color: #3E2723;
                font-family: Consolas, sans-serif;
                font-size: 13px;
            }
            QTableWidget {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                gridline-color: #EFEBE9;
                selection-background-color: #FFE0B2;
                selection-color: #5D4037;
            }
            QHeaderView::section {
                background-color: #D7CCC8;
                color: #5D4037;
                padding: 4px;
                font-weight: bold;
                border: 1px solid #EFEBE9;
            }
            QTabWidget::pane {
                border: 1px solid #D7CCC8;
                background-color: #FAF6F0;
                border-radius: 4px;
            }
            QTabBar::tab {
                background-color: #EFEBE9;
                color: #795548;
                padding: 8px 16px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background-color: #FAF6F0;
                color: #5D4037;
                border: 1px solid #D7CCC8;
                border-bottom-color: #FAF6F0;
            }
        """)
        
        self.setObjectName("detail_root")
        
        # We start in a "No Selection" state
        self.layout_stack = QVBoxLayout(self)
        
        self.no_selection_widget = QLabel("请在左侧选择一个工程项目以查看详情...")
        self.no_selection_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.no_selection_widget.setStyleSheet("font-size: 16px; color: #8D6E63; font-style: italic;")
        self.layout_stack.addWidget(self.no_selection_widget)
        
        # Create the main content widget (initially hidden)
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        
        # Header Row
        header_layout = QHBoxLayout()
        self.lbl_proj_title = QLabel("项目名称:")
        self.lbl_proj_title.setObjectName("lbl_proj_title")
        header_layout.addWidget(self.lbl_proj_title)
        
        header_layout.addStretch()

        self.btn_header_multi_select = QPushButton("🖼️ 批量选择预设")
        self.btn_header_multi_select.setToolTip(
            "打开全新的多选与图片预设可视化管理大窗：\n"
            "• 一目了然展示所有断句图片（支持 Ctrl+鼠标滚轮无级缩放）\n"
            "• 支持 Ctrl / Shift / 鼠标直接框选多个图片，在上方选项卡直接指定各种预设\n"
            "• 自带可折叠/展开的「任务资源图库」，多选断句后点击资源图即可批量更换\n"
            "• 支持在窗口内直接切换任务"
        )
        self.btn_header_multi_select.setStyleSheet("background-color: #10B981; color: white; font-weight: bold;")
        self.btn_header_multi_select.clicked.connect(self.open_bulk_edit_dialog)
        self.btn_header_multi_select.setVisible(False)
        header_layout.addWidget(self.btn_header_multi_select)
        
        self.btn_quick_review_proj = QPushButton("👁️ 快速审核")
        self.btn_quick_review_proj.setToolTip("跳转到「👁️ 素材快速审核」标签页并直接加载本项目的全部视频与图片素材")
        self.btn_quick_review_proj.setStyleSheet("background-color: #10B981; color: white; font-weight: bold;")
        self.btn_quick_review_proj.clicked.connect(self.jump_to_visual_review)
        self.btn_quick_review_proj.setVisible(False)
        header_layout.addWidget(self.btn_quick_review_proj)

        self.btn_open_folder = QPushButton("📂 打开文件夹")
        self.btn_open_folder.setObjectName("btn_open_folder")
        self.btn_open_folder.clicked.connect(self.open_project_folder)
        self.btn_open_folder.setVisible(False)
        header_layout.addWidget(self.btn_open_folder)
        
        self.content_layout.addLayout(header_layout)
        
        # Tabs
        self.tabs = QTabWidget()
        self.init_text_tab()
        self.init_media_tab()
        self.init_compare_tab()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.content_layout.addWidget(self.tabs)
        
        self.layout_stack.addWidget(self.content_widget)
        self.content_widget.setVisible(False)

    def _on_tab_changed(self, index):
        """Pauses media playback if switching away from video compare tab."""
        if hasattr(self, 'video_compare_widget') and self.video_compare_widget:
            compare_index = self.tabs.indexOf(self.video_compare_widget)
            if compare_index != -1 and index == compare_index and getattr(self, "_compare_dirty", False) and self.project_model:
                self._compare_dirty = False
                self.video_compare_widget.set_project(self.project_model, self.project_path, self.config_manager)
            if compare_index != -1 and index != compare_index:
                if hasattr(self.video_compare_widget, 'media_player') and self.video_compare_widget.media_player:
                    try:
                        self.video_compare_widget.media_player.pause()
                    except Exception:
                        pass

    def cleanup(self):
        """Cleans up active download threads and video compare widget resources."""
        if hasattr(self, 'download_thread') and self.download_thread:
            try:
                if self.download_thread.isRunning():
                    self.download_thread.stop()
            except Exception:
                pass
            self.download_thread = None
            
        if hasattr(self, 'video_compare_widget') and self.video_compare_widget:
            if hasattr(self.video_compare_widget, 'cleanup'):
                self.video_compare_widget.cleanup()

        # 停止后台缩略图解码线程
        th = getattr(self, "_icon_thread", None)
        if th is not None:
            try:
                if th.isRunning():
                    th.requestInterruption()
                    th.wait(2000)
            except Exception:
                pass

    def init_text_tab(self):
        tab_widget = QWidget()
        tab_layout = QVBoxLayout(tab_widget)
        tab_layout.setContentsMargins(10, 10, 10, 10)
        tab_layout.setSpacing(10)
        
        # 1. Top Selectors Layout
        selectors_layout = QHBoxLayout()
        selectors_layout.setSpacing(10)
        
        selectors_layout.addWidget(QLabel("选择统一提示词模板:"))
        self.combo_templates = QComboBox()
        self.combo_templates.setMaxVisibleItems(12)
        self.combo_templates.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.combo_templates.setStyleSheet("""
            QComboBox {
                combobox-popup: 0;
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 13px;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #D7CCC8;
                background-color: white;
                selection-background-color: #FFE0B2;
                selection-color: #5D4037;
                outline: none;
            }
            QComboBox QAbstractItemView::item {
                min-height: 26px;
            }
        """)
        self.combo_templates.currentIndexChanged.connect(self.on_template_changed)
        selectors_layout.addWidget(self.combo_templates, stretch=1)
        
        selectors_layout.addWidget(QLabel("选择统一运镜预设:"))
        self.combo_motions = QComboBox()
        self.combo_motions.setMaxVisibleItems(12)
        self.combo_motions.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.combo_motions.setStyleSheet("""
            QComboBox {
                combobox-popup: 0;
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 13px;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #D7CCC8;
                background-color: white;
                selection-background-color: #FFE0B2;
                selection-color: #5D4037;
                outline: none;
            }
            QComboBox QAbstractItemView::item {
                min-height: 26px;
            }
        """)
        self.combo_motions.currentIndexChanged.connect(self.on_motion_changed)
        selectors_layout.addWidget(self.combo_motions, stretch=1)
        
        self.btn_reset_all_segments = QPushButton("⚡ 重置所有片段为统一设置")
        self.btn_reset_all_segments.setStyleSheet("""
            QPushButton {
                background-color: #8D6E63;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 5px 10px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #795548;
            }
        """)
        self.btn_reset_all_segments.setToolTip("清空所有片段的单独模板与镜头设置，重新统一使用上方的全局设置。")
        self.btn_reset_all_segments.clicked.connect(self.reset_all_segments_to_unified)
        selectors_layout.addWidget(self.btn_reset_all_segments)
        
        tab_layout.addLayout(selectors_layout)
        
        # 2. Main Splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left pane: Chinese & Spanish texts
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        left_layout.addWidget(QLabel("中文原文 (Chinese Source):"))
        self.txt_chinese = QTextEdit()
        left_layout.addWidget(self.txt_chinese)
        
        left_layout.addWidget(QLabel("西班牙语原文 (Spanish Source):"))
        self.txt_spanish = QTextEdit()
        left_layout.addWidget(self.txt_spanish)
        
        self.btn_segment = QPushButton("✨ 自动清洗并智能切分西文")
        self.btn_segment.clicked.connect(self.run_segmentation)
        left_layout.addWidget(self.btn_segment)
        
        left_widget.setLayout(left_layout)
        splitter.addWidget(left_widget)
        
        # Right pane: Segment Table
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        
        # Header Layout with Title and Search Input
        table_header_layout = QHBoxLayout()
        lbl_table_title = QLabel("切分段落与提示词工作台 (Segments & Prompts):")
        table_header_layout.addWidget(lbl_table_title)
        table_header_layout.addStretch()
        
        self.txt_search = QLineEdit()
        self.txt_search.setObjectName("txt_search")
        self.txt_search.setPlaceholderText("🔍 搜索本项目文案或提示词...")
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.setFixedWidth(240)
        self.txt_search.setStyleSheet("""
            QLineEdit#txt_search {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 3px 8px;
                font-size: 12px;
                color: #5D4037;
            }
            QLineEdit#txt_search:focus {
                border: 1px solid #E0A96D;
            }
        """)
        self.txt_search.textChanged.connect(self.filter_segments_table)
        table_header_layout.addWidget(self.txt_search)
        
        right_layout.addLayout(table_header_layout)
        
        # Inner splitter for Table and Property Panel
        self.table_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        self.table_segments = QTableWidget()
        self.table_segments.setColumnCount(6)
        self.table_segments.setHorizontalHeaderLabels([
            "序号", "分句文案 (双击可修改)", "字数", "时长 (秒)", "生成的提示词 (双击可复制)", "操作"
        ])
        self.table_segments.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # 支持按住 Ctrl / Shift 多选分句，配合「🧩 批量设置」一次性修改多条
        self.table_segments.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table_segments.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_segments.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.table_segments.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table_segments.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        self.table_segments.cellChanged.connect(self.on_cell_changed)
        self.table_segments.cellDoubleClicked.connect(self.on_cell_double_clicked)
        self.table_segments.currentItemChanged.connect(self.on_table_selection_changed)
        # 「操作」列改为绘制按钮（不再每行创建 QPushButton 控件），大幅降低表格刷新开销
        from views.table_delegates import TableButtonDelegate
        self._copy_btn_delegate = TableButtonDelegate(["🤖 复制提示词"], self.table_segments,
                                                      colors=["#E0A96D"], hover_colors=["#D2904C"])
        self._copy_btn_delegate.clicked.connect(lambda row, _i: self.copy_segment_prompt(row))
        self.table_segments.setItemDelegateForColumn(5, self._copy_btn_delegate)
        self.table_segments.setMouseTracking(True)
        self.table_segments.setColumnWidth(5, 110)
        
        self.table_splitter.addWidget(self.table_segments)
        
        # Property Panel Scroll Area
        self.property_scroll = QScrollArea()
        self.property_scroll.setWidgetResizable(True)
        self.property_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.property_scroll.setStyleSheet("QScrollArea { border: none; background-color: #FAF6F0; }")
        
        self.property_panel = QWidget()
        self.init_property_panel()
        self.property_scroll.setWidget(self.property_panel)
        self.table_splitter.addWidget(self.property_scroll)
        
        # Set default proportions
        self.table_splitter.setSizes([640, 260])
        from PyQt6.QtWidgets import QSizePolicy
        self.table_splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        right_layout.addWidget(self.table_splitter, 1)
        
        # Table edit buttons
        table_buttons_layout = QHBoxLayout()
        self.btn_add_segment = QPushButton("＋ 添加行")
        self.btn_add_segment.clicked.connect(self.add_segment_row)
        table_buttons_layout.addWidget(self.btn_add_segment)
        
        self.btn_delete_segment = QPushButton("－ 删除选中行")
        self.btn_delete_segment.setObjectName("btn_delete_segment")
        self.btn_delete_segment.clicked.connect(self.delete_selected_segment)
        table_buttons_layout.addWidget(self.btn_delete_segment)

        self.btn_bulk_edit = QPushButton("🖼️ 批量选择预设")
        self.btn_bulk_edit.setToolTip(
            "打开全新的多选与图片预设可视化管理大窗：\n"
            "• 一目了然展示所有断句图片（支持 Ctrl+鼠标滚轮无级缩放）\n"
            "• 支持 Ctrl / Shift / 鼠标直接框选多个图片，在上方选项卡直接指定各种预设\n"
            "• 自带可折叠/展开的「任务资源图库」，多选断句后点击资源图即可批量更换\n"
            "• 支持在窗口内直接切换任务"
        )
        self.btn_bulk_edit.setStyleSheet("background-color: #10B981; color: white; font-weight: bold;")
        self.btn_bulk_edit.clicked.connect(self.open_bulk_edit_dialog)
        table_buttons_layout.addWidget(self.btn_bulk_edit)

        self.btn_copy_table = QPushButton("📊 复制为表格")
        self.btn_copy_table.setToolTip("把当前项目所有分句按「序号 / 文案 / 字数 / 时长 / 提示词」5 列复制到剪贴板，\n可直接粘贴到 Excel / WPS / 飞书 / 谷歌表格中")
        self.btn_copy_table.setStyleSheet("background-color: #0F766E; color: white; font-weight: bold;")
        self.btn_copy_table.clicked.connect(self.copy_segments_as_table)
        table_buttons_layout.addWidget(self.btn_copy_table)
        
        table_buttons_layout.addStretch()
        
        self.btn_export_batch = QPushButton("📋 导出批量生成 JSON")
        self.btn_export_batch.setStyleSheet("background-color: #8B5CF6; color: white; font-weight: bold;")
        self.btn_export_batch.clicked.connect(self.export_batch_json)
        table_buttons_layout.addWidget(self.btn_export_batch)
        
        self.btn_import_report = QPushButton("📥 导入报告并归位视频")
        self.btn_import_report.setStyleSheet("background-color: #10B981; color: white; font-weight: bold;")
        self.btn_import_report.clicked.connect(self.import_execution_report)
        table_buttons_layout.addWidget(self.btn_import_report)
        
        self.btn_save_project = QPushButton("💾 保存修改")
        self.btn_save_project.clicked.connect(self.save_project_data)
        table_buttons_layout.addWidget(self.btn_save_project)
        
        right_layout.addLayout(table_buttons_layout)
        right_widget.setLayout(right_layout)
        splitter.addWidget(right_widget)
        
        # Collapse the left widget (Chinese & Spanish text inputs) by default.
        splitter.setSizes([0, 900])
        tab_layout.addWidget(splitter, stretch=1)
        
        tab_widget.setLayout(tab_layout)
        self.tabs.addTab(tab_widget, "📝 文案、切分与提示词")

    def reset_to_no_selection(self):
        """Resets the detail widget to the 'No Selection' state."""
        self.cleanup()
        self.project_path = None
        self.project_model = None
        self.content_widget.setVisible(False)
        self.no_selection_widget.setVisible(True)
        # Also clear the compare widget
        if hasattr(self, 'video_compare_widget'):
            self.video_compare_widget.set_project(None, None)

    def init_compare_tab(self):
        """Initializes the video vs script comparison tab (Tab 3)."""
        from views.video_compare_widget import VideoCompareWidget
        self.video_compare_widget = VideoCompareWidget()
        self.video_compare_widget.videos_deleted.connect(self.populate_segments_table)
        if hasattr(self.video_compare_widget, "send_to_batch_reels"):
            self.video_compare_widget.send_to_batch_reels.connect(self._on_send_to_batch_reels)
        self.tabs.addTab(self.video_compare_widget, "🎬 视频与文案比对")

    def jump_to_visual_review(self):
        """Switches to the top-level Visual Review tab and selects the current project."""
        if not self.project_path:
            return
        main_win = self.window()
        if hasattr(main_win, "open_in_visual_review"):
            main_win.open_in_visual_review(self.project_path)

    def _on_send_to_batch_reels(self, payload: dict):
        """Forwards merged video + SRT + word timings to the top-level Batch Reels tab."""
        main_win = self.window()
        if hasattr(main_win, "open_in_batch_reels"):
            main_win.open_in_batch_reels(payload)

    def set_project(self, project_path, light=False):
        """Loads and binds project data.
        light=True：仅加载拆批所需的数据（全局托管批量拆批时使用），跳过素材列表与视频比对页刷新，避免卡顿。"""
        self.project_path = Path(project_path)
        self.project_model = ProjectModel(self.project_path)
        self.copied_rows = set()
        self.dispatched_indices = set()
        self.failed_skip_indices = set()
        self.segment_retry_counts = {}
        
        # Switch visible UI
        self.no_selection_widget.setVisible(False)
        self.content_widget.setVisible(True)
        
        # Update labels and fields
        self.lbl_proj_title.setText(f"项目名称: {self.project_model.project_id} (序号: {self.project_model.index:02d})")
        self.txt_chinese.setPlainText(self.project_model.chinese_text)
        self.txt_spanish.setPlainText(self.project_model.spanish_text)
        self.txt_gdrive_url.setPlainText(self.project_model.google_drive_url)
        
        # Load end frame setting (project override or global default)
        if self.project_model.enable_end_frame is not None:
            self.enable_end_frame = bool(self.project_model.enable_end_frame)
        else:
            self.enable_end_frame = bool(getattr(self.config_manager, "enable_end_frame", False)) if self.config_manager else False

        if hasattr(self, "chk_enable_end_frame"):
            self.chk_enable_end_frame.blockSignals(True)
            self.chk_enable_end_frame.setChecked(self.enable_end_frame)
            self.chk_enable_end_frame.blockSignals(False)
        if hasattr(self, "container_end_image"):
            self.container_end_image.setVisible(self.enable_end_frame)

        # Populate table segments（refresh_template_comboboxes 内部会再刷新一次表格，因此这里只在没有模板管理器时刷新，避免重复整表重建）
        if not self.template_manager:
            self.populate_segments_table()
        
        # Refresh media list
        if not light:
            self.refresh_media_list()
        
        # Refresh templates dropdowns & prompts table
        self.refresh_template_comboboxes()
        
        if light:
            self._compare_dirty = True
            return
        
        # Check if this project has an active background download running in MainWindow
        main_win = self.window()
        if hasattr(main_win, "active_downloads") and self.project_model.project_id in main_win.active_downloads:
            self.lbl_download_status.setText("下载状态: 正在后台自动下载中...")
            self.btn_download.setEnabled(False)
        else:
            self.lbl_download_status.setText("下载状态: 未开始")
            self.btn_download.setEnabled(True)
        
        # Refresh the video compare tab
        if hasattr(self, 'video_compare_widget'):
            # 视频比对页需要读取视频文件信息，比较耗时：只有当前正在看该页时才立即刷新，否则切过去时再加载
            if self.tabs.currentWidget() is self.video_compare_widget:
                self._compare_dirty = False
                self.video_compare_widget.set_project(self.project_model, self.project_path, self.config_manager)
            else:
                self._compare_dirty = True
