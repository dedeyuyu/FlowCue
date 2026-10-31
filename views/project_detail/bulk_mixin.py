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
        """多选分句后批量设置 首帧图片 / 片段专属模板 / 片段专属运镜 / 生成模式。"""
        if not self.project_model or not self.project_model.spanish_segments:
            QMessageBox.information(self, "提示", "请先打开一个有分句的项目。")
            return
        rows = self._selected_segment_rows()
        if not rows:
            QMessageBox.information(self, "提示", "请先在表格中选择要批量设置的分句。\n\n💡 按住 Ctrl 逐个点选，或按住 Shift 连续选择。")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"🧩 批量设置（已选 {len(rows)} 句）")
        dlg.resize(520, 360)
        lay = QVBoxLayout(dlg)
        preview = "、".join(str(r + 1) for r in rows[:30]) + (f" 等 {len(rows)} 句" if len(rows) > 30 else "")
        lbl = QLabel(f"已选分句序号：{preview}\n勾选需要修改的项目，未勾选的项目保持各分句原有设置不变。")
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: #5D4037; font-weight: bold;")
        lay.addWidget(lbl)

        from PyQt6.QtWidgets import QGridLayout
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)

        def make_row(r, text, combo):
            chk = QCheckBox(text)
            chk.setStyleSheet("font-weight: bold; color: #5D4037;")
            combo.setEnabled(False)
            chk.toggled.connect(combo.setEnabled)
            # 用户直接改下拉框时自动勾选
            combo.activated.connect(lambda _=None, c=chk: c.setChecked(True))
            grid.addWidget(chk, r, 0)
            grid.addWidget(combo, r, 1)
            return chk

        # 1. 首帧图片
        cb_img = NoWheelComboBox()
        cb_img.setMaxVisibleItems(14)
        cb_img.addItem("-- 无首帧 --", "")
        for img in self._list_project_images():
            cb_img.addItem(self.get_small_image_icon(img), img.name, img.name)
        chk_img = make_row(0, "📸 首帧图片", cb_img)

        # 2. 片段专属模板
        global_tpl = self.template_manager.get_template(self.combo_templates.currentData()) if self.template_manager else None
        global_motion = self.template_manager.get_motion(self.combo_motions.currentData()) if self.template_manager else None
        cb_tpl = NoWheelComboBox()
        cb_tpl.setMaxVisibleItems(14)
        cb_tpl.addItem(f"-- 遵循统一设置 ({global_tpl['name'] if global_tpl else '未选择'}) --", "")
        if self.template_manager:
            for t in self.template_manager.templates:
                cb_tpl.addItem(t["name"], t["id"])
        chk_tpl = make_row(1, "📐 片段专属模板", cb_tpl)

        # 3. 片段专属运镜
        cb_motion = NoWheelComboBox()
        cb_motion.setMaxVisibleItems(14)
        cb_motion.addItem(f"-- 遵循统一设置 ({global_motion['name'] if global_motion else '未选择'}) --", "")
        if self.template_manager:
            for m in self.template_manager.motions:
                cb_motion.addItem(m["name"], m["id"])
        chk_motion = make_row(2, "🎥 片段专属运镜", cb_motion)

        # 4. 生成模式
        default_mode_code = getattr(self.config_manager, "default_generation_mode", "VIDEO_FRAMES") if self.config_manager else "VIDEO_FRAMES"
        cb_mode = NoWheelComboBox()
        cb_mode.addItem(f"-- 遵循规则设置 ({'素材模式' if default_mode_code == 'VIDEO_REFERENCES' else '帧模式'}) --", "")
        cb_mode.addItem("帧模式 (First Frame)", "VIDEO_FRAMES")
        cb_mode.addItem("素材模式 (Reference)", "VIDEO_REFERENCES")
        chk_mode = make_row(3, "⚙️ 生成模式", cb_mode)

        # 默认选中第一条已选分句的当前值，方便参考
        first = self.project_model.spanish_segments[rows[0]]
        for cb, val in ((cb_img, first.get("image_name", "")), (cb_tpl, first.get("template_id", "")),
                        (cb_motion, first.get("motion_id", "")),
                        (cb_mode, first.get("mode", "") if first.get("mode_overridden") else "")):
            i = cb.findData(val)
            cb.setCurrentIndex(i if i >= 0 else 0)

        lay.addLayout(grid)

        # 图片预览
        lbl_prev = QLabel("")
        lbl_prev.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_prev.setMinimumHeight(130)
        lbl_prev.setStyleSheet("background-color: #EFEBE9; border: 1px solid #D7CCC8; border-radius: 4px; color: #8D6E63;")
        lay.addWidget(lbl_prev)

        def update_prev():
            name = cb_img.currentData()
            if not name or not self.project_path:
                lbl_prev.clear()
                lbl_prev.setText("无首帧预览")
                return
            pm = QPixmap(str(self.project_path / "downloads" / name))
            if pm.isNull():
                lbl_prev.clear()
                lbl_prev.setText("预览失败")
                return
            lbl_prev.setPixmap(pm.scaled(240, 130, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        cb_img.currentIndexChanged.connect(lambda _=None: update_prev())
        update_prev()

        lay.addStretch()
        btns = QHBoxLayout()
        btns.addStretch()
        btn_ok = QPushButton(f"✅ 应用到 {len(rows)} 句")
        btn_ok.setStyleSheet("background-color: #059669; color: white; font-weight: bold; padding: 6px 16px;")
        btn_cancel = QPushButton("取消")
        btn_ok.clicked.connect(dlg.accept)
        btn_cancel.clicked.connect(dlg.reject)
        btns.addWidget(btn_ok)
        btns.addWidget(btn_cancel)
        lay.addLayout(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if not any(c.isChecked() for c in (chk_img, chk_tpl, chk_motion, chk_mode)):
            QMessageBox.information(self, "提示", "未勾选任何需要修改的项目，未做任何更改。")
            return

        img_val = cb_img.currentData() or ""
        tpl_val = cb_tpl.currentData() or ""
        motion_val = cb_motion.currentData() or ""
        mode_val = cb_mode.currentData() or ""
        segs = self.project_model.spanish_segments
        self.table_segments.setUpdatesEnabled(False)
        try:
            for r in rows:
                seg = segs[r]
                if chk_img.isChecked():
                    seg["image_name"] = img_val
                if chk_tpl.isChecked():
                    seg["template_id"] = tpl_val
                if chk_motion.isChecked():
                    seg["motion_id"] = motion_val
                if chk_mode.isChecked():
                    if mode_val:
                        seg["mode"] = mode_val
                        seg["mode_overridden"] = True
                    else:
                        seg["mode"] = default_mode_code
                        seg["mode_overridden"] = False
                if chk_tpl.isChecked() or chk_motion.isChecked():
                    self.update_segment_row_prompt(r)
                self.refresh_table_row_index_label(r)
        finally:
            self.table_segments.setUpdatesEnabled(True)
        self.project_model.save()

        # 刷新右侧属性面板（显示当前行最新设置）
        cur = self.table_segments.currentItem()
        if cur is not None:
            self.on_table_selection_changed(cur, None)
        changed = [n for c, n in ((chk_img, "首帧图片"), (chk_tpl, "专属模板"), (chk_motion, "专属运镜"), (chk_mode, "生成模式")) if c.isChecked()]
        QToolTip.showText(QCursor.pos(), f"✅ 已为 {len(rows)} 句批量设置：{'、'.join(changed)}", self)

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
