# -*- coding: utf-8 -*-
"""
账号积分管理 Tab

- 显示所有已连接浏览器（插件）的账号与积分
- 只有点击「刷新积分」时才会让插件去读取积分（不会自动轮询，避免浏览器卡顿）
- 设置阈值，一键关闭积分「低于」阈值的浏览器（等于阈值的不关闭）
"""
import json
import time
import logging
from pathlib import Path

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
                             QMessageBox, QAbstractItemView, QTextEdit)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor

logger = logging.getLogger(__name__)

REFRESH_COOLDOWN_MS = 5000   # 刷新积分按钮冷却时间，避免频繁点击


class AccountMonitorWidget(QWidget):
    COL_STATUS, COL_EMAIL, COL_ALIAS, COL_POINTS, COL_TIME, COL_ACTION = range(6)

    def __init__(self, plugin_server, workspace_dir, parent=None):
        super().__init__(parent)
        self.plugin_server = plugin_server
        self.workspace_dir = Path(workspace_dir)
        self.settings_file = self.workspace_dir / "account_monitor.json"
        self.aliases_file = self.workspace_dir / "account_aliases.json"
        self.aliases = {}
        self.threshold = 50
        self._load_settings()

        self._refresh_pending = False
        self._init_ui()

        if self.plugin_server:
            self.plugin_server.client_connected_signal.connect(self._schedule_table_refresh)
            self.plugin_server.client_disconnected_signal.connect(self._schedule_table_refresh)
            self.plugin_server.client_updated_signal.connect(self._schedule_table_refresh)
            self.plugin_server.rpc_response_signal.connect(self._on_rpc_response)

        self.refresh_table()

    # ──────────────────────────────────────────
    # 设置 / 备注 持久化
    # ──────────────────────────────────────────
    def _load_settings(self):
        try:
            if self.settings_file.exists():
                data = json.loads(self.settings_file.read_text(encoding="utf-8"))
                self.threshold = int(data.get("threshold", 50))
        except Exception as e:
            logger.warning(f"读取账号监控设置失败: {e}")
        try:
            if self.aliases_file.exists():
                self.aliases = json.loads(self.aliases_file.read_text(encoding="utf-8")) or {}
        except Exception as e:
            logger.warning(f"读取账号备注失败: {e}")
            self.aliases = {}

    def _save_settings(self):
        try:
            self.settings_file.write_text(json.dumps({"threshold": self.threshold}, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
        except Exception as e:
            logger.warning(f"保存账号监控设置失败: {e}")

    def _save_aliases(self):
        try:
            self.aliases_file.write_text(json.dumps(self.aliases, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"保存账号备注失败: {e}")

    # ──────────────────────────────────────────
    # UI
    # ──────────────────────────────────────────
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 第一行：连接状态 + 刷新
        row1 = QHBoxLayout()
        self.lbl_conn = QLabel("")
        self.lbl_conn.setStyleSheet("font-size: 13px; font-weight: bold;")
        row1.addWidget(self.lbl_conn)
        row1.addStretch()

        self.btn_refresh = QPushButton("🔄 刷新积分")
        self.btn_refresh.setToolTip("让每个已连接的浏览器读取一次当前积分（只在点击时读取，不会自动轮询）")
        self.btn_refresh.setStyleSheet("""
            QPushButton { background-color: #059669; color: white; font-weight: bold; padding: 7px 16px; border-radius: 4px; }
            QPushButton:hover { background-color: #047857; }
            QPushButton:disabled { background-color: #9CA3AF; }
        """)
        self.btn_refresh.clicked.connect(self.on_refresh_clicked)
        row1.addWidget(self.btn_refresh)
        layout.addLayout(row1)

        # 第二行：阈值 + 一键关闭
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("积分阈值："))
        self.spin_threshold = QSpinBox()
        self.spin_threshold.setRange(0, 100000)
        self.spin_threshold.setValue(self.threshold)
        self.spin_threshold.setSuffix(" 积分")
        self.spin_threshold.setMinimumWidth(120)
        self.spin_threshold.setStyleSheet("padding: 4px; font-size: 13px;")
        self.spin_threshold.valueChanged.connect(self.on_threshold_changed)
        row2.addWidget(self.spin_threshold)

        hint = QLabel("低于阈值的浏览器会被标红（等于阈值不算）；未刷新出积分的浏览器不会被关闭")
        hint.setStyleSheet("font-size: 11px; color: #6B7280; font-weight: normal;")
        row2.addWidget(hint)
        row2.addStretch()

        self.btn_close_low = QPushButton("🔴 一键关闭低于阈值的浏览器")
        self.btn_close_low.setStyleSheet("""
            QPushButton { background-color: #DC2626; color: white; font-weight: bold; padding: 7px 16px; border-radius: 4px; }
            QPushButton:hover { background-color: #B91C1C; }
        """)
        self.btn_close_low.clicked.connect(self.on_close_low_clicked)
        row2.addWidget(self.btn_close_low)
        layout.addLayout(row2)

        # 第三行：批量清空
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("批量操作（对所有已连接浏览器）："))
        self.btn_clear_media = QPushButton("🗑️ 清空 Flow 页面所有图片和视频")
        self.btn_clear_media.setToolTip("在每个浏览器当前打开的 Flow 项目中执行 Ctrl+A 全选 → Delete 删除")
        self.btn_clear_media.setStyleSheet("""
            QPushButton { background-color: #7C3AED; color: white; font-weight: bold; padding: 7px 16px; border-radius: 4px; }
            QPushButton:hover { background-color: #6D28D9; }
        """)
        self.btn_clear_media.clicked.connect(self.on_clear_media_clicked)
        row3.addWidget(self.btn_clear_media)

        self.btn_clear_tasks = QPushButton("🧹 清空所有插件中的任务")
        self.btn_clear_tasks.setToolTip("相当于在每个浏览器插件里点击「清空全部任务列表」")
        self.btn_clear_tasks.setStyleSheet("""
            QPushButton { background-color: #EA580C; color: white; font-weight: bold; padding: 7px 16px; border-radius: 4px; }
            QPushButton:hover { background-color: #C2410C; }
        """)
        self.btn_clear_tasks.clicked.connect(self.on_clear_tasks_clicked)
        row3.addWidget(self.btn_clear_tasks)
        row3.addStretch()
        layout.addLayout(row3)

        # 表格
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["状态", "账号", "备注（可编辑）", "剩余积分", "积分更新时间", "操作"])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(self.COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(self.COL_EMAIL, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(self.COL_ALIAS, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(self.COL_POINTS, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(self.COL_TIME, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(self.COL_ACTION, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setStyleSheet("""
            QTableWidget { background-color: white; border: 1px solid #D7CCC8; border-radius: 4px; font-size: 13px; color: #5D4037; }
            QHeaderView::section { background-color: #EDE0D4; color: #5D4037; font-weight: bold; padding: 6px; border: none; }
        """)
        self.table.cellChanged.connect(self.on_cell_changed)
        layout.addWidget(self.table, stretch=1)

        # 日志
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(110)
        self.log_text.setStyleSheet("background-color: #1E293B; color: #E2E8F0; font-family: Consolas, monospace; font-size: 11px; border-radius: 4px;")
        layout.addWidget(self.log_text)

    def _log(self, msg):
        ts = time.strftime("%H:%M:%S")
        self.log_text.append(f"[{ts}] {msg}")
        logger.info(msg)

    # ──────────────────────────────────────────
    # 数据
    # ──────────────────────────────────────────
    @staticmethod
    def _short_email(client):
        email = client.get("email") or ""
        if email:
            return email
        cid = client.get("client_id", "")
        return cid.split(" (W#")[0] if " (W#" in cid else cid

    def _clients(self):
        if not self.plugin_server:
            return []
        try:
            return self.plugin_server.get_online_clients()
        except Exception:
            return []

    def _is_below(self, client):
        return bool(client.get("points_known")) and int(client.get("remaining_points", 0)) < self.threshold

    # ──────────────────────────────────────────
    # 表格刷新
    # ──────────────────────────────────────────
    def _schedule_table_refresh(self, *args):
        # 合并短时间内的多次信号，减少重绘
        if self._refresh_pending:
            return
        self._refresh_pending = True
        QTimer.singleShot(200, self._do_scheduled_refresh)

    def _do_scheduled_refresh(self):
        self._refresh_pending = False
        # 正在编辑备注时不要重建表格，稍后再刷
        if self.table.state() == QAbstractItemView.State.EditingState:
            self._schedule_table_refresh()
            return
        self.refresh_table()

    def refresh_table(self):
        clients = self._clients()
        server_ok = bool(self.plugin_server and getattr(self.plugin_server, "servers", None))
        if not server_ok:
            self.lbl_conn.setText("🔴 插件服务未启动（端口 18188 可能被占用）")
            self.lbl_conn.setStyleSheet("font-size: 13px; font-weight: bold; color: #DC2626;")
        elif not clients:
            self.lbl_conn.setText("⚪ 暂无浏览器连接（请打开 Google Flow 页面，并在扩展管理页刷新插件）")
            self.lbl_conn.setStyleSheet("font-size: 13px; font-weight: bold; color: #6B7280;")
        else:
            below = sum(1 for c in clients if self._is_below(c))
            self.lbl_conn.setText(f"🟢 已连接 {len(clients)} 个浏览器页面  |  低于阈值: {below} 个")
            self.lbl_conn.setStyleSheet("font-size: 13px; font-weight: bold; color: #059669;")

        self.table.blockSignals(True)
        self.table.setRowCount(len(clients))
        for row, c in enumerate(clients):
            cid = c.get("client_id", "")
            email = self._short_email(c)
            known = bool(c.get("points_known"))
            pts = int(c.get("remaining_points", 0)) if known else None
            below = self._is_below(c)

            status_txt = "⚪ 未读取" if not known else ("🔴 不足" if below else "🟢 正常")
            self._set_item(row, self.COL_STATUS, status_txt, center=True)

            email_item = self._set_item(row, self.COL_EMAIL, email or "(未识别账号)")
            email_item.setData(Qt.ItemDataRole.UserRole, cid)
            email_item.setToolTip(cid)

            alias_item = QTableWidgetItem(self.aliases.get(email, ""))
            self.table.setItem(row, self.COL_ALIAS, alias_item)

            pts_item = self._set_item(row, self.COL_POINTS, "-" if pts is None else str(pts), center=True)
            if pts is not None:
                pts_item.setForeground(QColor("#DC2626") if below else QColor("#059669"))
                f = pts_item.font(); f.setBold(True); pts_item.setFont(f)

            ts = c.get("points_updated_at")
            self._set_item(row, self.COL_TIME, time.strftime("%H:%M:%S", time.localtime(ts)) if ts else "-", center=True)

            btn = QPushButton("关闭浏览器")
            btn.setStyleSheet("QPushButton { background-color: #F87171; color: white; padding: 3px 10px; border-radius: 3px; font-size: 12px; }"
                              "QPushButton:hover { background-color: #DC2626; }")
            btn.clicked.connect(lambda _=False, cid=cid, em=email: self.close_single(cid, em))
            self.table.setCellWidget(row, self.COL_ACTION, btn)

            if below:
                for col in range(self.COL_ACTION):
                    it = self.table.item(row, col)
                    if it:
                        it.setBackground(QColor("#FEE2E2"))
        self.table.blockSignals(False)

    def _set_item(self, row, col, text, center=False):
        it = QTableWidgetItem(text)
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if center:
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, col, it)
        return it

    # ──────────────────────────────────────────
    # 事件
    # ──────────────────────────────────────────
    def on_cell_changed(self, row, col):
        if col != self.COL_ALIAS:
            return
        email_item = self.table.item(row, self.COL_EMAIL)
        alias_item = self.table.item(row, self.COL_ALIAS)
        if not email_item or not alias_item:
            return
        email = email_item.text()
        if not email or email == "(未识别账号)":
            return
        self.aliases[email] = alias_item.text().strip()
        self._save_aliases()

    def on_threshold_changed(self, val):
        self.threshold = int(val)
        self._save_settings()
        self.refresh_table()

    def on_refresh_clicked(self):
        if not self.plugin_server:
            return
        clients = self._clients()
        if not clients:
            QMessageBox.information(self, "提示", "当前没有已连接的浏览器。\n请打开 Google Flow 页面，并在 chrome://extensions 刷新插件后再试。")
            return
        n = self.plugin_server.query_all_clients_points()
        self._log(f"已向 {n} 个浏览器发送读取积分指令...")
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setText("⏳ 读取中...")
        QTimer.singleShot(REFRESH_COOLDOWN_MS, self._reset_refresh_btn)

    def _reset_refresh_btn(self):
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText("🔄 刷新积分")
        self.refresh_table()

    def _alias_label(self, email):
        alias = self.aliases.get(email, "")
        return f"{email}（{alias}）" if alias else email

    def close_single(self, client_id, email):
        reply = QMessageBox.question(
            self, "确认关闭",
            f"确定要关闭该浏览器吗？\n\n{self._alias_label(email)}\n\n（会关闭整个浏览器）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._request_close(client_id, self._alias_label(email), email)

    def on_close_low_clicked(self):
        clients = self._clients()
        if not clients:
            QMessageBox.information(self, "提示", "当前没有已连接的浏览器。")
            return

        targets = [c for c in clients if self._is_below(c)]
        unknown = [c for c in clients if not c.get("points_known")]

        if not targets:
            msg = f"没有积分低于 {self.threshold} 的浏览器。"
            if unknown:
                msg += f"\n\n另有 {len(unknown)} 个浏览器还没有读取到积分，请先点击「刷新积分」。"
            QMessageBox.information(self, "提示", msg)
            return

        lines = "\n".join(f"  • {self._alias_label(self._short_email(c))}：{c.get('remaining_points', 0)} 积分" for c in targets)
        extra = f"\n\n⚠️ 另有 {len(unknown)} 个浏览器未读取到积分，不会被关闭。" if unknown else ""
        reply = QMessageBox.question(
            self, "确认一键关闭",
            f"以下 {len(targets)} 个浏览器积分低于 {self.threshold}，将被关闭：\n\n{lines}{extra}\n\n确定关闭吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

        for c in targets:
            label = f"{self._alias_label(self._short_email(c))}（{c.get('remaining_points', 0)} 积分）"
            self._request_close(c.get("client_id"), label, self._short_email(c))

    # ──────────────────────────────────────────
    # 关闭浏览器（定位该账号的 Chrome 窗口 → 只关这些窗口，不结束共享进程）
    # ──────────────────────────────────────────
    def _request_close(self, client_id, label, email=""):
        # 完全依赖插件自身的关闭能力（最安全，不跨 Profile）
        self._log(f"⚡ 正在向插件发送精准关闭指令: {label}")
        
        import uuid
        token = "FLOWCLOSE-" + uuid.uuid4().hex[:10]
        # 让插件执行关闭
        self.plugin_server.close_client_browser(client_id, token)
        
        if not hasattr(self, "_pending_closes"):
            self._pending_closes = {}
            self._close_timer = QTimer(self)
            self._close_timer.setInterval(400)
            self._close_timer.timeout.connect(self._poll_pending_closes)
        self._pending_closes[token] = {"label": label, "client_id": client_id, "email": email,
                                       "start": time.time(), "hwnds": None, "closed_at": None, "retried": False}
        if not self._close_timer.isActive():
            self._close_timer.start()

    def _client_connected(self, client_id):
        return any(c.get("client_id") == client_id for c in self._clients())

    def _poll_pending_closes(self):
        from services import browser_closer as bc
        now = time.time()
        for token, p in list(self._pending_closes.items()):
            try:
                if not self._client_connected(p["client_id"]):
                    self._log(f"✅ 浏览器已成功关闭: {p['label']}")
                    del self._pending_closes[token]
                    continue

                if p["hwnds"] is None:
                    hwnds, profile_dir, profile_email = bc.find_windows_for_email(p["email"])
                    where = f"Chrome 用户「{profile_dir}」({profile_email})" if hwnds else ""
                    if not hwnds:
                        hwnds = bc.find_windows_by_title_token(token)
                        where = "标题标记窗口" if hwnds else ""
                    if hwnds:
                        for h in hwnds:
                            bc.close_window(h)
                        p["hwnds"] = hwnds
                        p["closed_at"] = now
                        self._log(f"🪟 找到 {where} 的 {len(hwnds)} 个窗口，正在使用强制命令关闭: {p['label']}")
                    elif now - p["start"] > 6:
                        self._log(f"❌ 未找到该账号的浏览器窗口，且插件尝试自动关闭失败: {p['label']}")
                        del self._pending_closes[token]
                else:
                    remaining = [h for h in p["hwnds"] if bc.window_exists(h)]
                    if not remaining:
                        self._log(f"✅ 浏览器已关闭: {p['label']}")
                        del self._pending_closes[token]
                    elif not p["retried"] and now - p["closed_at"] > 4:
                        for h in remaining:
                            bc.close_window(h)
                        p["retried"] = True
                        p["closed_at"] = now
                    elif p["retried"] and now - p["closed_at"] > 5:
                        self._log(f"❌ 窗口未能关闭（可能弹出了“确定离开”提示，请手动处理）: {p['label']}")
                        del self._pending_closes[token]
            except Exception as e:
                self._log(f"❌ 关闭出错: {p['label']} - {e}")
                self._pending_closes.pop(token, None)
        if not self._pending_closes:
            self._close_timer.stop()

    # ──────────────────────────────────────────
    # 批量清空：Flow 媒体 / 插件任务
    # ──────────────────────────────────────────
    def _label_for_client_id(self, client_id):
        for c in self._clients():
            if c.get("client_id") == client_id:
                return self._alias_label(self._short_email(c))
        return client_id.split(" (W#")[0]

    def _broadcast(self, action, what):
        clients = self._clients()
        if not clients:
            QMessageBox.information(self, "提示", "当前没有已连接的浏览器。")
            return
        sent = 0
        for c in clients:
            if self.plugin_server.send_rpc_action(c.get("client_id"), action, {}):
                sent += 1
        self._log(f"⏳ 已向 {sent} 个浏览器发送「{what}」指令...")

    def on_clear_media_clicked(self):
        n = len(self._clients())
        if not n:
            QMessageBox.information(self, "提示", "当前没有已连接的浏览器。")
            return
        reply = QMessageBox.warning(
            self, "确认清空 Flow 媒体",
            f"将在 {n} 个浏览器当前打开的 Flow 项目中，删除页面上的【所有图片和视频】。\n\n"
            "（相当于在每个 Flow 页面按 Ctrl+A 再按 Delete，删除的内容会进入 Flow 回收站）\n\n确定继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._broadcast("clear_media", "清空 Flow 媒体")

    def on_clear_tasks_clicked(self):
        n = len(self._clients())
        if not n:
            QMessageBox.information(self, "提示", "当前没有已连接的浏览器。")
            return
        reply = QMessageBox.question(
            self, "确认清空插件任务",
            f"将清空 {n} 个浏览器插件中的【全部任务列表】。\n\n（Flow 云端项目和已下载文件不受影响）\n\n确定继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._broadcast("clear_tasks", "清空插件任务")

    def _on_rpc_response(self, payload):
        msg = payload.get("message", {}) or {}
        action = msg.get("action", "")
        if action not in ("clear_media_response", "clear_tasks_response"):
            return
        label = self._label_for_client_id(payload.get("client_id", ""))
        data = msg.get("data", {}) or {}
        ok = msg.get("success")
        if action == "clear_tasks_response":
            if ok:
                self._log(f"✅ 已清空插件任务（{data.get('cleared', 0)} 个）: {label}")
            else:
                self._log(f"❌ 清空插件任务失败: {label} - {msg.get('error', '')}")
        else:
            before, after = data.get("before", "?"), data.get("after", "?")
            if ok:
                note = data.get("note")
                self._log(f"✅ 已清空 Flow 媒体: {label}" + (f"（{note}）" if note else f"（{before} → {after}）"))
            else:
                self._log(f"❌ 清空 Flow 媒体失败: {label} - {msg.get('error', '')}（{before} → {after}）")

