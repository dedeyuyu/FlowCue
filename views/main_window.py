# -*- coding: utf-8 -*-
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QLineEdit, QPushButton, QListWidget, 
                             QListWidgetItem, QSplitter, QFileDialog, QMessageBox,
                             QInputDialog, QMenu, QToolTip, QDialog, QSpinBox,
                             QProgressBar, QFrame)
from PyQt6.QtCore import Qt, QSize, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QCursor, QColor
from models.storage_manager import StorageManager
from views.import_dialog import ImportDialog
from views.project_detail_widget import ProjectDetailWidget
from pathlib import Path

class _StatusThread(QThread):
    status_signal = pyqtSignal(int, str, dict)

    def __init__(self, gen, items, base, parent=None):
        super().__init__(parent)
        self.gen, self.items, self.base = gen, list(items), base

    def run(self):
        from models.project_model import ProjectModel
        from services.video_checker import VideoChecker
        for path in self.items:
            if self.isInterruptionRequested():
                return
            try:
                report = VideoChecker.check_project_videos(ProjectModel(path), path, base_storage_path=self.base)
                self.status_signal.emit(self.gen, str(path), {
                    "missing": report.get("missing_count", 0), "pending": report.get("pending_count", 0),
                    "already": report.get("already_count", 0), "rate": report.get("completion_rate", 0.0)})
            except Exception as e:
                print(f"Error checking project status for {path}: {e}")


class RenameProjectDialog(QDialog):
    """Dialog for modifying all parts of a project (Index, Project Name, and Notes)."""
    
    def __init__(self, index, col1_name, col7_notes, parent=None):
        super().__init__(parent)
        self.setWindowTitle("✏️ 重命名项目 (Rename Project)")
        self.resize(420, 260)
        self.index_val = index
        self.col1_val = col1_name
        self.col7_val = col7_notes
        self.init_ui()
        
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
            QLineEdit, QSpinBox {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 13px;
                color: #5D4037;
            }
            QLineEdit:focus, QSpinBox:focus {
                border: 1px solid #E0A96D;
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
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        
        # Index field
        idx_layout = QHBoxLayout()
        idx_layout.addWidget(QLabel("项目序号 (Index):"))
        self.spin_index = QSpinBox()
        self.spin_index.setRange(1, 9999)
        self.spin_index.setValue(int(self.index_val) if self.index_val else 1)
        idx_layout.addWidget(self.spin_index, stretch=1)
        layout.addLayout(idx_layout)
        
        # Name field
        layout.addWidget(QLabel("项目名称 (Project Name):"))
        self.txt_name = QLineEdit()
        self.txt_name.setText(self.col1_val)
        layout.addWidget(self.txt_name)
        
        # Notes field
        layout.addWidget(QLabel("项目备注/后缀 (Notes):"))
        self.txt_notes = QLineEdit()
        self.txt_notes.setText(self.col7_val)
        layout.addWidget(self.txt_notes)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        
        btn_save = QPushButton("💾 确认修改")
        btn_save.setStyleSheet("background-color: #10B981; color: white; font-weight: bold;")
        btn_save.clicked.connect(self.accept)
        btn_layout.addWidget(btn_save)
        
        layout.addLayout(btn_layout)

    def get_values(self):
        return self.spin_index.value(), self.txt_name.text().strip(), self.txt_notes.text().strip()

class MainWindow(QMainWindow):
    """Main window of the Project Manager application."""
    
    def __init__(self, workspace_dir):
        super().__init__()
        self.workspace_dir = Path(workspace_dir)
        self.storage_manager = StorageManager(self.workspace_dir)
        self.active_downloads = {}
        
        # Initialize TemplateManager & ConfigManager
        from models.template_manager import TemplateManager
        from models.config_manager import ConfigManager
        from services.plugin_server import PluginServer
        self.template_manager = TemplateManager(self.workspace_dir)
        self.config_manager = ConfigManager(self.workspace_dir)
        
        # Initialize PluginServer
        # 默认不启动：只有在「全局托管」页点击「🔌 开始识别浏览器」或「🔄 刷新积分」时才开启监听。
        # 未开启时浏览器插件处于休眠状态，手动模式（复制 JSON + 闪电一键）完全不受影响。
        self.plugin_server = PluginServer(port=self.config_manager.plugin_server_port, parent=self)
        
        self.init_ui()
        # Bind template, config manager & plugin server to detail panel
        self.detail_widget.set_template_manager(self.template_manager)
        self.detail_widget.set_config_manager(self.config_manager)
        self.detail_widget.set_plugin_server(self.plugin_server)
        
        self.plugin_server.client_connected_signal.connect(self.update_plugin_status_ui)
        self.plugin_server.client_disconnected_signal.connect(self.update_plugin_status_ui)
        self.plugin_server.client_updated_signal.connect(self.update_plugin_status_ui)
        self.plugin_server.alarm_detected_signal.connect(self.on_plugin_alarm_detected)
        self.update_plugin_status_ui()

        self.load_initial_state()

    def init_ui(self):
        from version import __version__
        self.setWindowTitle(f"FlowCue v{__version__}")
        self.resize(1200, 800)
        self.setMinimumSize(1000, 600)
        
        # Warm and premium style theme
        self.setStyleSheet("""
            QMainWindow {
                background-color: #F5EBE6;
                font-family: "Segoe UI", "PingFang SC", sans-serif;
            }
            QWidget#central_widget {
                background-color: #F5EBE6;
            }
            QLabel {
                font-size: 13px;
                color: #5D4037;
                font-weight: bold;
            }
            QLineEdit {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 6px;
                color: #5D4037;
                font-size: 13px;
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
            QPushButton#btn_import {
                background-color: #E0A96D;
                font-size: 14px;
                padding: 8px 18px;
            }
            QPushButton#btn_import:hover {
                background-color: #D2904C;
            }
            QPushButton#btn_template_config {
                background-color: #D7CCC8;
                color: #5D4037;
                font-size: 13px;
                padding: 6px 14px;
            }
            QPushButton#btn_template_config:hover {
                background-color: #BCAAA4;
            }
            QListWidget {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                color: #5D4037;
                font-size: 13px;
                padding: 4px;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #EFEBE9;
                border-radius: 4px;
            }
            QListWidget::item:hover {
                background-color: #F5F5F5;
                color: #5D4037;
            }
            QListWidget::item:selected {
                background-color: #FFE0B2;
                color: #5D4037;
                font-weight: bold;
            }
        """)

        central_widget = QWidget()
        central_widget.setObjectName("central_widget")
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)
        
        # 1. Top Bar (分成上下两行：第一行主配置与导入，第二行项目与批量快捷工作流)
        top_container_layout = QVBoxLayout()
        top_container_layout.setContentsMargins(0, 0, 0, 0)
        top_container_layout.setSpacing(8)

        # ── 第一行：存储路径 + 选择路径(蓝) + 新建导入(蓝) + 描述词预设(黄) + 规则设置(黄) + 检查更新(小字原色) + 亮/暗模式(小字原色) ──
        top_row1 = QHBoxLayout()
        top_row1.setSpacing(8)

        row1_blue_qss = """
            QPushButton {
                background-color: #2563EB;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 6px 14px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1D4ED8;
            }
            QPushButton:pressed {
                background-color: #1E40AF;
            }
        """
        row1_yellow_qss = """
            QPushButton {
                background-color: #E0A96D;
                color: white;
                border: none;
                border-radius: 5px;
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
        """

        top_row1.addWidget(QLabel("存储路径 (Storage Path):"))

        self.txt_base_path = QLineEdit()
        self.txt_base_path.setReadOnly(True)
        self.txt_base_path.setPlaceholderText("请选择项目数据存放的总目录...")
        top_row1.addWidget(self.txt_base_path, stretch=1)

        self.btn_select_path = QPushButton("选择路径")
        self.btn_select_path.setStyleSheet(row1_blue_qss)
        self.btn_select_path.clicked.connect(self.select_base_path)
        top_row1.addWidget(self.btn_select_path)

        self.btn_import = QPushButton("＋ 新建导入 (Import)")
        self.btn_import.setObjectName("btn_import")
        self.btn_import.setStyleSheet(row1_blue_qss)
        self.btn_import.clicked.connect(self.open_import_dialog)
        top_row1.addWidget(self.btn_import)

        self.btn_template_config = QPushButton("⚙️ 描述词预设")
        self.btn_template_config.setObjectName("btn_template_config")
        self.btn_template_config.setStyleSheet(row1_yellow_qss)
        self.btn_template_config.setToolTip("配置提示词模板与运镜预设")
        self.btn_template_config.clicked.connect(self.open_template_config_dialog)
        top_row1.addWidget(self.btn_template_config)

        self.btn_rules_config = QPushButton("⚙️ 规则设置")
        self.btn_rules_config.setObjectName("btn_rules_config")
        self.btn_rules_config.setStyleSheet(row1_yellow_qss)
        self.btn_rules_config.setToolTip("配置全局生成规则、API Key 与系统参数")
        self.btn_rules_config.clicked.connect(self.open_settings_dialog)
        top_row1.addWidget(self.btn_rules_config)

        top_row1.addSpacing(8)

        self.btn_check_update = QPushButton("⬆️ 检查更新")
        self.btn_check_update.setStyleSheet("""
            QPushButton { background-color: #2563EB; color: white; font-size: 12px;
                          font-weight: bold; padding: 5px 11px; border-radius: 5px; }
            QPushButton:hover { background-color: #1D4ED8; }
        """)
        self.btn_check_update.setToolTip("检查 GitHub 上是否有新版本，并可一键下载安装")
        self.btn_check_update.clicked.connect(self.open_update_dialog)
        top_row1.addWidget(self.btn_check_update)
        QTimer.singleShot(6000, self._silent_update_check)

        self.btn_theme_toggle = QPushButton("🌙 暗色模式")
        self.btn_theme_toggle.setObjectName("btn_theme_toggle")
        self.btn_theme_toggle.setToolTip("一键切换【☀️ 亮色模式】与【🌙 暗色模式】")
        self.btn_theme_toggle.clicked.connect(self.toggle_theme_mode)
        top_row1.addWidget(self.btn_theme_toggle)
        self._update_theme_toggle_btn()

        top_container_layout.addLayout(top_row1)

        # ── 第二行：归位 + 核对文案 + 批量拼接 + 批量选择预设 + 快速审核 (统一绿色，字号稍小) + 打开文件夹 (保留原色) ──
        top_row2 = QHBoxLayout()
        top_row2.setSpacing(8)

        row2_green_qss = """
            QPushButton {
                background-color: #10B981;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 5px 13px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
            }
            QPushButton:pressed {
                background-color: #047857;
            }
        """

        self.btn_batch_check_video = QPushButton("🔍 归位")
        self.btn_batch_check_video.setObjectName("btn_batch_check_video")
        self.btn_batch_check_video.setStyleSheet(row2_green_qss)
        self.btn_batch_check_video.setToolTip("全项目视频完整性核查与一键批量归位")
        self.btn_batch_check_video.clicked.connect(self.open_batch_video_check_dialog)
        top_row2.addWidget(self.btn_batch_check_video)

        self.btn_batch_verify_all = QPushButton("📚 核对文案")
        self.btn_batch_verify_all.setObjectName("btn_batch_verify_all")
        self.btn_batch_verify_all.setStyleSheet(row2_green_qss)
        self.btn_batch_verify_all.setToolTip("批量并列核对所有任务的文案与自动气口剪切（最大支持 4 任务并发）")
        self.btn_batch_verify_all.clicked.connect(self.open_batch_verify_all_dialog)
        top_row2.addWidget(self.btn_batch_verify_all)

        self.btn_batch_splice_all = QPushButton("🎬 批量拼接")
        self.btn_batch_splice_all.setObjectName("btn_batch_splice_all")
        self.btn_batch_splice_all.setStyleSheet(row2_green_qss)
        self.btn_batch_splice_all.setToolTip("勾选多个或全部任务，逐个完成合并拼接成片 (+SRT) 并全部送入【🎬 批量Reels】")
        self.btn_batch_splice_all.clicked.connect(self.open_batch_splice_all_dialog)
        top_row2.addWidget(self.btn_batch_splice_all)

        self.btn_top_multi_select = QPushButton("🖼️ 批量选择预设")
        self.btn_top_multi_select.setObjectName("btn_top_multi_select")
        self.btn_top_multi_select.setStyleSheet(row2_green_qss)
        self.btn_top_multi_select.setToolTip(
            "打开多选与图片预设可视化管理大窗：\n"
            "• 一目了然展示所有断句图片（支持 Ctrl+鼠标滚轮无级缩放）\n"
            "• 支持 Ctrl / Shift / 鼠标直接框选多个图片，在上方选项卡直接指定各种预设\n"
            "• 自带可折叠/展开的「任务资源图库」，多选断句后点击资源图即可批量更换\n"
            "• 支持在窗口内直接切换任务"
        )
        self.btn_top_multi_select.clicked.connect(self.open_current_project_bulk_edit)
        top_row2.addWidget(self.btn_top_multi_select)

        self.btn_top_quick_review = QPushButton("👁️ 快速审核")
        self.btn_top_quick_review.setObjectName("btn_top_quick_review")
        self.btn_top_quick_review.setStyleSheet(row2_green_qss)
        self.btn_top_quick_review.setToolTip("跳转到「👁️ 素材快速审核」标签页并直接加载当前项目的全部视频与图片素材")
        self.btn_top_quick_review.clicked.connect(self.open_current_project_quick_review)
        top_row2.addWidget(self.btn_top_quick_review)

        self.btn_top_open_folder = QPushButton("📂 打开文件夹")
        self.btn_top_open_folder.setObjectName("btn_top_open_folder")
        self.btn_top_open_folder.setStyleSheet("""
            QPushButton#btn_top_open_folder {
                background-color: #D7CCC8;
                color: #5D4037;
                border: none;
                border-radius: 5px;
                padding: 5px 13px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton#btn_top_open_folder:hover {
                background-color: #BCAAA4;
            }
        """)
        self.btn_top_open_folder.setToolTip("在系统资源管理器中打开当前项目的文件夹")
        self.btn_top_open_folder.clicked.connect(self.open_current_project_folder)
        top_row2.addWidget(self.btn_top_open_folder)

        top_row2.addStretch()

        top_container_layout.addLayout(top_row2)
        main_layout.addLayout(top_container_layout)
        
        # 2. Main Area (Splitter: Sidebar and Details)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left Panel (Sidebar Container)
        sidebar_widget = QWidget()
        sidebar_layout = QVBoxLayout(sidebar_widget)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(6)
        
        # Pipeline Header & Actions Box (带实时生成监控看板)
        pipeline_box = QFrame()
        pipeline_box.setStyleSheet("background-color: #EDE0D4; border-radius: 6px; padding: 6px;")
        p_box_layout = QVBoxLayout(pipeline_box)
        p_box_layout.setContentsMargins(6, 6, 6, 6)
        p_box_layout.setSpacing(6)

        hdr_row = QHBoxLayout()
        hdr_row.addWidget(QLabel("<b>项目列表 (Projects)</b>"))
        hdr_row.addStretch()
        
        self.btn_select_all_proj = QPushButton("☑️ 全选")
        self.btn_select_all_proj.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.btn_select_all_proj.clicked.connect(self.select_all_projects_for_pipeline)
        hdr_row.addWidget(self.btn_select_all_proj)

        self.btn_clear_all_proj = QPushButton("⏹️ 清空")
        self.btn_clear_all_proj.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.btn_clear_all_proj.clicked.connect(self.deselect_all_projects_for_pipeline)
        hdr_row.addWidget(self.btn_clear_all_proj)
        p_box_layout.addLayout(hdr_row)

        sidebar_layout.addWidget(pipeline_box)

        self.list_projects = QListWidget()
        self.list_projects.itemClicked.connect(self.on_project_clicked)
        self.list_projects.itemDoubleClicked.connect(self.on_project_double_clicked)
        self.list_projects.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_projects.customContextMenuRequested.connect(self.show_project_context_menu)
        sidebar_layout.addWidget(self.list_projects)
        
        # Add delete button under the list
        self.btn_delete_project = QPushButton("🗑️ 删除选中项目")
        self.btn_delete_project.setObjectName("btn_delete_project")
        self.btn_delete_project.setStyleSheet("""
            QPushButton#btn_delete_project {
                background-color: #E57373;
                color: white;
            }
            QPushButton#btn_delete_project:hover {
                background-color: #EF5350;
            }
            QPushButton#btn_delete_project:pressed {
                background-color: #E53935;
            }
        """)
        self.btn_delete_project.clicked.connect(self.delete_selected_project)
        sidebar_layout.addWidget(self.btn_delete_project)
        
        sidebar_widget.setLayout(sidebar_layout)
        splitter.addWidget(sidebar_widget)
        
        # Right Panel (Detail Widget)
        self.detail_widget = ProjectDetailWidget()
        splitter.addWidget(self.detail_widget)
        
        # Set splitter proportions (approx 25% sidebar, 75% details)
        splitter.setSizes([300, 900])

        from PyQt6.QtWidgets import QTabWidget
        self.main_tab_widget = QTabWidget()
        self.main_tab_widget.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #D7CCC8; border-radius: 4px; background-color: #F5EBE6; }
            QTabBar::tab {
                background-color: #EDE0D4; color: #5D4037; font-size: 13px; font-weight: bold;
                padding: 8px 20px; border: 1px solid #D7CCC8; border-bottom: none;
                border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px;
            }
            QTabBar::tab:selected { background-color: #F5EBE6; border-bottom: 2px solid #E0A96D; }
            QTabBar::tab:hover { background-color: #FFE0B2; }
        """)
        self.main_tab_widget.addTab(splitter, "📋 项目管理")

        from views.batch_generate_tab import BatchGenerateTabWidget
        self.batch_generate_tab = BatchGenerateTabWidget(self.plugin_server, self)
        self.main_tab_widget.addTab(self.batch_generate_tab, "🚀 批量生成")

        from views.hosted_mode_widget import HostedModeWidget
        self.hosted_mode = HostedModeWidget(self.plugin_server, self)
        self.main_tab_widget.addTab(self.hosted_mode, "🤖 全局托管")

        from views.visual_review_tab import VisualReviewTabWidget
        self.visual_review_tab = VisualReviewTabWidget(self.storage_manager, self.config_manager, self)
        self.visual_review_tab.project_review_updated.connect(self._on_visual_review_updated)
        self.main_tab_widget.addTab(self.visual_review_tab, "👁️ 素材快速审核")

        from views.batch_reels_tab import BatchReelsTabWidget
        self.batch_reels_tab = BatchReelsTabWidget(self.storage_manager, self.config_manager, self)
        self.main_tab_widget.addTab(self.batch_reels_tab, "🎬 批量Reels")

        self.main_tab_widget.currentChanged.connect(self._on_main_tab_changed)
        self.account_monitor = None
        main_layout.addWidget(self.main_tab_widget, stretch=1)

    def load_initial_state(self):
        """Displays saved base path if it exists and loads projects list."""
        base_path = self.storage_manager.get_base_path()
        if base_path:
            self.txt_base_path.setText(str(base_path))
            self.reload_projects_list()
        else:
            self.txt_base_path.setText("")
            QMessageBox.information(self, "欢迎", "首次使用，请先点击 ［选择路径］ 设置数据存放的总目录！")

    def select_base_path(self):
        """Opens a folder selection dialog to set the base path."""
        dir_path = QFileDialog.getExistingDirectory(self, "选择总存储路径", str(self.workspace_dir))
        if dir_path:
            if self.storage_manager.set_base_path(dir_path):
                self.txt_base_path.setText(dir_path)
                self.reload_projects_list()
                QMessageBox.information(self, "成功", "总存储路径设置成功！")
            else:
                QMessageBox.critical(self, "错误", "无法使用该存储路径，请检查权限。")

    def reload_projects_list(self):
        """Fetches current projects and populates sidebar list widget with video completeness status colors."""
        self.list_projects.clear()
        
        projects = self.storage_manager.list_projects()
        base_path = self.storage_manager.get_base_path()
        from models.project_model import ProjectModel
        from services.video_checker import VideoChecker
        from services.theme_manager import ThemeManager
        default_fg = ThemeManager.get_default_item_fg()
        is_dark = ThemeManager.is_dark()
        
        for p in projects:
            # Format list item label: {index} {col1} - {col7}
            label = f"●  {p['index_str']}   {p['col1']}"
            if p['col7']:
                label += f" - {p['col7']}"
                
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, p['path'])
            item.setData(Qt.ItemDataRole.UserRole + 1, p)
            item.setForeground(default_fg)
            self.list_projects.addItem(item)

        # 视频完整度（红 / 黄 / 默认色）需要扫描磁盘上的视频文件夹，项目多时很慢：
        # 改为后台线程逐个计算，算好一个就给对应项目上色，列表本身立即显示、界面不卡。
        self._start_project_status_scan(projects, base_path)

    def _start_project_status_scan(self, projects, base_path):
        self._status_gen = getattr(self, "_status_gen", 0) + 1
        old = getattr(self, "_status_thread", None)
        if old is not None:
            try:
                if old.isRunning():
                    old.requestInterruption()
            except RuntimeError:
                pass
            self._status_thread = None
        th = _StatusThread(self._status_gen, [p['path'] for p in projects], base_path, self)
        th.status_signal.connect(self._apply_project_status)

        def _on_status_done(t=th):
            if getattr(self, "_status_thread", None) is t:
                self._status_thread = None
            try:
                t.deleteLater()
            except RuntimeError:
                pass

        th.finished.connect(_on_status_done)
        self._status_thread = th
        th.start()

    def _apply_project_status(self, gen, path, st):
        if gen != getattr(self, "_status_gen", 0):
            return
        from services.theme_manager import ThemeManager
        default_fg = ThemeManager.get_default_item_fg()
        is_dark = ThemeManager.is_dark()
        for i in range(self.list_projects.count()):
            item = self.list_projects.item(i)
            if str(item.data(Qt.ItemDataRole.UserRole)) != path:
                continue
            missing, pending, already, rate = st["missing"], st["pending"], st["already"], st["rate"]
            # 规则：
            # 1. 缺少视频就显示红色
            # 2. 成功归位并且没有缺少视频就显示黄色
            # 3. 没有归位就显示默认颜色
            if missing > 0:
                item.setForeground(QColor("#F87171" if is_dark else "#DC2626"))  # 红色
                item.setToolTip(f"❌ 缺失 {missing} 个视频片段")
            elif rate >= 100.0 and pending == 0 and already > 0:
                item.setForeground(QColor("#FBBF24" if is_dark else "#D97706"))  # 黄色
                item.setToolTip("✅ 视频已全部归位且无缺失")
            elif pending > 0:
                item.setForeground(default_fg)  # 默认色
                item.setToolTip(f"⚠️ 包含 {pending} 个未归位视频")
            else:
                item.setForeground(default_fg)  # 默认色
            break

    def _update_theme_toggle_btn(self):
        """Updates the top bar theme toggle button appearance."""
        if not hasattr(self, "btn_theme_toggle"):
            return
        from services.theme_manager import ThemeManager
        if ThemeManager.is_dark():
            self.btn_theme_toggle.setText("☀️ 亮色模式")
            self.btn_theme_toggle.setStyleSheet("""
                QPushButton#btn_theme_toggle {
                    background-color: #F59E0B;
                    color: #18181B;
                    font-size: 12px;
                    font-weight: bold;
                    padding: 4px 10px;
                    border-radius: 4px;
                }
                QPushButton#btn_theme_toggle:hover {
                    background-color: #D97706;
                    color: white;
                }
            """)
        else:
            self.btn_theme_toggle.setText("🌙 暗色模式")
            self.btn_theme_toggle.setStyleSheet("""
                QPushButton#btn_theme_toggle {
                    background-color: #334155;
                    color: white;
                    font-size: 12px;
                    font-weight: bold;
                    padding: 4px 10px;
                    border-radius: 4px;
                }
                QPushButton#btn_theme_toggle:hover {
                    background-color: #1E293B;
                }
            """)

    def toggle_theme_mode(self):
        """Toggles between Light Mode and Dark Mode and persists the setting."""
        from services.theme_manager import ThemeManager
        new_mode = ThemeManager.LIGHT if ThemeManager.is_dark() else ThemeManager.DARK
        self.apply_theme_mode(new_mode, save_config=True)

    def apply_theme_mode(self, mode: str, save_config: bool = False):
        """Applies the given theme mode across the entire application and refreshes item colors."""
        from services.theme_manager import ThemeManager
        mode = ThemeManager.DARK if str(mode).lower() == ThemeManager.DARK else ThemeManager.LIGHT
        if self.config_manager:
            self.config_manager.theme_mode = mode
            if save_config:
                self.config_manager.save()
        ThemeManager.apply_theme(mode)
        self._update_theme_toggle_btn()

        # Refresh project list item colors while preserving current selection
        cur_row = self.list_projects.currentRow()
        if self.storage_manager.get_base_path():
            self.reload_projects_list()
            if 0 <= cur_row < self.list_projects.count():
                self.list_projects.setCurrentRow(cur_row)

        # Refresh table row colors in ProjectDetailWidget and BatchGenerateTabWidget
        if hasattr(self, "detail_widget") and self.detail_widget and self.detail_widget.project_model:
            for r in list(getattr(self.detail_widget, "copied_rows", [])):
                self.detail_widget.change_row_color(r, copied=True)
        if hasattr(self, "batch_generate_tab") and self.batch_generate_tab and self.batch_generate_tab.current_project:
            for r in list(getattr(self.batch_generate_tab, "copied_rows", [])):
                self.batch_generate_tab.change_row_color(r, copied=True)

    def open_import_dialog(self):
        """Opens the clipboard import dialog."""
        if not self.storage_manager.get_base_path():
            QMessageBox.warning(self, "错误", "请先设置总存储路径后再导入项目！")
            return
            
        dialog = ImportDialog(self.storage_manager, self)
        if dialog.exec() == ImportDialog.DialogCode.Accepted:
            self.reload_projects_list()

    def open_settings_dialog(self):
        """Opens rules & points settings dialog."""
        from views.settings_dialog import SettingsDialog
        dialog = SettingsDialog(self.config_manager, self)
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            self.apply_theme_mode(getattr(self.config_manager, "theme_mode", "light"), save_config=False)
            if hasattr(self, "detail_widget"):
                self.detail_widget.set_config_manager(self.config_manager)
                self.detail_widget.populate_segments_table()

    def on_project_clicked(self, item):
        """Triggers detail load when sidebar item is clicked."""
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.detail_widget.set_project(path)

    def on_project_double_clicked(self, item):
        """Copies the entire full project name (including index prefix and notes) to clipboard."""
        if not item:
            return
            
        import re
        full_name = item.text().replace("●", "").strip()
        full_name = re.sub(r' +', ' ', full_name)
        
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(full_name)
        QToolTip.showText(QCursor.pos(), f"已复制完整项目名称:\n{full_name}", self)

    def show_project_context_menu(self, pos):
        """Displays context menu for renaming, copying full name, or deleting project."""
        item = self.list_projects.itemAt(pos)
        if not item:
            return
            
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px 6px 10px;
                font-size: 13px;
                color: #5D4037;
            }
            QMenu::item:selected {
                background-color: #FFE0B2;
                border-radius: 3px;
            }
        """)
        
        act_rename = menu.addAction("✏️ 重命名项目 (Rename)")
        act_copy_name = menu.addAction("📋 复制完整项目名称 (Copy Full Name)")
        menu.addSeparator()
        act_delete = menu.addAction("🗑️ 删除项目 (Delete)")
        
        action = menu.exec(self.list_projects.mapToGlobal(pos))
        if action == act_rename:
            self.rename_project(item)
        elif action == act_copy_name:
            self.on_project_double_clicked(item)
        elif action == act_delete:
            self.delete_selected_project()

    def rename_project(self, item):
        """Opens dialog to rename all parts (Index, Name, Notes) of a project and updates storage and metadata."""
        project_path_str = item.data(Qt.ItemDataRole.UserRole)
        if not project_path_str:
            return
            
        path = Path(project_path_str)
        if not path.exists():
            return
            
        from models.project_model import ProjectModel
        try:
            model = ProjectModel(path)
            old_index = model.index
            old_name = model.col1_name
            old_notes = model.col7_notes
        except Exception as e:
            QMessageBox.critical(self, "错误", f"读取项目信息失败: {e}")
            return

        dialog = RenameProjectDialog(old_index, old_name, old_notes, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_index, new_name, new_notes = dialog.get_values()
            
            if not new_name:
                QMessageBox.warning(self, "警告", "项目名称不能为空！")
                return
                
            try:
                # Update model
                model.index = new_index
                model.col1_name = new_name
                model.col7_notes = new_notes
                model.save()
                
                # Format new folder name on disk
                invalid_chars = '<>:"/\\|?*'
                c1 = "".join(c for c in new_name if c not in invalid_chars).strip()[:50]
                c7 = "".join(c for c in new_notes if c not in invalid_chars).strip()[:50]
                
                new_dir_name = f"{new_index:02d}_{c1}_{c7}-flow"
                new_dir_path = path.parent / new_dir_name
                
                target_path = path
                if new_dir_path != path and not new_dir_path.exists():
                    try:
                        path.rename(new_dir_path)
                        target_path = new_dir_path
                        model.project_dir = new_dir_path
                        model.project_id = new_dir_name
                        model.save()
                    except Exception as e:
                        print(f"Directory rename failed, metadata updated: {e}")
                        
                # Reload project list
                self.reload_projects_list()
                
                # If detail_widget is currently displaying this project, update it
                if hasattr(self, "detail_widget"):
                    current_active = self.detail_widget.project_path
                    if current_active and (Path(current_active) == path or Path(current_active) == target_path):
                        self.detail_widget.set_project(target_path)
                        
                QMessageBox.information(self, "成功", "项目基本信息修改成功！")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"修改项目失败: {e}")

    def start_background_download(self, project_id, url, project_dir):
        """Starts an asynchronous background download of Google Drive link for a project."""
        if not url:
            return
            
        if project_id in self.active_downloads:
            return
            
        from services.downloader import DownloadThread
        downloads_dir = Path(project_dir) / "downloads"
        
        thread = DownloadThread(url, downloads_dir)
        self.active_downloads[project_id] = thread
        
        thread.status_signal.connect(
            lambda msg, pid=project_id: self.on_background_download_status(msg, pid)
        )
        thread.finished_signal.connect(
            lambda success, msg, pid=project_id: self.on_background_download_finished(success, msg, pid)
        )
        thread.finished.connect(thread.deleteLater)
        
        thread.start()

    def on_background_download_status(self, msg, project_id):
        """Dispatches status updates to detail widget if showing this project."""
        if self.detail_widget.project_model and self.detail_widget.project_model.project_id == project_id:
            self.detail_widget.on_download_status_updated(msg)

    def on_background_download_finished(self, success, msg, project_id):
        """Cleans up thread and updates project metadata and detail view."""
        self.active_downloads.pop(project_id, None)
        
        # Scan and update metadata files in project directory
        proj_path = self.storage_manager.resolve_path(project_id)
        if proj_path.exists():
            from models.project_model import ProjectModel
            try:
                proj = ProjectModel(proj_path)
                proj.rename_images()
                proj.update_media_files()
            except Exception as e:
                print(f"Error updating project files: {e}")
                
        # Notify detail widget if current project matches
        if self.detail_widget.project_model and self.detail_widget.project_model.project_id == project_id:
            self.detail_widget.on_download_finished(success, msg)

    def open_update_dialog(self):
        from views.update_dialog import UpdateDialog
        dlg = UpdateDialog(self, auto_check=True)
        dlg.exec()

    def _silent_update_check(self):
        """启动后静默检查一次；有新版本时仅把按钮改成醒目提示，不弹窗打扰。"""
        try:
            from services.updater import CheckUpdateThread
            self._silent_check_thread = CheckUpdateThread()

            def _done(res):
                if res.get("has_update"):
                    self.btn_check_update.setText(f"🆕 有新版本 v{res['version']}")
                    self.btn_check_update.setStyleSheet(
                        "QPushButton { background-color: #DC2626; color: white; font-size: 12px;"
                        " font-weight: bold; padding: 4px 10px; border-radius: 4px; }"
                        "QPushButton:hover { background-color: #B91C1C; }")
            self._silent_check_thread.finished_signal.connect(_done)
            self._silent_check_thread.start()
        except Exception:
            pass

    def delete_selected_project(self):
        """Permanently deletes the selected project folder and files."""
        current_item = self.list_projects.currentItem()
        if not current_item:
            QMessageBox.warning(self, "提示", "请先在列表中选择要删除的项目！")
            return
            
        project_path_str = current_item.data(Qt.ItemDataRole.UserRole)
        project_path = Path(project_path_str)
        project_id = project_path.name
        
        # Confirmation Dialog
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要永久删除项目【{project_id}】吗？\n\n这将会永久删除该项目的文件夹及所有已下载的素材资源，此操作无法撤销！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # 1. Stop any active download thread first
            if project_id in self.active_downloads:
                thread = self.active_downloads.pop(project_id)
                try:
                    if thread and thread.isRunning():
                        thread.stop()
                except RuntimeError:
                    pass
            
            # 2. Delete the directory recursively
            import shutil
            try:
                base = self.storage_manager.base_path.resolve() if self.storage_manager.base_path else None
                resolved_target = project_path.resolve()
                if not base or not resolved_target.is_relative_to(base) or resolved_target == base:
                    QMessageBox.critical(self, "错误", "安全拦截：目标路径不在有效工程根目录内，已中止删除！")
                    return

                if resolved_target.exists() and resolved_target.is_dir():
                    shutil.rmtree(resolved_target)
                
                # Delete corresponding subtitle file in "字幕" folder
                subtitles_dir = project_path.parent / "字幕"
                subtitle_file_path = subtitles_dir / f"{project_id}.txt"
                if subtitle_file_path.exists():
                    subtitle_file_path.unlink()
                
                # 3. If the deleted project is currently displayed, reset the detail view
                if self.detail_widget.project_model and self.detail_widget.project_model.project_id == project_id:
                    self.detail_widget.reset_to_no_selection()
                    
                # 4. Reload the sidebar
                self.reload_projects_list()
                QMessageBox.information(self, "成功", f"项目【{project_id}】已成功删除！")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"删除项目文件夹失败: {str(e)}")

    def open_template_config_dialog(self):
        """Opens the templates and motions configuration dialog."""
        from views.template_config_dialog import TemplateConfigDialog
        dialog = TemplateConfigDialog(self.template_manager, self)
        dialog.exec()
        # Refresh project details dropdowns if a project is loaded
        if hasattr(self, "detail_widget") and self.detail_widget.project_model:
            self.detail_widget.refresh_template_comboboxes()
        # Refresh batch generate tab template dropdown as well
        if hasattr(self, "batch_generate_tab"):
            self.batch_generate_tab.refresh_template_list()

    def open_batch_video_check_dialog(self):
        """Opens batch video completeness dialog for all projects in storage_manager."""
        projects = self.storage_manager.list_projects()
        if not projects:
            QMessageBox.warning(self, "提示", "当前存储路径下没有找到任何项目！")
            return
            
        base_storage_path = self.storage_manager.get_base_path()
        from views.video_check_dialog import BatchVideoCheckDialog
        dialog = BatchVideoCheckDialog(projects, base_storage_path, self)
        dialog.exec()

    def update_plugin_status_ui(self, info=None):
        """Updates the plugin connection status."""
        if hasattr(self, "lbl_plugin_status"):
            if not hasattr(self, "plugin_server") or not self.plugin_server:
                self.lbl_plugin_status.setText("🔌 插件未连接")
                self.lbl_plugin_status.setStyleSheet("color: #64748B; font-size: 12px; font-weight: bold; padding: 4px 8px; border: 1px solid #CBD5E1; border-radius: 4px; background-color: #F8FAFC;")
                return
                
            if not self.plugin_server.is_running():
                self.lbl_plugin_status.setText("⚪ 未开启识别（手动模式）")
                self.lbl_plugin_status.setToolTip("需要全局托管时，到「🤖 全局托管」页点击「🔌 开始识别浏览器」")
                self.lbl_plugin_status.setStyleSheet("color: #64748B; font-size: 12px; font-weight: bold; padding: 4px 8px; border: 1px solid #CBD5E1; border-radius: 4px; background-color: #F8FAFC;")
                return

            clients = self.plugin_server.get_online_clients()
            count = len(clients)
            if count == 0:
                self.lbl_plugin_status.setText("🟡 识别中，等待浏览器连接...")
                self.lbl_plugin_status.setStyleSheet("color: #D97706; font-size: 12px; font-weight: bold; padding: 4px 8px; border: 1px solid #FCD34D; border-radius: 4px; background-color: #FEF3C7;")
            else:
                pts_summary = ", ".join(f"{(c.get('email') or c.get('client_id', '')).split('@')[0]}:{c.get('remaining_points', 0)}分" for c in clients[:3])
                if len(clients) > 3:
                    pts_summary += "..."
                text = f"🟢 插件在线: {count} 个 ({pts_summary})"
                self.lbl_plugin_status.setText(text)
                self.lbl_plugin_status.setStyleSheet("color: #059669; font-size: 12px; font-weight: bold; padding: 4px 8px; border: 1px solid #A7F3D0; border-radius: 4px; background-color: #ECFDF5;")

    def manual_refresh_plugin_points(self):
        """Broadcasts get_points RPC request to all connected browsers to probe points."""
        if not hasattr(self, "plugin_server") or not self.plugin_server:
            QMessageBox.warning(self, "提示", "插件服务未启动。")
            return

        # 与「全局托管 → 刷新积分」走同一套逻辑：未开启识别时先开启，等待浏览器连上后再读积分
        if hasattr(self, "hosted_mode"):
            self.hosted_mode.on_refresh_points()
            return

        clients = self.plugin_server.get_online_clients()
        if not clients:
            QMessageBox.information(self, "提示", "当前没有在线的浏览器插件。请先打开 Google Flow 网页。")
            return

        sent_count = self.plugin_server.query_all_clients_points()
        if hasattr(self, "lbl_plugin_status"):
            self.lbl_plugin_status.setText("⏳ 正在探测各浏览器最新点数...")
            self.lbl_plugin_status.setStyleSheet("color: #D97706; font-size: 12px; font-weight: bold; padding: 4px 8px; border: 1px solid #FCD34D; border-radius: 4px; background-color: #FEF3C7;")
            QTimer.singleShot(2500, self.update_plugin_status_ui)
        else:
            self.statusBar().showMessage(f"已向 {sent_count} 个浏览器发送探测点数指令...", 3000)

    def on_plugin_alarm_detected(self, alarm_info):
        """Handles safety / unusual activity limit notification from Google Flow plugin."""
        client_id = alarm_info.get("client_id", "")
        msg = alarm_info.get("message", "检测到 Google 安全限制（异常活动）")
        if hasattr(self, "lbl_plugin_status"):
            self.lbl_plugin_status.setText(f"🚨 {client_id} 安全风控挂起")
            self.lbl_plugin_status.setStyleSheet("color: #DC2626; font-size: 12px; font-weight: bold; padding: 4px 8px; border: 1px solid #DC2626; border-radius: 4px; background-color: #FEE2E2;")
        QMessageBox.warning(
            self, "Google 安全限制警报",
            f"收到浏览器 Worker 【{client_id}】的告警：\n\n{msg}\n\n"
            "建议：请切到该浏览器窗口查看并手动消除网页安全验证，或等待插件自动刷新重试。"
        )

    def select_all_projects_for_pipeline(self):
        """Checks all project items in sidebar list."""
        for i in range(self.list_projects.count()):
            item = self.list_projects.item(i)
            item.setCheckState(Qt.CheckState.Checked)

    def deselect_all_projects_for_pipeline(self):
        """Unchecks all project items in sidebar list."""
        for i in range(self.list_projects.count()):
            item = self.list_projects.item(i)
            item.setCheckState(Qt.CheckState.Unchecked)

    def select_project_by_info(self, proj_info):
        """Selects and opens project in UI given its info dict."""
        target_path = proj_info.get("path") if isinstance(proj_info, dict) else str(proj_info)
        for i in range(self.list_projects.count()):
            item = self.list_projects.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == target_path:
                self.list_projects.setCurrentItem(item)
                self.detail_widget.set_project(target_path)
                break

    def batch_rename_all_images(self):
        """Iterates through all projects and auto-renames their images based on the global sequential rule."""
        projects = self.storage_manager.list_projects()
        if not projects:
            QMessageBox.information(self, "提示", "当前没有项目。")
            return
            
        # Sort projects by their natural index so numbering flows correctly
        try:
            projects.sort(key=lambda p: int(p.get("index_str", "0")))
        except Exception:
            projects.sort(key=lambda p: p.get("id", ""))
            
        reply = QMessageBox.question(
            self, "确认批量重命名",
            "是否要为所有项目自动重命名里面的图片？\n\n(规则：将所有项目视为一个整体，依次命名为 1.jpg, 2.jpg...)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            from models.project_model import ProjectModel
            total_renamed = 0
            current_idx = 1
            for p in projects:
                proj_path = self.storage_manager.resolve_path(p["id"])
                try:
                    proj = ProjectModel(proj_path)
                    renamed, current_idx = proj.rename_images(start_idx=current_idx, return_next_idx=True)
                    total_renamed += renamed
                except Exception as e:
                    print(f"Failed to rename project {p['id']}: {e}")
                    
            # Refresh current project detail if needed
            current_item = self.list_projects.currentItem()
            if current_item:
                self.on_project_clicked(current_item)
            QMessageBox.information(self, "完成", f"批量重命名完成，共重命名了 {total_renamed} 张图片！")

    def _on_main_tab_changed(self, index):
        """Handles top-level tab switches (refreshing Visual Review tasks or stopping video previews)."""
        current_w = self.main_tab_widget.widget(index)
        if hasattr(self, "visual_review_tab") and self.visual_review_tab:
            if current_w is self.visual_review_tab:
                self.visual_review_tab.refresh_flowcue_tasks()
            else:
                self.visual_review_tab.stop_all_video_previews()
        if hasattr(self, "batch_reels_tab") and self.batch_reels_tab and current_w is self.batch_reels_tab:
            self.batch_reels_tab.refresh_merged_projects_list()

    def _on_visual_review_updated(self, project_path_str):
        """Synchronizes review changes from VisualReviewTabWidget back to ProjectDetailWidget & project list."""
        try:
            if hasattr(self, "detail_widget") and self.detail_widget and self.detail_widget.project_path:
                if str(Path(self.detail_widget.project_path).resolve()) == str(Path(project_path_str).resolve()):
                    self.detail_widget.set_project(self.detail_widget.project_path)
            self.reload_projects_list()
        except Exception as e:
            print(f"Error syncing visual review update: {e}")

    def open_in_visual_review(self, project_path=None):
        """Switches to the Visual Review tab and selects the specified project."""
        if not hasattr(self, "visual_review_tab") or not self.visual_review_tab:
            return
        idx = self.main_tab_widget.indexOf(self.visual_review_tab)
        if idx >= 0:
            self.main_tab_widget.setCurrentIndex(idx)
        if project_path:
            self.visual_review_tab.select_project_by_path(project_path)

    def open_in_batch_reels(self, payload=None):
        """Switches to the Batch Reels tab and loads the merged video + SRT + word timings."""
        if not hasattr(self, "batch_reels_tab") or not self.batch_reels_tab:
            return
        idx = self.main_tab_widget.indexOf(self.batch_reels_tab)
        if idx >= 0:
            self.main_tab_widget.setCurrentIndex(idx)
        if payload:
            self.batch_reels_tab.load_flowcue_merged_task(payload)

    def open_batch_in_batch_reels(self, payloads=None):
        """Switches to the Batch Reels tab and batch-loads multiple merged videos + SRT + word timings."""
        if not hasattr(self, "batch_reels_tab") or not self.batch_reels_tab:
            return
        idx = self.main_tab_widget.indexOf(self.batch_reels_tab)
        if idx >= 0:
            self.main_tab_widget.setCurrentIndex(idx)
        if payloads:
            self.batch_reels_tab.load_flowcue_merged_tasks_batch(payloads)

    def _ensure_active_project_selected(self) -> bool:
        """Ensures a project is loaded in detail_widget (auto-selects first project if none selected)."""
        if hasattr(self, "detail_widget") and self.detail_widget and self.detail_widget.project_path:
            return True
        if hasattr(self, "list_projects") and self.list_projects.count() > 0:
            item = self.list_projects.currentItem() or self.list_projects.item(0)
            if item:
                self.list_projects.setCurrentItem(item)
                self.on_project_clicked(item)
                return bool(self.detail_widget.project_path)
        QMessageBox.information(self, "提示", "请先在左侧项目列表中选择一个项目（或先导入项目）！")
        return False

    def open_current_project_bulk_edit(self):
        """Opens the visual multi-select & preset batch manager dialog for the current project."""
        if not self._ensure_active_project_selected():
            return
        self.detail_widget.open_bulk_edit_dialog()

    def open_current_project_quick_review(self):
        """Jumps to Visual Review tab for the current project."""
        if hasattr(self, "detail_widget") and self.detail_widget and self.detail_widget.project_path:
            self.detail_widget.jump_to_visual_review()
            return
        if hasattr(self, "list_projects") and self.list_projects.count() > 0:
            item = self.list_projects.currentItem() or self.list_projects.item(0)
            if item:
                self.list_projects.setCurrentItem(item)
                self.on_project_clicked(item)
                if self.detail_widget.project_path:
                    self.detail_widget.jump_to_visual_review()
                    return
        self.open_in_visual_review()

    def open_current_project_folder(self):
        """Opens the current project's folder in Explorer (or base storage path if no project selected)."""
        if hasattr(self, "detail_widget") and self.detail_widget and self.detail_widget.project_path:
            self.detail_widget.open_project_folder()
            return
        if self._ensure_active_project_selected():
            self.detail_widget.open_project_folder()

    def open_batch_splice_all_dialog(self):
        """Opens the multi-task batch splice dialog to splice selected tasks one-by-one and send all to Batch Reels."""
        from views.video_compare_widget import BatchAllTasksSpliceDialog
        dlg = BatchAllTasksSpliceDialog(
            storage_manager=self.storage_manager,
            main_window=self,
            parent=self,
        )
        dlg.exec()
        try:
            if hasattr(self, "batch_reels_tab") and self.batch_reels_tab:
                self.batch_reels_tab.refresh_merged_projects_list()
        except Exception as e:
            print(f"Error refreshing after batch splice: {e}")

    def open_batch_verify_all_dialog(self):
        """Opens the parallel multi-task batch subtitle verification dialog (up to 4 tasks in parallel)."""
        from views.video_compare_widget import BatchAllTasksVerifyDialog
        dlg = BatchAllTasksVerifyDialog(
            storage_manager=self.storage_manager,
            config_manager=self.config_manager,
            default_engine="gladia",
            parent=self,
        )
        dlg.exec()
        try:
            if hasattr(self, "detail_widget") and self.detail_widget and self.detail_widget.project_path:
                self.detail_widget.set_project(self.detail_widget.project_path)
            self.reload_projects_list()
        except Exception as e:
            print(f"Error refreshing after batch verify: {e}")

    def closeEvent(self, event):
        """Clean up background tasks, plugin server, and media players before quitting."""
        # 停止后台扫描 / 拆批线程，避免退出时线程仍在运行
        for th in (getattr(self, "_status_thread", None),
                   getattr(getattr(self, "hosted_mode", None), "_planner_thread", None)):
            try:
                if th is not None and th.isRunning():
                    th.requestInterruption()
                    th.wait(3000)
            except Exception:
                pass
        if hasattr(self, "plugin_server") and self.plugin_server:
            try:
                self.plugin_server.stop()
            except Exception:
                pass
                
        if hasattr(self, "active_downloads"):
            for project_id, thread in list(self.active_downloads.items()):
                if thread and thread.isRunning():
                    thread.stop()
            self.active_downloads.clear()
            
        if hasattr(self, "detail_widget") and self.detail_widget:
            if hasattr(self.detail_widget, "cleanup"):
                self.detail_widget.cleanup()

        if hasattr(self, "visual_review_tab") and self.visual_review_tab:
            try:
                self.visual_review_tab.cleanup()
            except Exception:
                pass

        if hasattr(self, "batch_reels_tab") and self.batch_reels_tab:
            try:
                self.batch_reels_tab.shutdown()
            except Exception:
                pass
                
        super().closeEvent(event)


