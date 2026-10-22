# -*- coding: utf-8 -*-
import os
import json
import logging
from pathlib import Path
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QTextEdit, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QComboBox, QSpinBox, QFileDialog, QMessageBox,
                             QSplitter, QListWidget, QFrame, QInputDialog, QDialog)
from PyQt6.QtCore import Qt, pyqtSlot, QUrl
from PyQt6.QtGui import QGuiApplication, QPixmap, QDesktopServices

logger = logging.getLogger(__name__)
from models.batch_model import BatchProjectModel
from views.project_detail_widget import BatchExportDialog

class NoWheelComboBox(QComboBox):
    """QComboBox that ignores mouse wheel events unless its popup view is open, preventing accidental changes while scrolling the table."""
    def wheelEvent(self, event):
        if self.view() and self.view().isVisible():
            super().wheelEvent(event)
        else:
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
        self.cb_duration.currentIndexChanged.connect(self.save_current_project)
        config_layout.addWidget(self.cb_duration)
        
        config_layout.addWidget(QLabel("尺寸比例:"))
        self.cb_aspect = NoWheelComboBox()
        self.cb_aspect.addItems(["16:9", "9:16"])
        self.cb_aspect.setCurrentText("16:9")
        self.cb_aspect.currentIndexChanged.connect(self.save_current_project)
        config_layout.addWidget(self.cb_aspect)
        
        config_layout.addWidget(QLabel("单批次生成积分上限:"))
        self.sb_points = QSpinBox()
        self.sb_points.setRange(1, 1000)
        self.sb_points.setValue(50)
        self.sb_points.setToolTip("每个导出的JSON任务块最高消耗积分")
        self.sb_points.valueChanged.connect(self.save_current_project)
        config_layout.addWidget(self.sb_points)
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

        lbl_cat_hint = QLabel("💡 选择分类后点击「随机发放」，将按分类内预设顺序依次循环铺满所有单条任务")
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
        self.table.itemChanged.connect(self.on_table_item_changed)
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
        """Look up batch template content by template ID."""
        if not tpl_id:
            return ""
        for t in self._get_batch_templates_list():
            if t.get("id") == tpl_id:
                return t.get("content", "")
        return ""

    def refresh_project_list(self):
        self.list_projects.clear()
        for p in self.model.projects:
            self.list_projects.addItem(f"{p['name']} ({len(p['images'])}图)")
            
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
        self.cb_aspect.blockSignals(True)
        
        self.cb_duration.setCurrentText(f"{self.current_project.get('duration', 8)}秒")
        self.cb_aspect.setCurrentText(self.current_project.get('aspect_ratio', "16:9"))
        self.sb_points.setValue(self.current_project.get('points_cost', 50))
        
        tpl_id = self.current_project.get("template_id", "")
        idx = self.cb_template.findData(tpl_id)
        if idx >= 0:
            self.cb_template.setCurrentIndex(idx)
        else:
            self.cb_template.setCurrentIndex(0)
            
        self.cb_duration.blockSignals(False)
        self.sb_points.blockSignals(False)
        self.cb_template.blockSignals(False)
        self.cb_aspect.blockSignals(False)
        
        self.render_table()

    def on_template_changed(self):
        if not self.current_project: return
        tpl_id = self.cb_template.currentData()
        self.current_project["template_id"] = tpl_id
        content = self._get_template_content_by_id(tpl_id)
                        
        for img in self.current_project["images"]:
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

    def on_row_template_changed(self, row: int, combo: QComboBox):
        """Handle changing a single row's individual template preset."""
        if self._is_rendering_table or not self.current_project:
            return
        images = self.current_project.get("images", [])
        if row < 0 or row >= len(images):
            return

        row_tpl_id = combo.currentData() or ""
        images[row]["template_id"] = row_tpl_id
        if row_tpl_id:
            new_prompt = self._get_template_content_by_id(row_tpl_id)
        else:
            global_tpl_id = self.cb_template.currentData() or self.current_project.get("template_id", "")
            new_prompt = self._get_template_content_by_id(global_tpl_id)

        images[row]["prompt"] = new_prompt
        self._apply_row_combo_style(combo, bool(row_tpl_id))

        # Update prompt cell in table without rebuilding all widgets
        self._is_rendering_table = True
        prompt_item = self.table.item(row, 5)
        if prompt_item:
            prompt_item.setText(new_prompt)
        else:
            self.table.setItem(row, 5, QTableWidgetItem(new_prompt))
        self._is_rendering_table = False

        self.model.save_project(self.current_project)

    def _apply_row_combo_style(self, combo: QComboBox, has_custom: bool):
        """Visually highlight rows that have a custom individual preset."""
        if has_custom:
            combo.setStyleSheet(
                "QComboBox { background-color: #FFF3E0; color: #E65100; border: 1.5px solid #FFB74D; border-radius: 4px; padding: 3px 6px; font-weight: bold; font-size: 12px; }"
            )
        else:
            combo.setStyleSheet(
                "QComboBox { background-color: #FAFAFA; color: #5D4037; border: 1px solid #D7CCC8; border-radius: 4px; padding: 3px 6px; font-size: 12px; }"
            )

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

    def _sync_ui_to_current_project(self):
        """Sync all top-bar settings and table row presets/prompts into self.current_project."""
        if not self.current_project:
            return
        new_dur = int(self.cb_duration.currentText().replace("秒", ""))
        self.current_project["duration"] = new_dur
        self.current_project["points_cost"] = self.sb_points.value()
        self.current_project["aspect_ratio"] = self.cb_aspect.currentText()
        self.current_project["template_id"] = self.cb_template.currentData() or ""

        images = self.current_project.get("images", [])
        for i, img in enumerate(images):
            img["duration"] = new_dur
            if i < self.table.rowCount():
                w_preset = self.table.cellWidget(i, 4)
                if w_preset:
                    cb = w_preset.findChild(QComboBox)
                    if cb is not None:
                        img["template_id"] = cb.currentData() or ""
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
        default_mode = getattr(cm, "default_generation_mode", "VIDEO_FRAMES") if cm else "VIDEO_FRAMES"
        default_model = getattr(cm, "default_video_model", "omni_1_1_flash") if cm else "omni_1_1_flash"
        default_aspect = getattr(cm, "default_aspect_ratio", "9:16") if cm else "9:16"
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
                "aspect_ratio": self.current_project.get("aspect_ratio", default_aspect),
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
            def __init__(self, pts, real_cm=None):
                self.max_batch_points = pts
                self.default_generation_mode = getattr(real_cm, "default_generation_mode", "VIDEO_FRAMES") if real_cm else "VIDEO_FRAMES"
                self.default_aspect_ratio = getattr(real_cm, "default_aspect_ratio", "9:16") if real_cm else "9:16"
                self.default_video_model = getattr(real_cm, "default_video_model", "omni_1_1_flash") if real_cm else "omni_1_1_flash"
                self.task_interval = getattr(real_cm, "task_interval", 5) if real_cm else 5
            def get_points_for_duration(self, dur):
                points_map = {10: 15, 8: 12, 6: 10, 4: 7}
                return points_map.get(dur, 10)
                
        cm_mock = MockCM(max_batch_points, cm)
        
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
        from PyQt6.QtGui import QColor
        if copied:
            bg_color = QColor("#D4EDDA") # Light green
            text_color = QColor("#155724") # Dark green
        
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
        self._is_rendering_table = True
        try:
            images = self.current_project["images"]
            self.table.setRowCount(len(images))
            
            project_name = self.current_project.get("name", "批量任务")
            batch_templates = self._get_batch_templates_list()
            
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

                # Col 1: 图片预览 (Thumbnail + Click to enlarge)
                self.table.setItem(i, 1, QTableWidgetItem(""))
                w_thumb = QWidget()
                w_thumb.setStyleSheet("background: transparent;")
                l_thumb = QHBoxLayout(w_thumb)
                l_thumb.setContentsMargins(4, 4, 4, 4)
                l_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)

                lbl_thumb = QLabel()
                lbl_thumb.setFixedSize(106, 68)
                lbl_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl_thumb.setCursor(Qt.CursorShape.PointingHandCursor)
                lbl_thumb.setToolTip(f"🔍 点击查看大图预览\n文件: {name}\n路径: {raw_path}")

                thumb_pix = self._get_thumbnail_pixmap(raw_path, 102, 64)
                if thumb_pix:
                    lbl_thumb.setPixmap(thumb_pix)
                    lbl_thumb.setStyleSheet(
                        "QLabel { background-color: #FFFDF9; border: 1px solid #D7CCC8; border-radius: 4px; }"
                        "QLabel:hover { border: 2px solid #E0A96D; }"
                    )
                else:
                    lbl_thumb.setText("无预览" if os.path.exists(raw_path) else "文件缺失")
                    lbl_thumb.setStyleSheet(
                        "QLabel { background-color: #EFEBE9; color: #8D6E63; font-size: 11px; border: 1px dashed #BCAAA4; border-radius: 4px; }"
                    )

                lbl_thumb.mousePressEvent = lambda event, p=raw_path, idx_num=i+1: (
                    self._show_large_image_preview(p, idx_num)
                    if event.button() == Qt.MouseButton.LeftButton else None
                )
                l_thumb.addWidget(lbl_thumb)
                self.table.setCellWidget(i, 1, w_thumb)

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

                # Col 4: 单独预设 (Per-row template dropdown)
                self.table.setItem(i, 4, QTableWidgetItem(""))
                w_preset = QWidget()
                w_preset.setStyleSheet("background: transparent;")
                l_preset = QHBoxLayout(w_preset)
                l_preset.setContentsMargins(4, 4, 4, 4)

                cb_row_tpl = NoWheelComboBox()
                cb_row_tpl.setToolTip("为该单条任务指定独立的描述词预设（默认跟随整体预设）")
                cb_row_tpl.addItem("🔗 跟随整体预设", "")
                for t in batch_templates:
                    cat = (t.get("category") or "").strip()
                    t_label = f"📌 [{cat}] {t.get('name', '未命名')}" if cat else f"📌 {t.get('name', '未命名')}"
                    cb_row_tpl.addItem(t_label, t.get("id", ""))

                found_idx = cb_row_tpl.findData(row_tpl_id) if row_tpl_id else 0
                if found_idx >= 0:
                    cb_row_tpl.setCurrentIndex(found_idx)
                else:
                    cb_row_tpl.setCurrentIndex(0)

                self._apply_row_combo_style(cb_row_tpl, bool(row_tpl_id and found_idx > 0))
                cb_row_tpl.currentIndexChanged.connect(
                    lambda _, r=i, combo=cb_row_tpl: self.on_row_template_changed(r, combo)
                )
                l_preset.addWidget(cb_row_tpl)
                self.table.setCellWidget(i, 4, w_preset)

                # Col 5: 提示词 (Editable)
                prompt_item = QTableWidgetItem(prompt)
                prompt_item.setToolTip("双击可直接手动编辑此任务的提示词，修改后自动保存")
                self.table.setItem(i, 5, prompt_item)
                
                # Col 6: 操作
                self.table.setItem(i, 6, QTableWidgetItem(""))
                w_action = QWidget()
                l_action = QHBoxLayout(w_action)
                l_action.setContentsMargins(2, 2, 2, 2)
                
                btn_copy_prompt = QPushButton("复制提示词")
                btn_copy_prompt.clicked.connect(
                    lambda _, idx=i: QGuiApplication.clipboard().setText(
                        self.current_project["images"][idx].get("prompt", "")
                    )
                )
                
                btn_copy_path = QPushButton("复制路径")
                btn_copy_path.clicked.connect(lambda _, p=raw_path: QGuiApplication.clipboard().setText(p))
                
                btn_export = QPushButton("导出JSON")
                btn_export.clicked.connect(lambda _, idx=i: self.export_single_json(idx))
                
                l_action.addWidget(btn_copy_prompt)
                l_action.addWidget(btn_copy_path)
                l_action.addWidget(btn_export)
                self.table.setCellWidget(i, 6, w_action)
                # Get the actual base storage path where Chrome downloads
                base_path = self.main_window.storage_manager.get_base_path() if hasattr(self.main_window, 'storage_manager') else None
                if not base_path:
                    base_path = Path.home() / "Downloads"
                    
                check_path = Path(base_path) / "Flow" / project_name / f"{image_path.stem}.mp4"
                
                if check_path.exists() and check_path.stat().st_size > 0:
                    self.change_row_color(i, copied=True)
                else:
                    self.change_row_color(i, copied=False)
        finally:
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
        default_mode = getattr(cm, "default_generation_mode", "VIDEO_FRAMES") if cm else "VIDEO_FRAMES"
        default_model = getattr(cm, "default_video_model", "omni_1_1_flash") if cm else "omni_1_1_flash"
        default_aspect = getattr(cm, "default_aspect_ratio", "9:16") if cm else "9:16"
        task_interval = getattr(cm, "task_interval", 5) if cm else 5
        data = [{
            "prompt": img.get("prompt", ""),
            "image": image_path.name,
            "duration": img.get("duration", 8),
            "mode": default_mode,
            "model": default_model,
            "interval": task_interval,
            "aspect_ratio": self.current_project.get("aspect_ratio", default_aspect),
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
        default_mode = getattr(cm, "default_generation_mode", "VIDEO_FRAMES") if cm else "VIDEO_FRAMES"
        default_model = getattr(cm, "default_video_model", "omni_1_1_flash") if cm else "omni_1_1_flash"
        default_aspect = getattr(cm, "default_aspect_ratio", "9:16") if cm else "9:16"
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
                "aspect_ratio": self.current_project.get("aspect_ratio", default_aspect),
                "download_path": download_path
            })
            
        QGuiApplication.clipboard().setText(json.dumps(out, ensure_ascii=False, indent=2))
        QMessageBox.information(self, "复制成功", "已复制全部任务 JSON！")
