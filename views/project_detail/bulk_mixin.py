# -*- coding: utf-8 -*-
"""多选批量设置、复制为表格、重置统一设置。

由 ProjectDetailWidget 通过多重继承组合使用，方法内的 self 即 ProjectDetailWidget 实例。"""
from views.project_detail.common import *  # noqa: F401,F403
from views.project_detail.common import logger  # noqa: F401


class BulkEditMixin:
    def _selected_segment_rows(self):
        """Returns sorted list of selected (visible) segment row indices."""
        sm = self.table_segments.selectionModel()
        if not sm:
            return []
        rows = sorted({idx.row() for idx in sm.selectedRows()})
        if not rows:
            rows = sorted({idx.row() for idx in sm.selectedIndexes()})
        total = len(self.project_model.spanish_segments) if self.project_model else 0
        return [r for r in rows if 0 <= r < total and not self.table_segments.isRowHidden(r)]

    def open_bulk_edit_dialog(self):
        """直接打开「🖼️ 多选与图片预设可视化管理」独立大窗：
        - 直观多排平铺展示当前任务所有断句的图片（支持 Ctrl+滚轮缩放图片）
        - 支持 Ctrl / Shift / 鼠标拖拽橡皮筋框选多张图片，并在上方选项卡直接指定各种预设
        - 上方自带可折叠/展开的「任务资源图库」，多选断句后点击任意资源图即刻批量更换图片
        - 支持在多选界面内直接切换任务（无需关闭再重新打开）
        """
        if not self.project_model:
            QMessageBox.information(self, "提示", "请先打开一个项目。")
            return
        rows = self._selected_segment_rows()
        from views.segment_multi_select_dialog import SegmentVisualBatchManagerDialog
        dlg = SegmentVisualBatchManagerDialog(
            detail_widget=self,
            initial_selected_rows=rows,
            parent=self,
        )
        dlg.exec()
        # 关闭后确保当前表格与右侧面板刷新到最新状态
        if self.project_model:
            self.populate_segments_table()
            cur = self.table_segments.currentItem()
            if cur is not None:
                self.on_table_selection_changed(cur, None)

    def open_table_paste_import_dialog(self):
        """针对当前选中的单个项目任务，从剪贴板表格导入「断行后的文案」与「图片名称」。"""
        if not self.project_model or not self.project_path:
            QMessageBox.information(
                self,
                "请先选中任务",
                "该功能仅支持针对单个任务导入断行文案与图片名称。\n\n请先在左侧项目列表中点击选中一个任务！",
            )
            return

        from views.table_segment_import_dialog import TableSegmentImportDialog

        old_count = len(self.project_model.spanish_segments or [])
        dlg = TableSegmentImportDialog(
            project_model=self.project_model,
            project_path=self.project_path,
            config_manager=self.config_manager,
            template_manager=self.template_manager,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_segments = dlg.build_new_segments()
        if not new_segments:
            return

        # 严格用本次导入的 N 条有效分句替换原分句列表（例如原 15 条、导入 10 条 -> 精确变为 10 条，绝不残留多余空任务）
        self.project_model.spanish_segments = new_segments
        if not (self.project_model.spanish_text or "").strip():
            self.project_model.spanish_text = "\n".join(s["text"] for s in new_segments)
            if hasattr(self, "txt_spanish"):
                self.txt_spanish.setPlainText(self.project_model.spanish_text)

        if hasattr(self, "copied_rows"):
            self.copied_rows.clear()
        if hasattr(self, "dispatched_indices"):
            self.dispatched_indices.clear()
        self.failed_skip_indices = set()
        self.segment_retry_counts = {}
        self.current_prop_row = -1
        self._compare_dirty = True

        self.project_model.save()
        self.populate_segments_table()

        if self.table_segments.rowCount() > 0:
            self.table_segments.selectRow(0)
            first_item = self.table_segments.item(0, 0)
            if first_item is not None:
                self.table_segments.setCurrentItem(first_item)
        else:
            self.on_table_selection_changed(None, None)

        # 刷新左侧项目列表的视频完整性状态颜色
        main_win = self.window()
        if main_win is not None and hasattr(main_win, "storage_manager") and hasattr(main_win, "_start_project_status_scan"):
            try:
                base_path = main_win.storage_manager.get_base_path()
                if base_path:
                    main_win._start_project_status_scan(main_win.storage_manager.list_projects(), base_path)
            except Exception:
                pass

        QMessageBox.information(
            self,
            "表格导入成功",
            f"✅ 已成功为任务「{self.project_model.project_id}」导入 {len(new_segments)} 个分句小任务（原 {old_count} 个）！\n\n"
            "• 时长已根据每句文案字符数自动计算；\n"
            "• 提示词继续沿用当前模板与运镜预设；\n"
            "• 多余的旧分句已自动清理，无空任务残留。",
        )

    def copy_segments_as_table(self):
        """把当前项目全部分句按 序号 / 文案 / 字数 / 时长 / 提示词 5 列复制为表格（TSV）格式。"""
        rows_cnt = self.table_segments.rowCount()
        if not self.project_model or rows_cnt == 0:
            QMessageBox.information(self, "提示", "当前项目没有分句可复制。")
            return

        def cell(r, c):
            it = self.table_segments.item(r, c)
            return it.text().strip() if it else ""

        def esc(v):
            v = str(v).replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
            if "\n" in v or '"' in v:
                v = '"' + v.replace('"', '""') + '"'
            return v

        lines = ["\t".join(["序号", "文案", "字数", "时长", "提示词"])]
        for r in range(rows_cnt):
            dur = cell(r, 3)
            if dur.endswith("s") and dur[:-1].isdigit():
                dur = dur[:-1]
            lines.append("\t".join(esc(v) for v in (r + 1, cell(r, 1), cell(r, 2), dur, cell(r, 4))))
        QGuiApplication.clipboard().setText("\n".join(lines) + "\n")
        QMessageBox.information(
            self, "复制成功",
            f"✅ 已复制 {rows_cnt} 句分句（含表头，共 5 列：序号 / 文案 / 字数 / 时长(秒) / 提示词）。\n\n"
            "请直接到 Excel / WPS / 飞书 / 谷歌表格中选中 A1 单元格后粘贴（Ctrl+V）。")

    def reset_all_segments_to_unified(self):
        """Clears all custom template and motion overrides for segments, resetting them to global."""
        if not self.project_model or not self.project_model.spanish_segments:
            return
            
        reply = QMessageBox.question(
            self,
            "确认重置",
            "确定要清空所有片段的独立模板与运镜设置，全员恢复为使用顶部的统一设置吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            for seg in self.project_model.spanish_segments:
                seg["template_id"] = ""
                seg["motion_id"] = ""
                seg["mode_overridden"] = False
            self.project_model.save()
            self.refresh_prop_template_motion_combos()
            self.populate_segments_table()
            QMessageBox.information(self, "成功", "已成功重置所有片段为统一设置！")
