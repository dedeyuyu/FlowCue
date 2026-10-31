# -*- coding: utf-8 -*-
"""浏览器定位 / 备注、识别开关、刷新积分、关闭低积分浏览器、清空媒体与任务。

由 HostedModeWidget 通过多重继承组合使用，方法内的 self 即 HostedModeWidget 实例。"""
from views.hosted.common import *  # noqa: F401,F403
from views.hosted.common import logger  # noqa: F401


class BrowserOpsMixin:
    # ──────────────────────────────── 定位浏览器 / 备注
    def _locate_cid(self, cid, fallback_entry=None):
        if not cid and not fallback_entry:
            return
        c = None
        if fallback_entry:
            c = self._resolve_client(fallback_entry)
        if not c and cid:
            c = next((x for x in self._clients() if x.get("client_id") == cid), None)
        if not c:
            QMessageBox.information(self, "提示", "该浏览器当前未连接（可能已关闭或页面不在 Flow 项目）。")
            return
        ok, msg = self.plugin_server.locate_client(c["client_id"])
        self._log(f"📍 定位浏览器：{self._label(c)} — {msg}")

    def _selected_browser_cid(self):
        row = self.tbl_browsers.currentRow()
        cids = getattr(self, "_browser_row_cids", [])
        if 0 <= row < len(cids):
            return cids[row]
        return None

    def _on_browser_double_clicked(self, row, col):
        cids = getattr(self, "_browser_row_cids", [])
        if not (0 <= row < len(cids)):
            return
        if col == 1:
            self._rename_cid(cids[row])
        else:
            entry = self.plan.get(cids[row])
            self._locate_cid(cids[row], entry)

    def _on_batch_double_clicked(self, row, col):
        if not (0 <= row < len(self.batches)):
            return
        b = self.batches[row]
        if not b.get("cid"):
            return
        entry = self.plan.get(b["cid"]) or {"cid": b["cid"], "email": b.get("email", ""), "iid": b.get("iid", "")}
        self._locate_cid(b["cid"], entry)

    def on_locate_selected(self):
        cid = self._selected_browser_cid()
        if not cid:
            QMessageBox.information(self, "提示", "请先在上方浏览器列表中选中一行（或直接双击该行）。")
            return
        self._locate_cid(cid, self.plan.get(cid))

    def on_locate_next_failed(self):
        failed_cids = []
        for b in self.batches:
            if b.get("cid") and b.get("upload_state") == "失败" and b["cid"] not in failed_cids:
                failed_cids.append(b["cid"])
        if not failed_cids:
            QMessageBox.information(self, "提示", "当前没有上传失败的浏览器。")
            return
        idx = getattr(self, "_locate_failed_idx", -1) + 1
        if idx >= len(failed_cids):
            idx = 0
        self._locate_failed_idx = idx
        cid = failed_cids[idx]
        names = []
        for b in self.batches:
            if b.get("cid") == cid and b.get("upload_state") == "失败":
                names += [Path(p).name for p in b["upload_failed"]]
        self._log(f"📍 [{idx + 1}/{len(failed_cids)}] 上传失败的浏览器，失败图片：{'、'.join(names[:10])}")
        self._locate_cid(cid, self.plan.get(cid))

    def on_rename_selected(self):
        cid = self._selected_browser_cid()
        if not cid:
            QMessageBox.information(self, "提示", "请先在上方浏览器列表中选中一行。")
            return
        self._rename_cid(cid)

    def _rename_cid(self, cid):
        from PyQt6.QtWidgets import QInputDialog
        c = next((x for x in self._clients() if x.get("client_id") == cid), None)
        if not c:
            QMessageBox.information(self, "提示", "该浏览器当前未连接，无法设置备注。")
            return
        iid = self._iid(c)
        key = iid or self._email(c)
        if not key:
            return
        old = self._alias(c)
        name, ok = QInputDialog.getText(self, "设置浏览器备注",
                                        f"浏览器：{iid or '(旧版插件)'}\n配置：{c.get('profile') or '-'}\n账号：{self._email(c) or '-'}\n\n"
                                        "备注名（如 Brave-037，会显示在该浏览器的窗口标题上）：", text=old)
        if not ok:
            return
        name = name.strip()
        try:
            self._load_aliases()
            if name:
                self.aliases[key] = name
            else:
                self.aliases.pop(key, None)
            self.aliases_file.write_text(json.dumps(self.aliases, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))
            return
        if iid:
            self.plugin_server.set_instance_name(cid, name)
        self._log(f"✏️ 已设置备注：{key} → {name or '(清空)'}")
        self._schedule_refresh()

    # ──────────────────────────────── 识别开关（全局托管与手动模式分离）
    def _is_recognizing(self):
        return bool(self.plugin_server and self.plugin_server.is_running())

    def _update_recognize_btn(self):
        if not hasattr(self, "btn_recognize"):
            return
        on = self._is_recognizing()
        self.btn_recognize.setText("⏹ 停止识别" if on else "🔌 开始识别浏览器")
        color, hover = ("#DC2626", "#B91C1C") if on else ("#0EA5E9", "#0284C7")
        self.btn_recognize.setStyleSheet(
            f"QPushButton {{ background-color: {color}; color: white; font-weight: bold; padding: 7px 14px; border-radius: 4px; }}"
            f"QPushButton:hover {{ background-color: {hover}; }} QPushButton:disabled {{ background-color: #9CA3AF; }}")

    def start_recognition(self):
        if not self.plugin_server:
            return False
        if self._is_recognizing():
            return True
        ok = self.plugin_server.start()
        if ok:
            self._log("🔌 已开启识别：已打开 Flow 页面的浏览器插件会在约 5~10 秒内自动连接。")
        else:
            QMessageBox.warning(self, "开启失败", "无法开启识别：端口 18188 / 8000 / 8765 均被占用。\n请关闭占用端口的程序或重启 FlowCue 后重试。")
        self._update_recognize_btn()
        self._schedule_refresh()
        try:
            self.mw.update_plugin_status_ui()
        except Exception:
            pass
        return ok

    def stop_recognition(self):
        if not self._is_recognizing():
            return
        if self.running or self.upload_timer.isActive():
            r = QMessageBox.question(self, "确认停止识别",
                                     "全局托管任务正在进行中，停止识别后软件将无法继续接收各浏览器的进度。\n\n"
                                     "（浏览器里已开始的任务会继续执行）\n\n确定要停止识别吗？")
            if r != QMessageBox.StandardButton.Yes:
                return
        if self.cruise_active:
            self.stop_cruise(finished_naturally=False)
        self.plugin_server.stop()
        self._log("⏹ 已停止识别：所有浏览器插件已断开并回到休眠状态（手动模式不受影响）。")
        self._update_recognize_btn()
        self._schedule_refresh()
        try:
            self.mw.update_plugin_status_ui()
        except Exception:
            pass

    def on_toggle_recognition(self):
        if self._is_recognizing():
            self.stop_recognition()
        else:
            self.start_recognition()

    # ──────────────────────────────── 步骤 1
    def on_refresh_points(self):
        if not self._is_recognizing():
            if not self.start_recognition():
                return
            self.btn_refresh.setEnabled(False)
            self._log("⏳ 正在等待浏览器插件连接（约 10 秒），连接后自动读取积分...")
            QTimer.singleShot(10000, self._refresh_points_after_connect)
            return
        self._refresh_points_after_connect()

    def _refresh_points_after_connect(self):
        self.btn_refresh.setEnabled(True)
        if not self._clients():
            QMessageBox.information(self, "提示", "当前没有已连接的浏览器。\n请确认浏览器已打开 Google Flow 项目页面，并已安装最新插件。")
            return
        n = self.plugin_server.query_all_clients_points()
        self._log(f"已向 {n} 个浏览器发送读取积分指令...")
        self.btn_refresh.setEnabled(False)
        QTimer.singleShot(5000, lambda: (self.btn_refresh.setEnabled(True), self.refresh_all(), self._log_marks()))

    def _log_marks(self):
        low = [c for c in self._clients() if self._is_low(c)]
        unk = [c for c in self._clients() if not c.get("points_known")]
        if low:
            self._log(f"🔴 已标记 {len(low)} 个低于 {self.threshold} 积分的浏览器（分配时会优先为它们量身打包能完成的任务）："
                      + "、".join(f"{self._label(c)}={c.get('remaining_points')}" for c in low))
        if unk:
            self._log(f"⚪ {len(unk)} 个浏览器未读取到积分，分配时会被跳过")

    def on_close_marked(self):
        self._flush_pending_settings()
        low = [c for c in self._clients() if self._is_low(c)]
        if not low:
            QMessageBox.information(self, "提示", f"没有积分低于 {self.threshold} 的浏览器（请先刷新积分）。")
            return
        busy_cids = {c["client_id"] for c in low if c.get("client_id") in self.plan and self.plan[c["client_id"]]["batch_ids"]}
        items = []
        for c in low:
            cid = c.get("client_id")
            email = self._email(c)
            items.append({
                "client": c,
                "client_id": cid,
                "label": self._label(c),
                "points": c.get("remaining_points", 0),
                "is_busy": cid in busy_cids,
            })

        from views.close_confirm_dialog import CloseConfirmDialog
        from PyQt6.QtWidgets import QDialog
        dlg = CloseConfirmDialog(
            self,
            title="确认关闭低积分浏览器",
            header_text=f"将关闭以下 {len(low)} 个低积分浏览器（阈值：<{self.threshold} 积分）：",
            items=items,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        selected = dlg.get_selected_clients()
        if not selected:
            return

        for c in selected:
            email = self._email(c)
            self._request_close(c["client_id"], f"{self._label(c)}（{c.get('remaining_points')} 积分）", email)
        self._log(f"已发送关闭指令给 {len(selected)} 个低积分浏览器")

    def _busy(self):
        return self.running or self.upload_group_active or bool(self.upload_queue)

    def on_clear_plan(self):
        if self._busy():
            QMessageBox.warning(self, "提示", "正在上传或生成中，请先停止。")
            return
        self.batches, self.plan = [], {}
        self._schedule_refresh()
        self._log("已清空分配")

    # ──────────────────────────────────────────
    # 批量清空：Flow 媒体 / 插件任务
    # ──────────────────────────────────────────
    def _label_for_client_id(self, client_id):
        for c in self._clients():
            if c.get("client_id") == client_id:
                return self._label(c)
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

    # ──────────────────────────────────────────
    # 关闭浏览器（定位该账号的 Chrome 窗口 → 精准关闭）
    # ──────────────────────────────────────────
    def _request_close(self, client_id, label, email=""):
        self._log(f"⚡ 正在向插件发送精准关闭指令: {label}")
        import uuid
        token = "FLOWCLOSE-" + uuid.uuid4().hex[:10]
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
