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
