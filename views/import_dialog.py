# -*- coding: utf-8 -*-
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QTableWidget, QTableWidgetItem, QLabel, QMessageBox, 
                             QHeaderView, QTextEdit)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from bs4 import BeautifulSoup
import re
import csv
import io

class ImportDialog(QDialog):
    """Dialog for importing project rows from clipboard."""
    
    ROLE_SHORT_NAMES = {
        "name": "名字",
        "chinese": "中文",
        "original": "原文",
        "link": "链接",
        "empty": "空列",
    }

    def __init__(self, storage_manager, parent=None, config_manager=None):
        super().__init__(parent)
        self.storage_manager = storage_manager
        from models.config_manager import ConfigManager
        self.config_manager = config_manager or getattr(parent, "config_manager", None)
        if not self.config_manager and getattr(storage_manager, "workspace_dir", None):
            self.config_manager = ConfigManager(storage_manager.workspace_dir)
        elif self.config_manager:
            self.config_manager.load()
        self.import_columns = list(
            getattr(self.config_manager, "import_columns", None) or ConfigManager.DEFAULT_IMPORT_COLUMNS
        )
        self.imported_rows = []
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("新建导入 (Import Projects)")
        self.resize(900, 600)
        
        # Apply stylesheet matching the warm theme
        self.setStyleSheet("""
            QDialog {
                background-color: #FAF6F0;
                color: #5D4037;
                font-family: "Segoe UI", sans-serif;
            }
            QLabel {
                font-size: 14px;
                color: #5D4037;
                font-weight: bold;
            }
            QPushButton {
                background-color: #E0A96D;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #D2904C;
            }
            QPushButton:pressed {
                background-color: #B87635;
            }
            QPushButton#btn_cancel {
                background-color: #D7CCC8;
                color: #5D4037;
            }
            QPushButton#btn_cancel:hover {
                background-color: #BCAAA4;
            }
            QTableWidget {
                background-color: white;
                border: 1px solid #D7CCC8;
                gridline-color: #EFEBE9;
                selection-background-color: #FFE0B2;
                selection-color: #5D4037;
                border-radius: 4px;
            }
            QHeaderView::section {
                background-color: #D7CCC8;
                color: #5D4037;
                padding: 6px;
                font-weight: bold;
                border: 1px solid #CFD8DC;
            }
        """)

        layout = QVBoxLayout(self)
        
        # Instructions showing current column rule
        col_desc = " | ".join(
            f"第{i + 1}列:{self.ROLE_SHORT_NAMES.get(t, t)}"
            for i, t in enumerate(self.import_columns)
        )
        self.lbl_info = QLabel(
            f"请在 Excel/Google Sheets 中复制要导入的行（当前规则共 {len(self.import_columns)} 列：{col_desc}），然后点击下方按钮读取剪贴板："
        )
        self.lbl_info.setWordWrap(True)
        layout.addWidget(self.lbl_info)
        
        # Clipboard action button
        self.btn_read_clipboard = QPushButton("📋 从剪贴板读取数据")
        self.btn_read_clipboard.clicked.connect(self.read_from_clipboard)
        layout.addWidget(self.btn_read_clipboard)
        
        # Preview Table
        name_cols = [i + 1 for i, t in enumerate(self.import_columns) if t == "name"]
        zh_cols = [i + 1 for i, t in enumerate(self.import_columns) if t == "chinese"]
        orig_cols = [i + 1 for i, t in enumerate(self.import_columns) if t == "original"]
        link_cols = [i + 1 for i, t in enumerate(self.import_columns) if t == "link"]

        h_name1 = f"{name_cols[0]}: 名称前缀" if len(name_cols) > 1 else f"{name_cols[0] if name_cols else 1}: 名字"
        h_zh = f"{','.join(map(str, zh_cols))}: 中文文案"
        h_orig = f"{','.join(map(str, orig_cols))}: 原文文案"
        h_link = f"{','.join(map(str, link_cols))}: 链接"
        h_name2 = f"{','.join(map(str, name_cols[1:]))}: 名字补充/后缀" if len(name_cols) > 1 else "名字补充 (无)"

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "序号", h_name1, h_zh, h_orig, h_link, h_name2
        ])
        self.table.setColumnHidden(5, len(name_cols) <= 1)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        
        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setObjectName("btn_cancel")
        self.btn_cancel.clicked.connect(self.reject)
        
        self.btn_confirm = QPushButton("确认导入")
        self.btn_confirm.setEnabled(False)
        self.btn_confirm.clicked.connect(self.confirm_import)
        
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_confirm)
        layout.addLayout(btn_layout)

    def _get_min_required_cols(self):
        """Returns the minimum number of columns needed in a clipboard row to cover required fields."""
        must_indices = [i for i, t in enumerate(self.import_columns) if t in ("chinese", "original", "link")]
        name_indices = [i for i, t in enumerate(self.import_columns) if t == "name"]
        if name_indices:
            must_indices.append(name_indices[0])
        if must_indices:
            return max(must_indices) + 1
        return len(self.import_columns)

    def read_from_clipboard(self):
        clipboard = QGuiApplication.clipboard()
        mime_data = clipboard.mimeData()
        
        parsed_rows = []
        
        # Try reading HTML first to preserve hyperlinked URLs in cells
        if mime_data.hasHtml():
            html_text = mime_data.html()
            parsed_rows = self.parse_html_table(html_text)
            
        # Fallback to plain text TSV if HTML failed or returned no results
        if not parsed_rows and mime_data.hasText():
            plain_text = mime_data.text()
            parsed_rows = self.parse_tsv_text(plain_text)
            
        if not parsed_rows:
            QMessageBox.warning(
                self,
                "提示",
                f"未能从剪贴板读取到有效的 {len(self.import_columns)} 列数据，请按当前列规则复制后重试。"
            )
            return
            
        self.imported_rows = parsed_rows
        self.populate_table()
        self.btn_confirm.setEnabled(True)
        QMessageBox.information(self, "成功", f"成功解析出 {len(parsed_rows)} 行项目数据！")

    def parse_html_table(self, html_content):
        """Parses HTML table and extracts cell text and all cell links."""
        soup = BeautifulSoup(html_content, 'html.parser')
        rows = []
        expected_cols = len(self.import_columns)
        min_cols = self._get_min_required_cols()
        
        tr_tags = soup.find_all('tr')
        for tr in tr_tags:
            td_tags = tr.find_all(['td', 'th'])
            if not td_tags:
                continue
                
            row_data = []
            for td in td_tags:
                # Use newline as separator to preserve Excel line breaks and prevent word sticking
                text = td.get_text(separator='\n').strip()
                
                # Extract all <a> href links
                links = []
                for a in td.find_all('a'):
                    if a.get('href'):
                        links.append(a.get('href').strip())
                
                # Also regex search for plain text http/https URLs in the cell
                url_pattern = re.compile(r'https?://[^\s\u4e00-\u9fa5]+')
                text_urls = url_pattern.findall(text)
                for u in text_urls:
                    cleaned_u = u.rstrip('.,;)"\'”」')
                    if cleaned_u not in links:
                        links.append(cleaned_u)
                    
                row_data.append({
                    "text": text,
                    "links": links
                })
                
            num_cols = len(row_data)
            if num_cols >= min_cols:
                while len(row_data) < expected_cols:
                    row_data.append({"text": "", "links": []})
                rows.append(row_data[:expected_cols])
                
        return rows

    def parse_tsv_text(self, text_content):
        """Parses tab-separated text (TSV) from clipboard and extracts links."""
        rows = []
        expected_cols = len(self.import_columns)
        min_cols = self._get_min_required_cols()
        reader = csv.reader(io.StringIO(text_content.strip('\r\n')), delimiter='\t')
        for cols in reader:
            if not cols or not any(c.strip() for c in cols):
                continue
            num_cols = len(cols)
            if num_cols >= min_cols:
                row_data = []
                for col in cols[:expected_cols]:
                    val = col.strip()
                    url_pattern = re.compile(r'https?://[^\s\u4e00-\u9fa5]+')
                    links = [u.rstrip('.,;)"\'”」') for u in url_pattern.findall(val)]
                    row_data.append({
                        "text": val,
                        "links": links
                    })
                while len(row_data) < expected_cols:
                    row_data.append({"text": "", "links": []})
                rows.append(row_data)
                
        return rows

    def populate_table(self):
        """Fills QTableWidget with parsed clipboard rows according to self.import_columns."""
        self.table.setRowCount(len(self.imported_rows))
        
        # Calculate next starting index based on existing projects
        existing = self.storage_manager.list_projects()
        next_idx = 1
        if existing:
            try:
                next_idx = max(int(p["index_str"]) for p in existing) + 1
            except ValueError:
                next_idx = len(existing) + 1

        name_indices = [i for i, t in enumerate(self.import_columns) if t == "name"]
        zh_indices = [i for i, t in enumerate(self.import_columns) if t == "chinese"]
        orig_indices = [i for i, t in enumerate(self.import_columns) if t == "original"]
        link_indices = [i for i, t in enumerate(self.import_columns) if t == "link"]
                
        for row_idx, row in enumerate(self.imported_rows):
            proj_idx = next_idx + row_idx
            
            # Row index display
            self.table.setItem(row_idx, 0, QTableWidgetItem(f"{proj_idx:02d}"))
            
            # Name columns: 1st name column -> col1, additional name columns -> col7 (supplement)
            name_vals = [row[i]["text"].strip() for i in name_indices if i < len(row)]
            col1_val = name_vals[0] if name_vals else ""
            col7_val = "_".join(v for v in name_vals[1:] if v) if len(name_vals) > 1 else ""
            if not col1_val and col7_val:
                col1_val, col7_val = col7_val, ""

            self.table.setItem(row_idx, 1, QTableWidgetItem(col1_val))
            
            # Chinese copy
            zh_text = "\n".join(row[i]["text"] for i in zh_indices if i < len(row) and row[i]["text"])
            self.table.setItem(row_idx, 2, QTableWidgetItem(zh_text))
            
            # Original copy
            orig_text = "\n".join(row[i]["text"] for i in orig_indices if i < len(row) and row[i]["text"])
            self.table.setItem(row_idx, 3, QTableWidgetItem(orig_text))
            
            # Link column(s)
            collected_links = []
            for i in link_indices:
                if i < len(row):
                    if row[i]["links"]:
                        for lk in row[i]["links"]:
                            if lk not in collected_links:
                                collected_links.append(lk)
                    elif row[i]["text"]:
                        collected_links.append(row[i]["text"])
            drive_url = "\n".join(collected_links)
            self.table.setItem(row_idx, 4, QTableWidgetItem(drive_url))
            
            # Additional name / notes suffix
            self.table.setItem(row_idx, 5, QTableWidgetItem(col7_val))

    def confirm_import(self):
        """Creates project directories and stores metadata.json."""
        if not self.storage_manager.get_base_path():
            QMessageBox.warning(self, "错误", "请先设置存储总路径！")
            self.reject()
            return
            
        success_count = 0
        from models.project_model import ProjectModel
        from services.text_processor import TextProcessor
        
        for row_idx in range(self.table.rowCount()):
            try:
                idx_str = self.table.item(row_idx, 0).text()
                idx_val = int(idx_str)
                col1 = self.table.item(row_idx, 1).text()
                col4 = self.table.item(row_idx, 2).text()
                col5 = self.table.item(row_idx, 3).text()
                col6 = self.table.item(row_idx, 4).text()
                col7 = self.table.item(row_idx, 5).text()
                
                # 1. Create project folder
                proj_dir, proj_id = self.storage_manager.create_project_dir(idx_val, col1, col7)
                
                # 2. Write metadata.json
                proj = ProjectModel(proj_dir)
                proj.index = idx_val
                proj.col1_name = col1
                proj.col7_notes = col7
                proj.google_drive_url = col6
                proj.chinese_text = col4
                proj.spanish_text = col5
                # Auto clean and segment Spanish text on import using config_manager rules if available
                config_mgr = self.config_manager or getattr(self.parent(), "config_manager", None)
                if config_mgr:
                    config_mgr.load()
                proj.spanish_segments = TextProcessor.segment_spanish_text(col5, config_mgr)
                proj.save()
                
                # 3. Trigger automatic background download via parent MainWindow
                if col6 and hasattr(self.parent(), "start_background_download"):
                    self.parent().start_background_download(proj_id, col6, proj_dir)
                
                success_count += 1
            except Exception as e:
                print(f"Error importing row {row_idx}: {e}")
                
        QMessageBox.information(self, "成功", f"成功导入并创建了 {success_count} 个工程项目！")
        self.accept()
