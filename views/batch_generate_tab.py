# -*- coding: utf-8 -*-
import os
import json
import logging
from pathlib import Path
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QTextEdit, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QComboBox, QSpinBox, QFileDialog, QMessageBox,
                             QSplitter, QListWidget, QFrame, QInputDialog, QDialog, QMenu, QToolTip)
from PyQt6.QtCore import Qt, pyqtSlot, QUrl
from PyQt6.QtGui import QGuiApplication, QPixmap, QDesktopServices, QShortcut, QKeySequence, QCursor

logger = logging.getLogger(__name__)
from models.batch_model import BatchProjectModel
from views.project_detail_widget import BatchExportDialog

class NoWheelComboBox(QComboBox):
    """QComboBox that ignores mouse wheel events unless its popup view is open, preventing accidental changes while scrolling the table."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setMaxVisibleItems(12)
        if self.view():
            self.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def wheelEvent(self, event):
        if self.view() and self.view().isVisible():
            super().wheelEvent(event)
        else:
            event.ignore()


class NoWheelSpinBox(QSpinBox):
    """QSpinBox that ignores mouse wheel events to prevent accidental changes while scrolling."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):
        event.ignore()


class BatchGenerateTabWidget(QWidget):
    def __init__(self, plugin_server, parent=None):
        super().__init__(parent)
        self.plugin_server = plugin_server
        self.main_window = parent
        self._thumb_cache = {}
        self._is_rendering_table = False
        
        workspace = "."
        if self.main_window and hasattr(self.main_window, "workspace_dir"):
            workspace = self.main_window.workspace_dir
            
        self.model = BatchProjectModel(workspace)
        self.current_project = None
        self.init_ui()
        self.refresh_project_list()

    def init_ui(self):
        self.setStyleSheet("""
            QWidget#batch_root { background-color: #FAF6F0; }
            QLabel { font-size: 13px; color: #5D4037; font-weight: bold; }
            QPushButton { background-color: #E0A96D; color: white; border: none; border-radius: 4px; padding: 6px 12px; font-weight: bold; }
            QPushButton:hover { background-color: #D2904C; }
            QPushButton:pressed { background-color: #B87635; }
            QPushButton#btn_delete { background-color: #E57373; }
            QPushButton#btn_delete:hover { background-color: #EF5350; }
            QTextEdit, QTableWidget, QSpinBox, QComboBox, QListWidget { border: 1px solid #D7CCC8; border-radius: 4px; background-color: white; }
        """)
        self.setObjectName("batch_root")
        
        main_layout = QVBoxLayout(self)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter, stretch=1)
        
        # ================= LEFT PANEL =================
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 10, 0)
        
        h_import = QHBoxLayout()
        self.btn_import_folder = QPushButton("📁 导入文件夹")
        self.btn_import_folder.clicked.connect(self.import_folder)
        self.btn_import_images = QPushButton("🖼️ 导入图片")
        self.btn_import_images.clicked.connect(self.import_images)
        h_import.addWidget(self.btn_import_folder)
        h_import.addWidget(self.btn_import_images)
        left_layout.addLayout(h_import)
        
        self.list_projects = QListWidget()
        self.list_projects.currentRowChanged.connect(self.on_project_selected)
        left_layout.addWidget(self.list_projects)
        
        self.btn_delete_project = QPushButton("🗑️ 删除选中任务")
        self.btn_delete_project.setObjectName("btn_delete")
        self.btn_delete_project.clicked.connect(self.delete_selected_project)
        left_layout.addWidget(self.btn_delete_project)
        
        # ================= RIGHT PANEL =================
        self.right_panel = QWidget()
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(10, 0, 0, 0)
        
        config_frame = QFrame()
        config_frame.setStyleSheet("QFrame { background-color: white; border: 1px solid #D7CCC8; border-radius: 6px; }")
        config_vbox = QVBoxLayout(config_frame)
        config_vbox.setContentsMargins(10, 8, 10, 8)
        config_vbox.setSpacing(6)

        config_layout = QHBoxLayout()
        
        config_layout.addWidget(QLabel("整体预设:"))
        self.cb_template = NoWheelComboBox()
        self.cb_template.setMinimumWidth(160)
        self.cb_template.setToolTip("设置当前任务的整体默认描述词预设（未单独指定预设的单条任务将自动跟随此预设）")
        self.cb_template.currentIndexChanged.connect(self.on_template_changed)
        config_layout.addWidget(self.cb_template)

        self.btn_reset_row_presets = QPushButton("🔄 全部跟随整体")
        self.btn_reset_row_presets.setToolTip("清除列表中所有单条任务的独立预设，统一恢复为跟随上方的「整体预设」")
        self.btn_reset_row_presets.setStyleSheet("background-color: #8D6E63; color: white; padding: 5px 10px; font-size: 12px;")
        self.btn_reset_row_presets.clicked.connect(self.reset_all_row_templates_to_global)
        config_layout.addWidget(self.btn_reset_row_presets)
        
        config_layout.addWidget(QLabel("单个任务块时长:"))
        self.cb_duration = NoWheelComboBox()
        self.cb_duration.addItems(["4秒", "6秒", "8秒", "10秒"])
        self.cb_duration.setCurrentText("8秒")
        self.cb_duration.currentIndexChanged.connect(self.on_duration_changed)
        config_layout.addWidget(self.cb_duration)

        config_layout.addWidget(QLabel("画面尺寸:"))
        self.cb_aspect = NoWheelComboBox()
        self.cb_aspect.setToolTip("每个批量任务单独设置画面尺寸比例（不再跟随规则设置），导出 JSON / 一键多开分配时使用此尺寸")
        try:
            from models.config_manager import ConfigManager
            _aspects = list(getattr(ConfigManager, "SUPPORTED_ASPECT_RATIOS", []))
        except Exception:
            _aspects = []
        if not _aspects:
            _aspects = [("9:16", "9:16 (竖屏)"), ("16:9", "16:9 (横屏)")]
        for a_code, a_label in _aspects:
            self.cb_aspect.addItem(a_label, a_code)
        self.cb_aspect.currentIndexChanged.connect(self.on_aspect_changed)
        config_layout.addWidget(self.cb_aspect)
        
        config_layout.addWidget(QLabel("单批次生成积分上限:"))
        self.sb_points = NoWheelSpinBox()
        self.sb_points.setRange(1, 1000)
        self.sb_points.setValue(50)
        self.sb_points.setToolTip("每个导出的JSON任务块最高消耗积分（修改此数值不会触发重算卡顿，仅在点击一键多开分配生成时按此上限计算）")
        self.sb_points.valueChanged.connect(self.on_points_limit_changed)
        self.sb_points.editingFinished.connect(self.on_points_editing_finished)
        config_layout.addWidget(self.sb_points)
        config_layout.addStretch()
        config_vbox.addLayout(config_layout)

        # Row 2: Category selection & sequential/cycle distribution ("随机发放")
        cat_distribute_layout = QHBoxLayout()
        cat_distribute_layout.addWidget(QLabel("📂 预设分类:"))
        self.cb_category = NoWheelComboBox()
        self.cb_category.setMinimumWidth(220)
        self.cb_category.setToolTip("选择在「模板配置 -> 批量模板」中设置好的预设分类")
        cat_distribute_layout.addWidget(self.cb_category)

        self.btn_distribute_category = QPushButton("🎲 随机发放")
        self.btn_distribute_category.setToolTip(
            "将所选分类下的预设按顺序（1、2、3...）依次分配给下方每一条任务的「单独预设」，\n"
            "尽量不重复；当任务数多于该分类的预设数时自动从头循环铺满全部任务。"
        )
        self.btn_distribute_category.setStyleSheet(
            "QPushButton { background-color: #7E57C2; color: white; padding: 5px 14px; font-size: 13px; font-weight: bold; border-radius: 4px; }"
            "QPushButton:hover { background-color: #673AB7; }"
            "QPushButton:pressed { background-color: #512DA8; }"
        )
        self.btn_distribute_category.clicked.connect(self.distribute_category_presets_to_rows)
        cat_distribute_layout.addWidget(self.btn_distribute_category)

        cat_distribute_layout.addSpacing(12)
        cat_distribute_layout.addWidget(QLabel("📍 粘贴起始行:"))
        self.sb_paste_start_row = NoWheelSpinBox()
        self.sb_paste_start_row.setRange(1, 9999)
        self.sb_paste_start_row.setValue(1)
        self.sb_paste_start_row.setPrefix("第 ")
        self.sb_paste_start_row.setSuffix(" 行")
        self.sb_paste_start_row.setToolTip(
            "设置从第几行开始粘贴表格提示词（点击下方表格任意行也会自动同步此起始行号；粘贴完成后会自动推进到下一行）"
        )
        cat_distribute_layout.addWidget(self.sb_paste_start_row)

        self.btn_paste_prompts_table = QPushButton("📋 表格粘贴提示词")
        self.btn_paste_prompts_table.setToolTip(
            "直接在表格（Excel / WPS / 飞书 / 谷歌表格）中复制多行「提示词」，\n"
            "点击此按钮即可从指定的「起始行」开始依次往下批量填充到「提示词」列（也支持在表格中选中起始行后直接按 Ctrl+V 或右键粘贴）！"
        )
        self.btn_paste_prompts_table.setStyleSheet(
            "QPushButton { background-color: #0288D1; color: white; padding: 5px 14px; font-size: 13px; font-weight: bold; border-radius: 4px; }"
            "QPushButton:hover { background-color: #0277BD; }"
            "QPushButton:pressed { background-color: #01579B; }"
        )
        self.btn_paste_prompts_table.clicked.connect(
            lambda: self.paste_prompts_from_clipboard(start_row=self.sb_paste_start_row.value() - 1)
        )
        cat_distribute_layout.addWidget(self.btn_paste_prompts_table)

        lbl_cat_hint = QLabel("💡 可直接从表格复制多行提示词，选好起始行后点击「📋 表格粘贴提示词」（或在列表某行按 Ctrl+V / 右键粘贴）")
        lbl_cat_hint.setStyleSheet("color: #8D6E63; font-size: 12px; font-weight: normal;")
        cat_distribute_layout.addWidget(lbl_cat_hint)
        cat_distribute_layout.addStretch()
        config_vbox.addLayout(cat_distribute_layout)
        
        right_layout.addWidget(config_frame)
        
        h_action = QHBoxLayout()
        self.btn_save_settings = QPushButton("💾 保存设置")
        self.btn_save_settings.setToolTip("保存当前任务的整体预设、每个单任务的独立预设、时长及手动修改的提示词")
        self.btn_save_settings.setStyleSheet("background-color: #1976D2; color: white; font-size: 14px; padding: 6px 16px;")
        self.btn_save_settings.clicked.connect(self.save_all_settings_manual)
        h_action.addWidget(self.btn_save_settings)

        self.btn_allocate = QPushButton("🚀 一键多开分配生成 (分批JSON)")
        self.btn_allocate.setStyleSheet("background-color: #4CAF50; font-size: 14px;")
        self.btn_allocate.clicked.connect(self.export_batch_json)
        h_action.addWidget(self.btn_allocate, stretch=1)
        
        self.btn_export_all = QPushButton("📤 导出全部JSON")
        self.btn_export_all.clicked.connect(self.export_all_json)
        h_action.addWidget(self.btn_export_all)
        right_layout.addLayout(h_action)
        
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["序号", "图片预览", "图片名称", "时长", "单独预设", "提示词", "操作"])
        self.table.verticalHeader().setDefaultSectionSize(78)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 118)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(4, 185)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellDoubleClicked.connect(self.on_table_cell_double_clicked)
        self.table.cellClicked.connect(self._on_table_cell_clicked)
        self.table.itemChanged.connect(self.on_table_item_changed)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.on_table_context_menu)
        self._paste_shortcut = QShortcut(QKeySequence.StandardKey.Paste, self.table)
        self._paste_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self._paste_shortcut.activated.connect(self._on_table_paste_shortcut)

        # 轻量委托：缩略图按需加载、预设下拉框点击才创建、操作按钮直接绘制（不再每行创建多个控件）
        from views.table_delegates import ThumbnailDelegate, ComboDelegate, TableButtonDelegate
        self._thumb_delegate = ThumbnailDelegate(lambda p: self._get_thumbnail_pixmap(p, 102, 64), self.table)
        self.table.setItemDelegateForColumn(1, self._thumb_delegate)
        self._preset_delegate = ComboDelegate(self._row_preset_items, self._on_row_preset_committed, self.table,
                                              combo_factory=lambda parent: NoWheelComboBox(parent))
        self.table.setItemDelegateForColumn(4, self._preset_delegate)
        self._action_delegate = TableButtonDelegate(["复制提示词", "复制路径", "导出JSON"], self.table,
                                                    colors=["#E0A96D"] * 3, hover_colors=["#D2904C"] * 3)
        self._action_delegate.clicked.connect(self._on_row_action_clicked)
        self.table.setItemDelegateForColumn(6, self._action_delegate)
        self.table.setMouseTracking(True)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(6, 250)
        right_layout.addWidget(self.table)
        
        splitter.addWidget(left_panel)
        splitter.addWidget(self.right_panel)
        splitter.setSizes([300, 700])
        self.right_panel.setEnabled(False)

    def _get_batch_templates_list(self):
        """Return the list of batch templates from template_manager."""
        if self.main_window and hasattr(self.main_window, "template_manager"):
            tm = self.main_window.template_manager
            if hasattr(tm, "batch_templates"):
                return tm.batch_templates
        return []

    def _get_template_content_by_id(self, tpl_id: str) -> str:
        """Look up batch template content by template ID or preset name."""
        if not tpl_id:
            return ""
        tpl = self._find_batch_template(tpl_id)
        if tpl:
            return tpl.get("content", "")
        return ""

    def _find_batch_template(self, identifier: str):
        """
        Look up a batch template using preset Name as ID (or internal ID).
        Supports:
        1. Exact match on preset name (e.g. '男声1')
        2. Exact match on internal id (e.g. 'bt-xxxx')
        3. Case-insensitive match on preset name
        4. Match after stripping category prefix like '【分类】名称', '[分类] 名称', '📌 [分类] 名称'
        """
        import re
        key = (identifier or "").strip()
        if not key:
            return None
        batch_templates = self._get_batch_templates_list()
        if not batch_templates:
            return None

        # 1. Exact match on name
        for t in batch_templates:
            if (t.get("name") or "").strip() == key:
                return t
        # 2. Exact match on id
        for t in batch_templates:
            if (t.get("id") or "").strip() == key:
                return t
        # 3. Case-insensitive match on name
        key_lower = key.lower()
        for t in batch_templates:
            if (t.get("name") or "").strip().lower() == key_lower:
                return t
        # 4. Strip optional category badge prefix e.g. "📌 [分类] 名称" or "【分类】名称"
        stripped_key = re.sub(r'^(?:📌\s*)?(?:[\[【][^\]】]*[\]】]\s*)?', '', key).strip()
        if stripped_key and stripped_key != key:
            stripped_lower = stripped_key.lower()
            for t in batch_templates:
                t_name = (t.get("name") or "").strip()
                if t_name == stripped_key or t_name.lower() == stripped_lower:
                    return t
        return None

    def refresh_project_list(self):
        self.list_projects.clear()
        for p in self.model.projects:
            self.list_projects.addItem(self._project_list_label(p))

    def _project_list_label(self, p):
        return f"{p['name']} ({len(p['images'])}图 · {self._get_project_aspect(p)})"
            
    def refresh_template_list(self):
        prev_tpl_id = self.cb_template.currentData()
        if not prev_tpl_id and self.current_project:
            prev_tpl_id = self.current_project.get("template_id", "")
        batch_templates = self._get_batch_templates_list()
        self.cb_template.blockSignals(True)
        self.cb_template.clear()
        self.cb_template.addItem("未选择", "")
        for t in batch_templates:
            cat = (t.get("category") or "").strip()
            label = f"【{cat}】{t.get('name', '未命名')}" if cat else t.get("name", "未命名")
            self.cb_template.addItem(label, t.get("id"))
        if prev_tpl_id:
            idx = self.cb_template.findData(prev_tpl_id)
            if idx >= 0:
                self.cb_template.setCurrentIndex(idx)
        self.cb_template.blockSignals(False)

        if hasattr(self, "cb_category"):
            prev_cat = self.cb_category.currentData()
            self.cb_category.blockSignals(True)
            self.cb_category.clear()
            tm = getattr(self.main_window, "template_manager", None) if self.main_window else None
            categories = tm.get_batch_categories() if (tm and hasattr(tm, "get_batch_categories")) else []
            for c in categories:
                cnt = sum(1 for t in batch_templates if (t.get("category") or "").strip() == c)
                self.cb_category.addItem(f"📂 {c} ({cnt}个预设)", c)
            self.cb_category.addItem(f"📋 全部批量预设 ({len(batch_templates)}个)", "__ALL__")
            if prev_cat:
                c_idx = self.cb_category.findData(prev_cat)
                if c_idx >= 0:
                    self.cb_category.setCurrentIndex(c_idx)
            self.cb_category.blockSignals(False)

        if self.current_project and not self._is_rendering_table:
            self.render_table()

    def _get_next_task_name(self):
        def to_chinese_num(n):
            units = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
            if n < 10: return units[n]
            if n == 10: return "十"
            if n < 20: return "十" + units[n % 10]
            if n < 100:
                tens = units[n // 10] + "十"
                return tens if n % 10 == 0 else tens + units[n % 10]
            return str(n)
            
        import re
        max_idx = 0
        for p in self.model.projects:
            name = p.get("name", "")
            if name.startswith("批量生成"):
                # fallback for basic numbers just in case
                num_str = name.replace("批量生成", "")
                if num_str.isdigit():
                    max_idx = max(max_idx, int(num_str))
                else:
                    # simplistic check for chinese numbering up to 99
                    for i in range(1, 100):
                        if num_str == to_chinese_num(i):
                            max_idx = max(max_idx, i)
                            break
                            
        return f"批量生成{to_chinese_num(max_idx + 1)}"

    def import_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择图片文件夹")
        if not folder:
            return
        
        valid_exts = {'.png', '.jpg', '.jpeg', '.webp'}
        images = []
        try:
            for f in os.listdir(folder):
                if Path(f).suffix.lower() in valid_exts:
                    images.append(os.path.join(folder, f))
            images.sort()
        except Exception as e:
            logger.error(f"Error reading directory: {e}")
            
        if not images:
            QMessageBox.warning(self, "无图片", "该文件夹下没有支持的图片文件。")
            return
            
        name = self._get_next_task_name()
        self.create_new_project(name, images)

    def import_images(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择图片", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if not files:
            return
        files.sort()
        name = self._get_next_task_name()
        self.create_new_project(name, files)
        
    def create_new_project(self, name, files):
        images_data = []
        for f in files:
            images_data.append({
                "path": f,
                "prompt": "",
                "template_id": "",
                "duration": 8
            })
        self.model.create_project(name, images_data)
        self.refresh_project_list()
        self.list_projects.setCurrentRow(len(self.model.projects) - 1)

    def delete_selected_project(self):
        row = self.list_projects.currentRow()
        if row < 0: return
        p = self.model.projects[row]
        reply = QMessageBox.question(self, "删除确认", f"确定要删除任务 '{p['name']}' 吗？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.model.delete_project(p["id"])
            self.refresh_project_list()
            self.right_panel.setEnabled(False)

    def on_project_selected(self, row):
        if row < 0 or row >= len(self.model.projects):
            self.current_project = None
            self.right_panel.setEnabled(False)
            return
            
        self.current_project = self.model.projects[row]
        self.right_panel.setEnabled(True)
        self._is_rendering_table = True
        self.refresh_template_list()
        self._is_rendering_table = False
        
        self.cb_duration.blockSignals(True)
        self.sb_points.blockSignals(True)
        self.cb_template.blockSignals(True)
        
        self.cb_duration.setCurrentText(f"{self.current_project.get('duration', 8)}秒")
        self.sb_points.setValue(self.current_project.get('points_cost', 50))
        self.cb_aspect.blockSignals(True)
        a_idx = self.cb_aspect.findData(self._get_project_aspect())
        self.cb_aspect.setCurrentIndex(a_idx if a_idx >= 0 else 0)
        self.cb_aspect.blockSignals(False)
        
        tpl_id = self.current_project.get("template_id", "")
        idx = self.cb_template.findData(tpl_id)
        if idx >= 0:
            self.cb_template.setCurrentIndex(idx)
        else:
            self.cb_template.setCurrentIndex(0)
            
        self.cb_duration.blockSignals(False)
        self.sb_points.blockSignals(False)
        self.cb_template.blockSignals(False)
        if hasattr(self, "sb_paste_start_row"):
            img_cnt = max(1, len(self.current_project.get("images", [])))
            self.sb_paste_start_row.setRange(1, img_cnt)
            self.sb_paste_start_row.setValue(1)
        
        self.render_table()

    def on_template_changed(self):
        if not self.current_project: return
        tpl_id = self.cb_template.currentData()
        self.current_project["template_id"] = tpl_id
        content = self._get_template_content_by_id(tpl_id)
                        
        for img in self.current_project["images"]:
            # If user manually pasted/typed a custom prompt and tpl_id is cleared ("未选择"), keep user's prompt
            if not tpl_id and img.get("prompt"):
                continue
            # Only overwrite rows that follow the global preset (no individual template_id set)
            if not img.get("template_id"):
                img["prompt"] = content
            
        self.model.save_project(self.current_project)
        self.render_table()

    def reset_all_row_templates_to_global(self):
        """Reset all individual row presets to follow the global preset."""
        if not self.current_project:
            return
        global_tpl_id = self.cb_template.currentData() or ""
        global_content = self._get_template_content_by_id(global_tpl_id)
        for img in self.current_project.get("images", []):
            img["template_id"] = ""
            img["prompt"] = global_content
        self.model.save_project(self.current_project)
        self.render_table()
        QMessageBox.information(self, "已恢复跟随整体预设", "所有单条任务的单独预设已清除，现已统一跟随上方的「整体预设」！")

    def distribute_category_presets_to_rows(self):
        """
        将所选分类下的预设按顺序（1, 2, 3, ..., K）依次循环发放给所有单条任务的「单独预设」，
        若任务数大于预设数（如 20 个任务、10 个预设），则发完一轮 1~10 后继续从 1~10 循环铺满。
        """
        if not self.current_project:
            QMessageBox.warning(self, "提示", "请先在左侧选择或导入一个批量任务！")
            return

        images = self.current_project.get("images", [])
        if not images:
            QMessageBox.warning(self, "提示", "当前批量任务中没有图片条目。")
            return

        selected_cat = self.cb_category.currentData() if hasattr(self, "cb_category") else "__ALL__"
        all_templates = self._get_batch_templates_list()
        if selected_cat in ("__ALL__", None, ""):
            pool = list(all_templates)
            cat_display = "全部批量预设"
        else:
            pool = [t for t in all_templates if (t.get("category") or "").strip() == selected_cat]
            cat_display = selected_cat

        if not pool:
            QMessageBox.warning(
                self,
                "该分类下无预设",
                f"分类【{cat_display}】下还没有任何预设！\n\n"
                "请先点击顶部「⚙️ 模板配置」->「🚀 批量模板」，将预设设置到该分类后再点击随机发放。"
            )
            return

        pool_len = len(pool)
        for i, img in enumerate(images):
            chosen_tpl = pool[i % pool_len]
            img["template_id"] = chosen_tpl.get("id", "")
            img["prompt"] = chosen_tpl.get("content", "")

        self.model.save_project(self.current_project)
        self.render_table()
        QMessageBox.information(
            self,
            "发放完成",
            f"🎲 已按分类【{cat_display}】（共 {pool_len} 个预设）依次循环发放，\n"
            f"已将全部 {len(images)} 条任务的「单独预设」与「提示词」自动铺满并保存！"
        )

    def _on_table_cell_clicked(self, row: int, col: int):
        """Sync the paste starting row spinbox when user clicks a row in the table."""
        if hasattr(self, "sb_paste_start_row") and row >= 0:
            self.sb_paste_start_row.setValue(row + 1)
        if row < 0 or not self.current_project:
            return
        if col == 4:
            it = self.table.item(row, 4)
            if it is not None:
                self.table.editItem(it)
        elif col == 1:
            images = self.current_project.get("images", [])
            if row < len(images):
                self._show_large_image_preview(images[row].get("path", ""), row + 1)

    def _parse_prompts_from_clipboard(self) -> list:
        """
        Parse multi-row prompts copied from a spreadsheet (Excel / WPS / Feishu / Google Sheets) or plain text.
        Supports multiline cells inside Excel (quoted TSV or HTML <table>) and preserves row alignment.
        """
        import csv
        import io
        import re
        from bs4 import BeautifulSoup

        clipboard = QGuiApplication.clipboard()
        mime_data = clipboard.mimeData()
        if not mime_data:
            return []

        tsv_rows = []
        html_rows = []

        if mime_data.hasText():
            text = mime_data.text()
            if text and text.strip():
                cleaned = text.rstrip("\r\n")
                try:
                    reader = csv.reader(io.StringIO(cleaned), delimiter="\t")
                    for cols in reader:
                        tsv_rows.append([c.strip() for c in cols] if cols else [""])
                except Exception:
                    tsv_rows = [[line.strip()] for line in cleaned.splitlines()]

        if mime_data.hasHtml():
            html_text = mime_data.html()
            if html_text and "<tr" in html_text.lower():
                soup = BeautifulSoup(html_text, "html.parser")
                for tr in soup.find_all("tr"):
                    tds = tr.find_all(["td", "th"])
                    if not tds:
                        continue
                    row_cells = []
                    for td in tds:
                        for br in td.find_all("br"):
                            br.replace_with("\n")
                        block_tags = td.find_all(["p", "div"])
                        if block_tags:
                            lines = [re.sub(r"\s+", " ", b.get_text()).strip() for b in block_tags if b.get_text().strip()]
                            cell_txt = "\n".join(lines) if lines else td.get_text().strip()
                        else:
                            raw = td.get_text()
                            parts = [re.sub(r"[ \t\r]+", " ", ln).strip() for ln in raw.split("\n")]
                            cell_txt = "\n".join(p for p in parts if p) if len(parts) > 1 else re.sub(r"\s+", " ", raw).strip()
                        row_cells.append(cell_txt)
                    html_rows.append(row_cells)

        # Prefer TSV when row counts match or HTML is absent; use HTML if unquoted newlines split TSV rows
        if tsv_rows and (not html_rows or len(tsv_rows) == len(html_rows)):
            raw_rows = tsv_rows
        elif html_rows:
            raw_rows = html_rows
        else:
            raw_rows = tsv_rows

        if not raw_rows:
            return []

        # If user copied 2+ columns (e.g. [序号 | 提示词]), pick the column that contains the actual prompt text
        max_cols = max(len(r) for r in raw_rows)
        best_col = 0
        if max_cols > 1:
            # Choose the column with the longest average text length (ignoring purely numeric index columns)
            best_len = -1
            for col_idx in range(max_cols):
                vals = [r[col_idx].strip() for r in raw_rows if col_idx < len(r) and r[col_idx].strip()]
                if not vals:
                    continue
                if all(v.isdigit() for v in vals):
                    continue
                avg_len = sum(len(v) for v in vals) / len(vals)
                if avg_len > best_len:
                    best_len = avg_len
                    best_col = col_idx

        extracted = [(r[best_col].strip() if best_col < len(r) else "") for r in raw_rows]

        # Auto-skip header row if the user copied the column header "提示词" / "描述词" / "Prompt"
        header_keywords = {"提示词", "描述词", "模板内容", "预设内容", "内容", "prompt", "prompts"}
        if len(extracted) > 1 and extracted[0].strip().lower() in header_keywords:
            extracted = extracted[1:]

        return extracted

    def paste_prompts_from_clipboard(self, start_row: int = 0):
        """
        Paste multi-row prompts from clipboard directly into the '提示词' column (Col 5)
        starting from `start_row` (0-based). User-filled prompts take top priority.
        After pasting N rows, automatically advances `sb_paste_start_row` to `start_row + N + 1`.
        """
        if not self.current_project:
            QMessageBox.warning(self, "提示", "请先在左侧选择或导入一个批量任务！")
            return

        images = self.current_project.get("images", [])
        if not images:
            QMessageBox.warning(self, "提示", "当前批量任务中没有图片条目。")
            return

        prompts = self._parse_prompts_from_clipboard()
        if not prompts or not any(p.strip() for p in prompts):
            QMessageBox.warning(
                self,
                "剪贴板无有效提示词",
                "未能从剪贴板读取到提示词内容！\n\n"
                "📌 使用方法：\n"
                "1. 在表格（Excel / WPS / 飞书 / 谷歌表格）中直接复制 1 行或多行「提示词」\n"
                "2. 选择好「粘贴起始行」（或直接在下方表格中点击目标起始行）\n"
                "3. 点击「📋 表格粘贴提示词」或直接按 Ctrl+V / 右键粘贴，即可从起始行开始依次往下填充提示词！"
            )
            return

        if start_row < 0:
            start_row = 0
        if start_row >= len(images):
            QMessageBox.warning(
                self,
                "起始行超出范围",
                f"当前任务共有 {len(images)} 行，而您选择的起始行为第 {start_row + 1} 行，请重新选择起始行！"
            )
            return

        filled_count = 0
        actual_start_1based = start_row + 1
        actual_end_1based = start_row + 1

        self._is_rendering_table = True
        try:
            for offset, text in enumerate(prompts):
                target_row = start_row + offset
                if target_row >= len(images):
                    break
                clean_text = (text or "").strip()
                images[target_row]["prompt"] = clean_text
                prompt_item = self.table.item(target_row, 5)
                if prompt_item is not None:
                    prompt_item.setText(clean_text)
                else:
                    self.table.setItem(target_row, 5, QTableWidgetItem(clean_text))
                filled_count += 1
                actual_end_1based = target_row + 1
        finally:
            self._is_rendering_table = False

        self.model.save_project(self.current_project)

        # Advance starting row to the next unfilled row for convenient continuous pasting
        next_row_0based = min(start_row + filled_count, len(images) - 1)
        if hasattr(self, "sb_paste_start_row"):
            self.sb_paste_start_row.setRange(1, max(1, len(images)))
            self.sb_paste_start_row.setValue(min(start_row + filled_count + 1, len(images)))
        self.table.setCurrentCell(next_row_0based, 5)

        extra_cnt = max(0, len(prompts) - filled_count)
        extra_note = f"\n• 超出任务总行数的 {extra_cnt} 行已自动忽略" if extra_cnt > 0 else ""
        next_hint = (
            f"\n• 下一次粘贴起始行已自动推进至：第 {start_row + filled_count + 1} 行"
            if (start_row + filled_count) < len(images)
            else "\n• 已粘贴至最后一行"
        )
        QMessageBox.information(
            self,
            "表格提示词粘贴成功",
            f"✅ 已成功粘贴 {filled_count} 行提示词！\n\n"
            f"• 填充范围：第 {actual_start_1based} 行 ～ 第 {actual_end_1based} 行"
            f"{extra_note}"
            f"{next_hint}"
        )

    def _on_table_paste_shortcut(self):
        """Handle Ctrl+V on the table to paste multi-row prompts starting from current selected row."""
        if not self.current_project:
            return
        cur_row = self.table.currentRow()
        if cur_row < 0:
            cur_row = (self.sb_paste_start_row.value() - 1) if hasattr(self, "sb_paste_start_row") else 0
        self.paste_prompts_from_clipboard(start_row=max(0, cur_row))

    def on_table_context_menu(self, pos):
        """Right-click context menu on the batch table for multi-row prompt pasting from any starting row."""
        if not self.current_project:
            return
        item = self.table.itemAt(pos)
        clicked_row = item.row() if item else max(0, self.table.currentRow())
        if hasattr(self, "sb_paste_start_row") and clicked_row >= 0:
            self.sb_paste_start_row.setValue(clicked_row + 1)

        menu = QMenu(self)
        act_paste_from_cur = menu.addAction(f"📋 从第 {clicked_row + 1} 行开始粘贴表格提示词 (Ctrl+V)")
        act_paste_from_top = None
        if clicked_row > 0:
            act_paste_from_top = menu.addAction("📋 从第 1 行开始粘贴表格提示词")
        menu.addSeparator()
        act_clear_cur_prompt = menu.addAction(f"🧹 清空第 {clicked_row + 1} 行提示词")
        act_reset_all = menu.addAction("🔄 将全部行恢复为「跟随整体预设」")

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == act_paste_from_cur:
            self.paste_prompts_from_clipboard(start_row=clicked_row)
        elif act_paste_from_top and chosen == act_paste_from_top:
            self.paste_prompts_from_clipboard(start_row=0)
        elif chosen == act_clear_cur_prompt:
            images = self.current_project.get("images", [])
            if 0 <= clicked_row < len(images):
                images[clicked_row]["prompt"] = ""
                self._is_rendering_table = True
                prompt_item = self.table.item(clicked_row, 5)
                if prompt_item:
                    prompt_item.setText("")
                self._is_rendering_table = False
                self.model.save_project(self.current_project)
        elif chosen == act_reset_all:
            self.reset_all_row_templates_to_global()

    def _find_batch_template_by_id(self, tpl_id):
        for t in self._get_batch_templates_list():
            if t.get("id") == tpl_id:
                return t
        return None

    def _row_preset_items(self):
        """Items for the per-row preset dropdown (built only when the user clicks the cell)."""
        items = [("🔗 跟随整体预设", "")]
        for t in self._get_batch_templates_list():
            cat = (t.get("category") or "").strip()
            label = f"📌 [{cat}] {t.get('name', '未命名')}" if cat else f"📌 {t.get('name', '未命名')}"
            items.append((label, t.get("id", "")))
        return items

    def _set_preset_item(self, item, tpl):
        """Show the preset name in the cell, highlighting rows with a custom preset."""
        from PyQt6.QtGui import QColor, QFont
        if tpl:
            cat = (tpl.get("category") or "").strip()
            item.setText((f"📌 [{cat}] {tpl.get('name', '未命名')}" if cat else f"📌 {tpl.get('name', '未命名')}") + " ▾")
            item.setData(Qt.ItemDataRole.UserRole, tpl.get("id", ""))
            item.setForeground(QColor("#E65100"))
            f = QFont()
            f.setBold(True)
            item.setFont(f)
        else:
            item.setText("🔗 跟随整体预设 ▾")
            item.setData(Qt.ItemDataRole.UserRole, "")
            item.setData(Qt.ItemDataRole.ForegroundRole, None)
            item.setFont(QFont())
        item.setToolTip("单击选择该单条任务的独立描述词预设（默认跟随整体预设）")

    def _on_row_preset_committed(self, row: int, tpl_id: str):
        self.on_row_template_changed(row, tpl_id)

    def _on_row_action_clicked(self, row: int, which: int):
        if not self.current_project:
            return
        images = self.current_project.get("images", [])
        if not (0 <= row < len(images)):
            return
        if which == 0:
            QGuiApplication.clipboard().setText(images[row].get("prompt", ""))
            QToolTip.showText(QCursor.pos(), "已复制提示词", self.table)
        elif which == 1:
            QGuiApplication.clipboard().setText(images[row].get("path", ""))
            QToolTip.showText(QCursor.pos(), "已复制图片路径", self.table)
        elif which == 2:
            self.export_single_json(row)

    def on_row_template_changed(self, row: int, row_tpl_id: str):
        """Handle changing a single row's individual template preset."""
        if self._is_rendering_table or not self.current_project:
            return
        images = self.current_project.get("images", [])
        if row < 0 or row >= len(images):
            return

        row_tpl_id = row_tpl_id or ""
        images[row]["template_id"] = row_tpl_id
        if row_tpl_id:
            new_prompt = self._get_template_content_by_id(row_tpl_id)
        else:
            global_tpl_id = self.cb_template.currentData() or self.current_project.get("template_id", "")
            new_prompt = self._get_template_content_by_id(global_tpl_id)

        images[row]["prompt"] = new_prompt

        # Update cells in place without rebuilding the table
        self._is_rendering_table = True
        try:
            preset_item = self.table.item(row, 4)
            if preset_item is not None:
                self._set_preset_item(preset_item, self._find_batch_template_by_id(row_tpl_id) if row_tpl_id else None)
            prompt_item = self.table.item(row, 5)
            if prompt_item:
                prompt_item.setText(new_prompt)
            else:
                self.table.setItem(row, 5, QTableWidgetItem(new_prompt))
        finally:
            self._is_rendering_table = False

        self.model.save_project(self.current_project)

    def on_table_item_changed(self, item: QTableWidgetItem):
        """Persist manual edits to the Prompt column (col 5) immediately."""
        if self._is_rendering_table or not self.current_project:
            return
        row = item.row()
        col = item.column()
        images = self.current_project.get("images", [])
        if col == 5 and 0 <= row < len(images):
            images[row]["prompt"] = item.text()
            self.model.save_project(self.current_project)

    def on_duration_changed(self):
        """Update duration in-place without rebuilding the entire table or recalculating batches."""
        if not self.current_project:
            return
        try:
            new_dur = int(self.cb_duration.currentText().replace("秒", ""))
        except ValueError:
            new_dur = 8
        self.current_project["duration"] = new_dur
        dur_str = f"{new_dur}秒"
        images = self.current_project.get("images", [])
        self._is_rendering_table = True
        try:
            for i, img in enumerate(images):
                img["duration"] = new_dur
                if i < self.table.rowCount():
                    item = self.table.item(i, 3)
                    if item is not None:
                        item.setText(dur_str)
        finally:
            self._is_rendering_table = False
        self.model.save_project(self.current_project)

    def _get_project_aspect(self, project=None):
        """Per-task aspect ratio; legacy tasks without one fall back to the old global batch setting, then 9:16."""
        p = project if project is not None else self.current_project
        val = (p or {}).get("aspect_ratio") if p else None
        if val:
            return val
        cm = getattr(self.main_window, "config_manager", None) if self.main_window else None
        return getattr(cm, "batch_default_aspect_ratio", None) or "9:16"

    def on_aspect_changed(self):
        if not self.current_project:
            return
        self.current_project["aspect_ratio"] = self.cb_aspect.currentData() or "9:16"
        self.model.save_project(self.current_project)
        row = self.list_projects.currentRow()
        it = self.list_projects.item(row) if row >= 0 else None
        if it is not None:
            it.setText(self._project_list_label(self.current_project))

    def on_points_limit_changed(self, value: int):
        """Lightweight in-memory update when points spinbox value changes; zero table rebuild or disk I/O."""
        if not self.current_project:
            return
        self.current_project["points_cost"] = int(value)

    def on_points_editing_finished(self):
        """Persist points_cost once user finishes editing the spinbox."""
        if not self.current_project:
            return
        self.current_project["points_cost"] = self.sb_points.value()
        self.model.save_project(self.current_project)

    def _sync_ui_to_current_project(self):
        """Sync all top-bar settings and table row presets/prompts into self.current_project."""
        if not self.current_project:
            return
        new_dur = int(self.cb_duration.currentText().replace("秒", ""))
        self.current_project["duration"] = new_dur
        self.current_project["points_cost"] = self.sb_points.value()
        self.current_project["template_id"] = self.cb_template.currentData() or ""
        self.current_project["aspect_ratio"] = self.cb_aspect.currentData() or "9:16"

        images = self.current_project.get("images", [])
        for i, img in enumerate(images):
            img["duration"] = new_dur
            if i < self.table.rowCount():
                preset_item = self.table.item(i, 4)
                if preset_item is not None:
                    img["template_id"] = preset_item.data(Qt.ItemDataRole.UserRole) or ""
                prompt_item = self.table.item(i, 5)
                if prompt_item is not None:
                    img["prompt"] = prompt_item.text()

    def save_current_project(self):
        if not self.current_project: return
        self._sync_ui_to_current_project()
        self.model.save_project(self.current_project)
        self.render_table()

    def save_all_settings_manual(self):
        """Explicit 'Save Settings' button handler with visual feedback."""
        if not self.current_project:
            QMessageBox.warning(self, "提示", "请先在左侧选择或导入一个批量任务。")
            return
        self._sync_ui_to_current_project()
        self.model.save_project(self.current_project)
        custom_count = sum(1 for img in self.current_project.get("images", []) if img.get("template_id"))
        total_count = len(self.current_project.get("images", []))
        QMessageBox.information(
            self,
            "保存成功",
            f"✅ 当前批量任务设置已成功保存！\n\n"
            f"• 总图片任务数：{total_count} 条\n"
            f"• 单独指定预设：{custom_count} 条\n"
            f"• 跟随整体预设：{total_count - custom_count} 条"
        )

    def export_batch_json(self):
        if not self.current_project: return
        self._sync_ui_to_current_project()
        self.model.save_project(self.current_project)
        
        images = self.current_project["images"]
        if not images:
            QMessageBox.warning(self, "提示", "没有可导出的任务。")
            return
            
        # Format tasks for batch dialog
        all_tasks = []
        skipped_count = 0
        
        cm = getattr(self.main_window, "config_manager", None) if self.main_window else None
        if cm:
            cm.load()
        default_mode = getattr(cm, "default_generation_mode", "VIDEO_FRAMES") if cm else "VIDEO_FRAMES"
        default_model = getattr(cm, "default_video_model", "omni_1_1_flash") if cm else "omni_1_1_flash"
        batch_aspect = self._get_project_aspect()
        task_interval = getattr(cm, "task_interval", 5) if cm else 5
        
        for idx, img in enumerate(images):
            image_path = Path(img.get("path", ""))
            image_stem = image_path.stem
            download_name = f"{image_stem}.mp4"
            
            # Just create a path in workspace so it's valid for JSON payload parsing by UI.js
            ws = Path(self.main_window.workspace_dir) if hasattr(self.main_window, 'workspace_dir') else Path('.')
            project_name = self.current_project.get("name", "批量任务")
            download_path_obj = ws / project_name / download_name
            
            # Check if video already exists on the actual disk location
            base_path = self.main_window.storage_manager.get_base_path() if hasattr(self.main_window, 'storage_manager') else None
            if not base_path:
                base_path = Path.home() / "Downloads"
            check_path = Path(base_path) / "Flow" / project_name / f"{image_stem}.mp4"
            
            if check_path.exists() and check_path.stat().st_size > 0:
                skipped_count += 1
                continue
            
            task_dict = {
                "_original_index": idx,
                "index": idx + 1,
                "prompt": img.get("prompt", ""),
                "image_name": image_path.name,
                "local_image_path": str(image_path.resolve()),
                "duration": img.get("duration", 8),
                "mode": default_mode,
                "model": default_model,
                "interval": task_interval,
                "aspect_ratio": batch_aspect,
                "download_path": str(download_path_obj.resolve())
            }
            all_tasks.append(task_dict)
            
        if not all_tasks:
            if skipped_count > 0:
                QMessageBox.information(self, "提示", f"该任务中的 {skipped_count} 个视频已全部生成成功，无需再次分配！")
            else:
                QMessageBox.warning(self, "提示", "没有可导出的任务。")
            return
            
        # Partition tasks using First Fit Decreasing (FFD)
        batches = []
        max_batch_points = self.sb_points.value()
        
        class MockCM:
            def __init__(self, pts, real_cm=None, aspect_override="9:16"):
                self._real_cm = real_cm
                self.max_batch_points = pts
                self.default_generation_mode = getattr(real_cm, "default_generation_mode", "VIDEO_FRAMES") if real_cm else "VIDEO_FRAMES"
                self.default_aspect_ratio = aspect_override
                self.batch_default_aspect_ratio = aspect_override
                self.default_video_model = getattr(real_cm, "default_video_model", "omni_1_1_flash") if real_cm else "omni_1_1_flash"
                self.task_interval = getattr(real_cm, "task_interval", 5) if real_cm else 5
            def get_points_for_duration(self, dur):
                if self._real_cm and hasattr(self._real_cm, "get_points_for_duration"):
                    return self._real_cm.get_points_for_duration(dur)
                points_map = {10: 15, 8: 12, 6: 10, 4: 7}
                return points_map.get(dur, 10)
                
        cm_mock = MockCM(max_batch_points, cm, batch_aspect)
        
        def get_task_points(task):
            return cm_mock.get_points_for_duration(task.get("duration", 4))

        all_tasks.sort(key=get_task_points, reverse=True)

        for task in all_tasks:
            pts = get_task_points(task)
            placed = False
            for batch in batches:
                current_batch_pts = sum(get_task_points(t) for t in batch)
                if current_batch_pts + pts <= max_batch_points:
                    batch.append(task)
                    placed = True
                    break
            if not placed:
                batches.append([task])
                
        # Sort back to original chronological index for clear display
        for batch in batches:
            batch.sort(key=lambda t: t["_original_index"])
            
        # Open the standard batch dialog
        dialog = BatchExportDialog(self, batches, cm_mock, skipped_count=skipped_count)
        # Override the dialog title/label to reflect the current batch points
        dialog.setWindowTitle(f"分批生成与多浏览器调度 (最高{max_batch_points}积分/批)")
        dialog.exec()

    def change_row_color(self, row, copied=True):
        from services.theme_manager import ThemeManager
        if copied:
            bg_color, text_color = ThemeManager.get_copied_row_colors()
        
        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item:
                if copied:
                    item.setBackground(bg_color)
                    item.setForeground(text_color)
                else:
                    item.setData(Qt.ItemDataRole.BackgroundRole, None)
                    item.setData(Qt.ItemDataRole.ForegroundRole, None)

    def _get_thumbnail_pixmap(self, path_str: str, max_w: int = 104, max_h: int = 66):
        """Load and cache a smooth thumbnail QPixmap for the given image path."""
        if not path_str or not os.path.exists(path_str):
            return None
        try:
            mtime = os.path.getmtime(path_str)
            cache_key = (path_str, mtime, max_w, max_h)
            if cache_key in self._thumb_cache:
                return self._thumb_cache[cache_key]

            pix = QPixmap(path_str)
            if pix.isNull():
                # Fallback via Pillow for special WebP/EXIF formats
                from PIL import Image, ImageOps
                from PyQt6.QtGui import QImage
                with Image.open(path_str) as pil_img:
                    pil_img = ImageOps.exif_transpose(pil_img)
                    pil_img = pil_img.convert("RGBA")
                    data = pil_img.tobytes("raw", "RGBA")
                    qimg = QImage(data, pil_img.width, pil_img.height, QImage.Format.Format_RGBA8888).copy()
                    pix = QPixmap.fromImage(qimg)

            if not pix.isNull():
                thumb = pix.scaled(
                    max_w, max_h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                if len(self._thumb_cache) > 500:
                    self._thumb_cache.clear()
                self._thumb_cache[cache_key] = thumb
                return thumb
        except Exception as e:
            logger.debug(f"Failed to load thumbnail for {path_str}: {e}")
        return None

    def on_table_cell_double_clicked(self, row: int, col: int):
        """Double-clicking image preview or image name opens large image preview."""
        if not self.current_project:
            return
        images = self.current_project.get("images", [])
        if 0 <= row < len(images) and col in (1, 2):
            self._show_large_image_preview(images[row].get("path", ""), row + 1)

    def _show_large_image_preview(self, path_str: str, index_num: int = 1):
        """Pop up a high-resolution preview dialog for the selected image."""
        if not path_str or not os.path.exists(path_str):
            QMessageBox.warning(self, "文件不存在", f"找不到图片文件：\n{path_str}")
            return

        dlg = QDialog(self)
        img_name = os.path.basename(path_str)
        dlg.setWindowTitle(f"🖼️ 图片预览 - #{index_num} {img_name}")
        dlg.resize(760, 620)
        dlg.setStyleSheet("""
            QDialog { background-color: #FAF6F0; }
            QLabel { color: #5D4037; font-size: 13px; font-weight: bold; }
            QPushButton { background-color: #E0A96D; color: white; border: none; border-radius: 4px; padding: 6px 14px; font-weight: bold; }
            QPushButton:hover { background-color: #D2904C; }
        """)
        v_layout = QVBoxLayout(dlg)

        pix = QPixmap(path_str)
        info_text = f"📄 文件名: {img_name}"
        if not pix.isNull():
            info_text += f"    📐 分辨率: {pix.width()} × {pix.height()}"
        info_lbl = QLabel(info_text)
        v_layout.addWidget(info_lbl)

        img_lbl = QLabel()
        img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_lbl.setStyleSheet("background-color: #263238; border: 1px solid #D7CCC8; border-radius: 6px; padding: 8px;")
        if not pix.isNull():
            scaled_pix = pix.scaled(
                720, 490,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            img_lbl.setPixmap(scaled_pix)
        else:
            img_lbl.setText("⚠️ 无法预览该图片格式")
            img_lbl.setStyleSheet("color: white; background-color: #263238; border-radius: 6px; padding: 20px;")
        v_layout.addWidget(img_lbl, stretch=1)

        btn_row = QHBoxLayout()
        btn_open_sys = QPushButton("🖼️ 用系统看图打开")
        btn_open_sys.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(path_str)))
        btn_open_dir = QPushButton("📂 打开所在文件夹")
        btn_open_dir.setStyleSheet("background-color: #8D6E63; color: white;")
        btn_open_dir.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path_str).parent))))
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(dlg.accept)

        btn_row.addWidget(btn_open_sys)
        btn_row.addWidget(btn_open_dir)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        v_layout.addLayout(btn_row)

        dlg.exec()

    def render_table(self):
        if not self.current_project: return
        from views.table_delegates import bulk_table_update
        with bulk_table_update(self.table):
            self._render_table_impl()

    def _render_table_impl(self):
        if not self.current_project: return
        self._is_rendering_table = True
        try:
            images = self.current_project["images"]
            self.table.setRowCount(len(images))
            
            project_name = self.current_project.get("name", "批量任务")
            # Get the actual base storage path where Chrome downloads（只取一次）
            base_path = self.main_window.storage_manager.get_base_path() if hasattr(self.main_window, 'storage_manager') else None
            if not base_path:
                base_path = Path.home() / "Downloads"
            self.table.setUpdatesEnabled(False)
            
            for i, img in enumerate(images):
                raw_path = img.get("path", "")
                image_path = Path(raw_path)
                name = image_path.name
                dur = f"{img.get('duration', 8)}秒"
                prompt = img.get("prompt", "")
                row_tpl_id = img.get("template_id", "")
                
                # Col 0: 序号
                idx_item = QTableWidgetItem(str(i + 1))
                idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                idx_item.setFlags(idx_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(i, 0, idx_item)

                # Col 1: 图片预览（由 ThumbnailDelegate 按需绘制，单击查看大图）
                thumb_item = QTableWidgetItem("")
                thumb_item.setData(Qt.ItemDataRole.UserRole, raw_path if os.path.exists(raw_path) else "")
                thumb_item.setToolTip(f"🔍 点击查看大图预览\n文件: {name}\n路径: {raw_path}")
                thumb_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(i, 1, thumb_item)

                # Col 2: 图片名称
                name_item = QTableWidgetItem(name)
                name_item.setToolTip(f"双击查看大图\n完整路径: {raw_path}")
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(i, 2, name_item)

                # Col 3: 时长
                dur_item = QTableWidgetItem(dur)
                dur_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                dur_item.setFlags(dur_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(i, 3, dur_item)

                # Col 4: 单独预设（平时只显示文字，单击时才弹出下拉框，由 ComboDelegate 处理）
                found_t = self._find_batch_template_by_id(row_tpl_id) if row_tpl_id else None
                if not found_t and (row_tpl_id or img.get("template_name")):
                    matched_t = self._find_batch_template(img.get("template_name") or row_tpl_id)
                    if matched_t:
                        row_tpl_id = matched_t.get("id", "")
                        img["template_id"] = row_tpl_id
                        found_t = matched_t
                preset_item = QTableWidgetItem("")
                preset_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable)
                self._set_preset_item(preset_item, found_t)
                self.table.setItem(i, 4, preset_item)

                # Col 5: 提示词 (Editable)
                prompt_item = QTableWidgetItem(prompt)
                prompt_item.setToolTip("双击可直接手动编辑此任务的提示词，修改后自动保存")
                self.table.setItem(i, 5, prompt_item)
                
                # Col 6: 操作（复制提示词 / 复制路径 / 导出JSON 三个按钮由 TableButtonDelegate 绘制）
                op_item = QTableWidgetItem("")
                op_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(i, 6, op_item)
                # Chrome 下载目录（已在循环外计算一次）
                    
                check_path = Path(base_path) / "Flow" / project_name / f"{image_path.stem}.mp4"
                
                if check_path.exists() and check_path.stat().st_size > 0:
                    self.change_row_color(i, copied=True)
                else:
                    self.change_row_color(i, copied=False)
        finally:
            self.table.setUpdatesEnabled(True)
            self._is_rendering_table = False

    def export_single_json(self, index):
        self._sync_ui_to_current_project()
        self.model.save_project(self.current_project)
        img = self.current_project["images"][index]
        image_path = Path(img.get("path", ""))
        ws = Path(self.main_window.workspace_dir) if hasattr(self.main_window, 'workspace_dir') else Path('.')
        project_name = self.current_project.get("name", "批量任务")
        download_path = str((ws / project_name / f"{image_path.stem}.mp4").resolve())
        cm = getattr(self.main_window, "config_manager", None) if self.main_window else None
        if cm:
            cm.load()
        default_mode = getattr(cm, "default_generation_mode", "VIDEO_FRAMES") if cm else "VIDEO_FRAMES"
        default_model = getattr(cm, "default_video_model", "omni_1_1_flash") if cm else "omni_1_1_flash"
        batch_aspect = self._get_project_aspect()
        task_interval = getattr(cm, "task_interval", 5) if cm else 5
        data = [{
            "prompt": img.get("prompt", ""),
            "image": image_path.name,
            "duration": img.get("duration", 8),
            "mode": default_mode,
            "model": default_model,
            "interval": task_interval,
            "aspect_ratio": batch_aspect,
            "download_path": download_path
        }]
        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        QGuiApplication.clipboard().setText(json_str)
        QMessageBox.information(self, "复制成功", "单条 JSON 已复制到剪贴板！")
        
    def export_all_json(self):
        if not self.current_project: return
        self._sync_ui_to_current_project()
        self.model.save_project(self.current_project)
        images = self.current_project["images"]
        if not images: return
        
        ws = Path(self.main_window.workspace_dir) if hasattr(self.main_window, 'workspace_dir') else Path('.')
        project_name = self.current_project.get("name", "批量任务")
        cm = getattr(self.main_window, "config_manager", None) if self.main_window else None
        if cm:
            cm.load()
        default_mode = getattr(cm, "default_generation_mode", "VIDEO_FRAMES") if cm else "VIDEO_FRAMES"
        default_model = getattr(cm, "default_video_model", "omni_1_1_flash") if cm else "omni_1_1_flash"
        batch_aspect = self._get_project_aspect()
        task_interval = getattr(cm, "task_interval", 5) if cm else 5
        out = []
        for i in images:
            image_path = Path(i.get("path", ""))
            download_path = str((ws / project_name / f"{image_path.stem}.mp4").resolve())
            out.append({
                "prompt": i.get("prompt", ""), 
                "image": image_path.name, 
                "duration": i.get("duration", 8), 
                "mode": default_mode,
                "model": default_model,
                "interval": task_interval,
                "aspect_ratio": batch_aspect,
                "download_path": download_path
            })
            
        QGuiApplication.clipboard().setText(json.dumps(out, ensure_ascii=False, indent=2))
        QMessageBox.information(self, "复制成功", "已复制全部任务 JSON！")
