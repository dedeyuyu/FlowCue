# -*- coding: utf-8 -*-
from pathlib import Path
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QTableWidget, QTableWidgetItem, QHeaderView, 
                             QMessageBox, QGroupBox, QAbstractItemView, QProgressBar,
                             QLineEdit, QFileDialog, QWidget)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from services.video_checker import VideoChecker

class VideoCheckDialog(QDialog):
    """Dialog displaying video completeness inspection report for a single project."""
    
    def __init__(self, report, project_model, project_path, base_storage_path=None, parent=None):
        super().__init__(parent)
        self.report = report
        self.project_model = project_model
        self.project_path = project_path
        self.base_storage_path = base_storage_path
        self.custom_search_dir = self.report.get("pre_relocate_dir", "")
        self.init_ui()
        self.populate_report()

    def init_ui(self):
        proj_name = self.report.get("project_name", "")
        self.setWindowTitle(f"🔍 项目视频完整性与归位 - {proj_name}")
        self.resize(850, 620)
        
        self.setStyleSheet("""
            QDialog {
                background-color: #FAF6F0;
                color: #5D4037;
                font-family: "Segoe UI", "PingFang SC", sans-serif;
            }
            QGroupBox {
                font-weight: bold;
                font-size: 13px;
                border: 1px solid #D7CCC8;
                border-radius: 6px;
                margin-top: 6px;
                padding-top: 12px;
                background-color: white;
            }
            QLabel {
                font-size: 13px;
                color: #5D4037;
            }
            QLineEdit {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 5px 8px;
                font-size: 12px;
                color: #5D4037;
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
                padding: 5px;
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
            QPushButton#btn_relocate {
                background-color: #10B981;
                font-size: 13px;
            }
            QPushButton#btn_relocate:hover {
                background-color: #059669;
            }
            QPushButton#btn_browse {
                background-color: #64748B;
                padding: 5px 12px;
                font-size: 12px;
            }
            QPushButton#btn_browse:hover {
                background-color: #475569;
            }
        """)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)
        
        # 1. Double Path Scoping Bar
        group_search_dir = QGroupBox("📁 视频排查路径（精准双路径锁定）")
        dir_layout = QVBoxLayout(group_search_dir)
        dir_layout.setContentsMargins(12, 12, 12, 12)
        dir_layout.setSpacing(6)
        
        # Post-relocate path label
        h1 = QHBoxLayout()
        h1.addWidget(QLabel("<b>归位后路径 (项目内置):</b>"))
        self.lbl_post_dir = QLabel()
        self.lbl_post_dir.setStyleSheet("color: #059669; font-weight: bold;")
        h1.addWidget(self.lbl_post_dir, stretch=1)
        dir_layout.addLayout(h1)
        
        # Pre-relocate path label & custom browse
        h2 = QHBoxLayout()
        h2.addWidget(QLabel("<b>归位前路径 (Flow下载):</b>"))
        self.txt_search_dir = QLineEdit()
        self.txt_search_dir.setReadOnly(True)
        h2.addWidget(self.txt_search_dir, stretch=1)
        
        btn_browse = QPushButton("📁 浏览/自定义目录")
        btn_browse.setObjectName("btn_browse")
        btn_browse.clicked.connect(self.browse_search_directory)
        h2.addWidget(btn_browse)
        dir_layout.addLayout(h2)
        
        main_layout.addWidget(group_search_dir)
        
        # 2. Summary Cards Section
        group_summary = QGroupBox("📊 项目视频完成度概览 (Overview)")
        sum_layout = QVBoxLayout(group_summary)
        sum_layout.setContentsMargins(12, 12, 12, 12)
        sum_layout.setSpacing(8)
        
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(15)
        
        self.lbl_total = QLabel("共 <b>0</b> 句段")
        self.lbl_already = QLabel("✅ 已归位 <b>0</b>")
        self.lbl_already.setStyleSheet("color: #10B981; font-weight: bold;")
        self.lbl_pending = QLabel("⚠️ 待归位 <b>0</b>")
        self.lbl_pending.setStyleSheet("color: #D97706; font-weight: bold;")
        self.lbl_missing = QLabel("❌ 缺失 <b>0</b>")
        self.lbl_missing.setStyleSheet("color: #EF4444; font-weight: bold;")
        self.lbl_rate = QLabel("完成度: <b>0.0%</b>")
        self.lbl_rate.setStyleSheet("color: #8B5CF6; font-size: 14px; font-weight: bold;")
        
        cards_layout.addWidget(self.lbl_total)
        cards_layout.addWidget(self.lbl_already)
        cards_layout.addWidget(self.lbl_pending)
        cards_layout.addWidget(self.lbl_missing)
        cards_layout.addStretch()
        cards_layout.addWidget(self.lbl_rate)
        
        sum_layout.addLayout(cards_layout)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(14)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #D7CCC8;
                border-radius: 7px;
                background-color: #EFEBE9;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #10B981;
                border-radius: 6px;
            }
        """)
        sum_layout.addWidget(self.progress_bar)
        
        main_layout.addWidget(group_summary)
        
        # 3. Detailed Table Section
        self.table_details = QTableWidget()
        self.table_details.setColumnCount(6)
        self.table_details.setHorizontalHeaderLabels([
            "序号", "分句文案", "期待文件名", "视频状态", "文件大小", "存放在"
        ])
        self.table_details.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_details.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_details.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table_details.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        main_layout.addWidget(self.table_details, stretch=1)
        
        # 4. Bottom Action Buttons
        bottom_layout = QHBoxLayout()
        
        self.btn_relocate = QPushButton("📦 一键自动归位视频 (移动到项目内置文件夹)")
        self.btn_relocate.setObjectName("btn_relocate")
        self.btn_relocate.clicked.connect(self.do_relocate)
        bottom_layout.addWidget(self.btn_relocate)
        
        bottom_layout.addStretch()
        
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        bottom_layout.addWidget(btn_close)
        
        main_layout.addLayout(bottom_layout)

    def browse_search_directory(self):
        """Allows user to select a custom folder to scan for pre-relocated video files."""
        current_dir = self.txt_search_dir.text().strip()
        chosen_dir = QFileDialog.getExistingDirectory(self, "选择未归位视频存放/搜索目录", current_dir)
        if chosen_dir:
            self.custom_search_dir = chosen_dir
            self.txt_search_dir.setText(chosen_dir)
            self.refresh_report()

    def refresh_report(self):
        """Re-scans disk for videos."""
        self.report = VideoChecker.check_project_videos(
            self.project_model,
            self.project_path,
            base_storage_path=self.base_storage_path,
            custom_search_dir=self.custom_search_dir
        )
        self.populate_report()

    def populate_report(self):
        self.lbl_post_dir.setText(self.report.get("post_relocate_dir", ""))
        self.txt_search_dir.setText(self.report.get("pre_relocate_dir", self.custom_search_dir))
        
        tot = self.report.get("total_segments", 0)
        already = self.report.get("already_count", 0)
        pending = self.report.get("pending_count", 0)
        missing = self.report.get("missing_count", 0)
        rate = self.report.get("completion_rate", 0.0)
        
        self.lbl_total.setText(f"共 <b>{tot}</b> 个分句")
        self.lbl_already.setText(f"✅ 已归位 <b>{already}</b>")
        self.lbl_pending.setText(f"⚠️ 待归位 <b>{pending}</b>")
        self.lbl_missing.setText(f"❌ 缺失 <b>{missing}</b>")
        self.lbl_rate.setText(f"完成度: <b>{rate:.1f}%</b>")
        self.progress_bar.setValue(int(rate))
        
        # Update relocate button state
        if pending > 0:
            self.btn_relocate.setEnabled(True)
            self.btn_relocate.setText(f"📦 一键自动归位 {pending} 个待处理视频")
            self.btn_relocate.setStyleSheet("background-color: #10B981; color: white; font-weight: bold;")
        else:
            self.btn_relocate.setEnabled(False)
            self.btn_relocate.setText("📦 视频已全部归位")
            self.btn_relocate.setStyleSheet("background-color: #9CA3AF; color: white; font-weight: bold;")

        details = self.report.get("segments_detail", [])
        self.table_details.setRowCount(len(details))
        
        for r, item in enumerate(details):
            # 0. Index
            self.table_details.setItem(r, 0, QTableWidgetItem(str(item["index"])))
            
            # 1. Text
            self.table_details.setItem(r, 1, QTableWidgetItem(item["text"]))
            
            # 2. Download name
            self.table_details.setItem(r, 2, QTableWidgetItem(item["download_name"]))
            
            # 3. Status
            status_str = item.get("status_text", "❌ 缺失")
            status_item = QTableWidgetItem(status_str)
            if item.get("already_in_target"):
                status_item.setForeground(QColor("#10B981"))
                bg = QColor("#D1FAE5")
            elif item["found"]:
                status_item.setForeground(QColor("#D97706"))
                bg = QColor("#FEF3C7")
            else:
                status_item.setForeground(QColor("#EF4444"))
                bg = QColor("#FEE2E2")
                
            status_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table_details.setItem(r, 3, status_item)
            
            # 4. File size
            self.table_details.setItem(r, 4, QTableWidgetItem(item["file_size"]))
            
            # 5. Path
            path_str = str(item["source_path"]) if item.get("source_path") else "未找到文件"
            self.table_details.setItem(r, 5, QTableWidgetItem(path_str))
            
            # Apply row background color
            for c in range(6):
                it = self.table_details.item(r, c)
                if it:
                    it.setBackground(bg)

    def do_relocate(self):
        res = VideoChecker.relocate_found_videos(self.report)
        moved = res["moved_count"]
        already = res["already_count"]
        errs = res["errors"]
        
        msg = ""
        if moved > 0:
            msg += f"✅ 成功归位移动了 {moved} 个视频到项目 `downloads/videos/` 文件夹中！\n"
        if already > 0:
            msg += f"ℹ️ 有 {already} 个视频本身已在项目内置目录中。\n"
        if errs:
            msg += "\n以下文件移动发生异常：\n" + "\n".join(errs)
            
        if not msg:
            msg = "没有可供归位的视频文件。"
            
        QMessageBox.information(self, "归位完成", msg)
        self.refresh_report()
        
        main_win = self.window()
        if hasattr(main_win, "reload_projects_list"):
            main_win.reload_projects_list()


class BatchVideoCheckDialog(QDialog):
    """Dialog displaying video completeness inspection report across ALL workspace projects."""
    
    def __init__(self, projects_list, base_storage_path, parent=None):
        super().__init__(parent)
        self.projects_list = projects_list
        self.base_storage_path = base_storage_path
        self.batch_report = None
        self.init_ui()
        self.refresh_batch_report()

    def init_ui(self):
        self.setWindowTitle("🔍 全项目视频完整性核查与一键批量归位 (Batch Inspector)")
        self.resize(980, 650)
        
        self.setStyleSheet("""
            QDialog {
                background-color: #FAF6F0;
                color: #5D4037;
                font-family: "Segoe UI", "PingFang SC", sans-serif;
            }
            QGroupBox {
                font-weight: bold;
                font-size: 13px;
                border: 1px solid #D7CCC8;
                border-radius: 6px;
                margin-top: 6px;
                padding-top: 12px;
                background-color: white;
            }
            QLabel {
                font-size: 13px;
                color: #5D4037;
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
                padding: 6px;
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
            QPushButton#btn_batch_relocate {
                background-color: #10B981;
                font-size: 14px;
                padding: 8px 18px;
            }
            QPushButton#btn_batch_relocate:hover {
                background-color: #059669;
            }
        """)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)
        
        # 1. Header Info
        header_box = QGroupBox("📊 全项目视频完成度汇总概览")
        h_layout = QVBoxLayout(header_box)
        
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(20)
        
        self.lbl_total_proj = QLabel("总项目数: <b>0</b>")
        self.lbl_complete_proj = QLabel("✅ 100%已就绪: <b>0</b>")
        self.lbl_complete_proj.setStyleSheet("color: #10B981; font-weight: bold;")
        self.lbl_pending_videos = QLabel("⚠️ 待归位视频: <b>0</b> 个")
        self.lbl_pending_videos.setStyleSheet("color: #D97706; font-weight: bold;")
        self.lbl_missing_videos = QLabel("❌ 缺失视频: <b>0</b> 个")
        self.lbl_missing_videos.setStyleSheet("color: #EF4444; font-weight: bold;")
        
        cards_layout.addWidget(self.lbl_total_proj)
        cards_layout.addWidget(self.lbl_complete_proj)
        cards_layout.addWidget(self.lbl_pending_videos)
        cards_layout.addWidget(self.lbl_missing_videos)
        cards_layout.addStretch()
        
        h_layout.addLayout(cards_layout)
        main_layout.addWidget(header_box)
        
        # 2. Table Section
        self.table_projects = QTableWidget()
        self.table_projects.setColumnCount(8)
        self.table_projects.setHorizontalHeaderLabels([
            "项目ID/序号", "项目名称", "文案片段", "已归位", "待归位", "缺失视频", "完成度", "操作"
        ])
        self.table_projects.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_projects.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_projects.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        main_layout.addWidget(self.table_projects, stretch=1)
        
        # 3. Bottom Action Buttons
        bottom_layout = QHBoxLayout()
        
        self.btn_batch_relocate = QPushButton("📦 一键全部归位所有待处理视频")
        self.btn_batch_relocate.setObjectName("btn_batch_relocate")
        self.btn_batch_relocate.clicked.connect(self.do_batch_relocate)
        bottom_layout.addWidget(self.btn_batch_relocate)
        
        btn_refresh = QPushButton("🔄 重新扫描")
        btn_refresh.clicked.connect(self.refresh_batch_report)
        bottom_layout.addWidget(btn_refresh)
        
        bottom_layout.addStretch()
        
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        bottom_layout.addWidget(btn_close)
        
        main_layout.addLayout(bottom_layout)

    def refresh_batch_report(self):
        """Scans disk for all projects."""
        self.batch_report = VideoChecker.check_all_projects(self.projects_list, self.base_storage_path)
        self.populate_batch_report()

    def populate_batch_report(self):
        if not self.batch_report:
            return
            
        tot_p = self.batch_report.get("total_projects", 0)
        comp_p = self.batch_report.get("fully_complete_count", 0)
        pending_v = self.batch_report.get("pending_count_total", 0)
        missing_v = self.batch_report.get("missing_count_total", 0)
        
        self.lbl_total_proj.setText(f"总项目数: <b>{tot_p}</b>")
        self.lbl_complete_proj.setText(f"✅ 100%已就绪: <b>{comp_p}</b> 个项目")
        self.lbl_pending_videos.setText(f"⚠️ 待归位视频: <b>{pending_v}</b> 个")
        self.lbl_missing_videos.setText(f"❌ 缺失视频: <b>{missing_v}</b> 个")
        
        if pending_v > 0:
            self.btn_batch_relocate.setEnabled(True)
            self.btn_batch_relocate.setText(f"📦 一键全部归位 ({pending_v}个待处理视频)")
            self.btn_batch_relocate.setStyleSheet("background-color: #10B981; color: white; font-weight: bold;")
        else:
            self.btn_batch_relocate.setEnabled(False)
            self.btn_batch_relocate.setText("📦 暂无可归位视频")
            self.btn_batch_relocate.setStyleSheet("background-color: #9CA3AF; color: white; font-weight: bold;")

        reports = self.batch_report.get("projects_reports", [])
        self.table_projects.setRowCount(len(reports))
        
        for r, proj_rep in enumerate(reports):
            # 0. ID
            pid = proj_rep.get("project_id", "")
            self.table_projects.setItem(r, 0, QTableWidgetItem(pid))
            
            # 1. Name
            pname = proj_rep.get("project_name", pid)
            self.table_projects.setItem(r, 1, QTableWidgetItem(pname))
            
            # 2. Segments
            tot_seg = proj_rep.get("total_segments", 0)
            self.table_projects.setItem(r, 2, QTableWidgetItem(str(tot_seg)))
            
            # 3. Already
            already = proj_rep.get("already_count", 0)
            it_already = QTableWidgetItem(str(already))
            it_already.setForeground(QColor("#10B981"))
            self.table_projects.setItem(r, 3, it_already)
            
            # 4. Pending
            pending = proj_rep.get("pending_count", 0)
            it_pending = QTableWidgetItem(str(pending))
            it_pending.setForeground(QColor("#D97706") if pending > 0 else QColor("#9CA3AF"))
            self.table_projects.setItem(r, 4, it_pending)
            
            # 5. Missing
            missing = proj_rep.get("missing_count", 0)
            it_missing = QTableWidgetItem(str(missing))
            it_missing.setForeground(QColor("#EF4444") if missing > 0 else QColor("#9CA3AF"))
            self.table_projects.setItem(r, 5, it_missing)
            
            # 6. Completion rate
            rate = proj_rep.get("completion_rate", 0.0)
            it_rate = QTableWidgetItem(f"{rate:.1f}%")
            it_rate.setFont(self.font())
            self.table_projects.setItem(r, 6, it_rate)
            
            # Row highlight color
            if rate >= 100.0 and pending == 0:
                bg = QColor("#D1FAE5")
            elif pending > 0:
                bg = QColor("#FEF3C7")
            else:
                bg = QColor("#FEE2E2") if missing > 0 else QColor("#FFFFFF")
                
            for c in range(7):
                it = self.table_projects.item(r, c)
                if it:
                    it.setBackground(bg)
                    
            # 7. Operations Widget (View Detail & Relocate Single)
            op_widget = QWidget()
            op_layout = QHBoxLayout(op_widget)
            op_layout.setContentsMargins(4, 2, 4, 2)
            op_layout.setSpacing(6)
            
            btn_detail = QPushButton("🔍 明细")
            btn_detail.setStyleSheet("background-color: #0284C7; color: white; padding: 3px 8px; font-size: 11px;")
            btn_detail.clicked.connect(lambda _, rep=proj_rep: self.open_project_detail_dialog(rep))
            op_layout.addWidget(btn_detail)
            
            if pending > 0:
                btn_rel_single = QPushButton("📦 归位")
                btn_rel_single.setStyleSheet("background-color: #10B981; color: white; padding: 3px 8px; font-size: 11px;")
                btn_rel_single.clicked.connect(lambda _, rep=proj_rep: self.relocate_single_project(rep))
                op_layout.addWidget(btn_rel_single)
                
            self.table_projects.setCellWidget(r, 7, op_widget)

    def open_project_detail_dialog(self, proj_rep):
        from models.project_model import ProjectModel
        proj_path = proj_rep.get("project_path")
        if not proj_path:
            return
        proj_model = ProjectModel(proj_path)
        dlg = VideoCheckDialog(
            report=proj_rep,
            project_model=proj_model,
            project_path=proj_path,
            base_storage_path=self.base_storage_path,
            parent=self
        )
        dlg.exec()
        self.refresh_batch_report()

    def relocate_single_project(self, proj_rep):
        res = VideoChecker.relocate_found_videos(proj_rep)
        moved = res["moved_count"]
        if moved > 0:
            QMessageBox.information(self, "归位成功", f"✅ 成功归位了 {moved} 个视频文件！")
        self.refresh_batch_report()
        
        main_win = self.window()
        if hasattr(main_win, "reload_projects_list"):
            main_win.reload_projects_list()

    def do_batch_relocate(self):
        res = VideoChecker.relocate_batch_videos(self.batch_report)
        moved = res["moved_count"]
        errs = res["errors"]
        
        msg = ""
        if moved > 0:
            msg += f"🎉 成功为全项目一键归位了 {moved} 个视频文件！\n"
        if errs:
            msg += "\n以下文件归位出现错误：\n" + "\n".join(errs)
            
        if not msg:
            msg = "没有可归位的视频文件。"
            
        QMessageBox.information(self, "批量归位完成", msg)
        self.refresh_batch_report()
        
        main_win = self.window()
        if hasattr(main_win, "reload_projects_list"):
            main_win.reload_projects_list()
