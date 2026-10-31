# -*- coding: utf-8 -*-
"""步骤 3：同步最新预设、分批发送任务并监控生成结果。

由 HostedModeWidget 通过多重继承组合使用，方法内的 self 即 HostedModeWidget 实例。"""
from views.hosted.common import *  # noqa: F401,F403
from views.hosted.common import logger  # noqa: F401


class RunMixin:
    # ──────────────────────────────── 步骤 3：发送任务并监控
    def _sync_latest_project_presets(self, batches):
        """
        在步骤 3 发送任务前，实时从各项目的最新配置（统一提示词模板、统一运镜预设、
        片段专属模板/运镜/生成模式、修改后的分句文案）重新计算并同步每个任务的 prompt 与参数，
        同时完全保留步骤 2 已上传成功的图片状态。
        """
        import re
        from models.project_model import ProjectModel
        from services.text_processor import TextProcessor

        cm = getattr(self.mw, "config_manager", None)
        if cm:
            cm.load()
        tm = getattr(self.mw, "template_manager", None)
        detail = getattr(self.mw, "detail_widget", None)
        if detail and getattr(detail, "project_model", None):
            try:
                detail.project_model.save()
            except Exception:
                pass

        default_aspect = getattr(cm, "default_aspect_ratio", "9:16") if cm else "9:16"
        default_model = getattr(cm, "default_video_model", "omni_1_1_flash") if cm else "omni_1_1_flash"
        default_mode = getattr(cm, "default_generation_mode", "VIDEO_FRAMES") if cm else "VIDEO_FRAMES"
        task_interval = getattr(cm, "task_interval", 5) if cm else 5

        proj_cache = {}
        updated_prompts_count = 0

        for b in batches:
            proj_path_str = b.get("project_path", "")
            proj_model = None
            if proj_path_str:
                if proj_path_str not in proj_cache:
                    try:
                        p_obj = Path(proj_path_str)
                        if p_obj.exists():
                            proj_cache[proj_path_str] = ProjectModel(p_obj)
                        else:
                            proj_cache[proj_path_str] = None
                    except Exception:
                        proj_cache[proj_path_str] = None
                proj_model = proj_cache.get(proj_path_str)

            for t in b.get("tasks") or []:
                t["aspect_ratio"] = default_aspect
                t["model"] = default_model
                t["interval"] = task_interval

                seg_idx = int(t.get("segment_index", 1)) - 1
                if proj_model and 0 <= seg_idx < len(proj_model.spanish_segments):
                    seg = proj_model.spanish_segments[seg_idx]
                    raw_text = seg.get("text", "")
                    text = TextProcessor.remove_punctuation(raw_text)

                    # 解析最新模板（优先片段专属模板，否则使用项目统一模板）
                    tpl_id = seg.get("template_id", "") or getattr(proj_model, "selected_template_id", "")
                    tpl = tm.get_template(tpl_id) if (tm and tpl_id) else None

                    # 解析最新运镜（优先片段专属运镜，否则使用项目统一运镜）
                    motion_id = seg.get("motion_id", "") or getattr(proj_model, "selected_motion_id", "")
                    motion = tm.get_motion(motion_id) if (tm and motion_id) else None

                    template_content = tpl["content"] if tpl else "{spanish_text}"
                    motion_content = motion["content"] if motion else ""
                    new_prompt = template_content.replace("{spanish_text}", text)
                    new_prompt = new_prompt.replace("{camera_motion}", motion_content)
                    new_prompt = re.sub(r" +", " ", new_prompt).strip()

                    if new_prompt and t.get("prompt") != new_prompt:
                        t["prompt"] = new_prompt
                        updated_prompts_count += 1

                    # 同步片段专属生成模式或全局默认生成模式
                    if seg.get("mode_overridden") and seg.get("mode") in ("VIDEO_FRAMES", "VIDEO_REFERENCES"):
                        t["mode"] = seg.get("mode")
                        t["_mode_overridden"] = True
                    else:
                        t["mode"] = default_mode
                        t["_mode_overridden"] = False

                    if cm:
                        is_edge = (seg_idx == 0 or seg_idx == len(proj_model.spanish_segments) - 1)
                        t["duration"] = cm.get_duration_for_length(len(text), is_edge=is_edge)
                    elif seg.get("duration"):
                        t["duration"] = seg.get("duration")
                else:
                    if not t.get("_mode_overridden"):
                        t["mode"] = default_mode

            b["points"] = sum(self._points_of(t) for t in (b.get("tasks") or []))

        if updated_prompts_count > 0:
            self._log(f"🔄 已自动同步「项目管理」中最新修改的预设提示词（共更新 {updated_prompts_count} 条任务）")
        return updated_prompts_count

    def _confirm_step3_dialog(self, ready, active_entries, g_size, wait_sec):
        """弹出步骤 3 启动前确认框：展示尺寸（16:9 爆红提醒）、模型、模式、账号数、总消耗积分及分批策略。"""
        from PyQt6.QtWidgets import QDialog, QFrame
        from models.config_manager import ConfigManager

        cm = getattr(self.mw, "config_manager", None)
        if cm:
            cm.load()

        default_aspect = getattr(cm, "default_aspect_ratio", "9:16") if cm else "9:16"
        default_model = getattr(cm, "default_video_model", "omni_1_1_flash") if cm else "omni_1_1_flash"
        default_mode = getattr(cm, "default_generation_mode", "VIDEO_FRAMES") if cm else "VIDEO_FRAMES"
        task_interval = getattr(cm, "task_interval", 5) if cm else 5

        # 实时同步各项目最新预设提示词、生成模式及全局规则到即将发送的批次任务中
        self._sync_latest_project_presets(ready)

        modes_used = set()
        for b in ready:
            for t in b.get("tasks") or []:
                modes_used.add(t.get("mode", default_mode))

        aspect_map = dict(getattr(ConfigManager, "SUPPORTED_ASPECT_RATIOS", [("9:16", "9:16 (竖屏)"), ("16:9", "16:9 (横屏)")]))
        model_map = dict(getattr(ConfigManager, "SUPPORTED_VIDEO_MODELS", []))
        mode_map = dict(getattr(ConfigManager, "SUPPORTED_GENERATION_MODES", []))

        aspect_label = aspect_map.get(default_aspect, default_aspect)
        model_label = model_map.get(default_model, default_model)
        if len(modes_used) > 1:
            mode_label = " + ".join(mode_map.get(m, m) for m in sorted(modes_used))
        else:
            single_mode = next(iter(modes_used), default_mode)
            mode_label = mode_map.get(single_mode, single_mode)

        is_16_9 = (default_aspect == "16:9")
        account_count = len(active_entries)
        batch_count = len(ready)
        task_count = sum(len(b.get("tasks") or []) for b in ready)
        total_points = sum(b.get("points", 0) for b in ready)
        num_groups = (account_count + g_size - 1) // g_size if account_count > 0 else 1

        dlg = QDialog(self)
        dlg.setWindowTitle("🚀 确认执行 步骤3：发送任务并开始生成")
        dlg.setMinimumWidth(520)
        dlg.setStyleSheet("""
            QDialog {
                background-color: #FAF6F0;
                color: #3E2723;
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
            }
            QLabel {
                font-size: 13px;
                color: #3E2723;
            }
        """)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title_lbl = QLabel("请核对本次全局托管生成的参数配置与消耗信息：")
        title_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #5D4037;")
        layout.addWidget(title_lbl)

        # 如果尺寸是 16:9，顶部显示爆红警告横幅（仅提醒，不阻止运行）
        if is_16_9:
            warn_box = QLabel(
                "🚨 【爆红提醒】当前画幅尺寸为 16:9（横屏）！\n"
                "请仔细确认本次任务是否确实需要生成 16:9 横屏视频！\n"
                "（若确认需要 16:9 可直接点击下方「确认开始」；如需改为 9:16 请点击「取消」前往系统规则设置修改）"
            )
            warn_box.setWordWrap(True)
            warn_box.setStyleSheet("""
                QLabel {
                    background-color: #FEE2E2;
                    color: #DC2626;
                    border: 2px solid #DC2626;
                    border-radius: 6px;
                    padding: 10px 12px;
                    font-size: 13px;
                    font-weight: bold;
                }
            """)
            layout.addWidget(warn_box)

        # 参数详情卡片
        card = QFrame(dlg)
        card.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #D7CCC8;
                border-radius: 6px;
            }
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(8)

        def add_info_row(label_text, value_text, highlight_red=False, highlight_color=None):
            row = QHBoxLayout()
            k_lbl = QLabel(label_text)
            k_lbl.setFixedWidth(135)
            k_lbl.setStyleSheet("font-weight: bold; color: #5D4037; border: none;")
            v_lbl = QLabel(value_text)
            v_lbl.setWordWrap(True)
            if highlight_red:
                v_lbl.setStyleSheet(
                    "background-color: #FEE2E2; color: #DC2626; font-weight: 900; "
                    "font-size: 15px; padding: 4px 8px; border: 1.5px solid #DC2626; border-radius: 4px;"
                )
            elif highlight_color:
                v_lbl.setStyleSheet(f"color: {highlight_color}; font-weight: bold; font-size: 14px; border: none;")
            else:
                v_lbl.setStyleSheet("color: #1E293B; font-weight: bold; font-size: 13px; border: none;")
            row.addWidget(k_lbl)
            row.addWidget(v_lbl, stretch=1)
            card_layout.addLayout(row)

        add_info_row(
            "📐 当前画幅尺寸：",
            f"🚨 {aspect_label} 【当前为16:9横屏，请重点核对！】" if is_16_9 else f"✅ {aspect_label}",
            highlight_red=is_16_9,
            highlight_color="#15803D" if not is_16_9 else None
        )
        add_info_row("🤖 当前生成模型：", model_label, highlight_color="#1D4ED8")
        add_info_row("🎬 当前生成模式：", mode_label, highlight_color="#7C3AED")
        add_info_row("👤 执行浏览器账号：", f"{account_count} 个账号（共 {batch_count} 批 / {task_count} 条视频任务）", highlight_color="#0F766E")
        add_info_row("⚡ 预计总消耗积分：", f"共 {total_points} 积分", highlight_color="#D97706")

        if num_groups > 1:
            batch_policy_str = f"每批运行 {g_size} 个浏览器（共 {num_groups} 批），间隔等待 {wait_sec} 秒后自动启动下一批"
        else:
            batch_policy_str = f"每批运行 {g_size} 个浏览器（共 1 批，立即全部启动）"
        add_info_row("⏱️ 分批执行策略：", batch_policy_str)

        layout.addWidget(card)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = self._btn("❌ 取消", "#6B7280", "#4B5563")
        btn_cancel.clicked.connect(dlg.reject)
        btn_ok = self._btn("✅ 确认开始", "#16A34A", "#15803D")
        btn_ok.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)

        return dlg.exec() == QDialog.DialogCode.Accepted

    def start_run(self):
        self._flush_pending_settings()
        if self.running:
            QMessageBox.information(self, "提示", "步骤 3 正在运行中，如需重新开始请先点击「⏹ 停止」。")
            return
        if self.upload_group_active or self.upload_queue:
            QMessageBox.warning(self, "提示", "图片还在上传中，请等待上传结束。")
            return
        if not self.plan:
            QMessageBox.information(self, "提示", "请先完成步骤 1 的任务分配。")
            return
        ready = [b for b in self.batches if b["cid"] and b["upload_state"] == "成功" and b["run_state"] in ("未开始", "发送失败", "连接断开")]
        not_ready = [b for b in self.batches if b["cid"] and b["upload_state"] != "成功" and b["run_state"] == "未开始"]
        if not ready:
            QMessageBox.information(self, "提示", "没有可以发送的批次。\n\n只有图片全部上传成功的批次才会发送（请先完成步骤 2）。")
            return
        if not_ready:
            names = "、".join(b["short"] for b in not_ready[:6])
            if QMessageBox.question(self, "部分批次图片未上传成功",
                                    f"有 {len(not_ready)} 批图片未全部上传成功，将暂不发送：\n{names}\n\n是否先发送其余 {len(ready)} 批？",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.Yes) != QMessageBox.StandardButton.Yes:
                return

        ready_cids = {b["cid"] for b in ready}
        active_entries = [entry for entry in self.plan.values() if entry["cid"] in ready_cids]
        g_size = self.spin_run_group.value()
        wait_sec = self.spin_run_wait.value()

        # 弹窗确认尺寸（16:9 爆红提醒）、模型、模式、账号数与总消耗积分
        if not self._confirm_step3_dialog(ready, active_entries, g_size, wait_sec):
            self._log("⏹ 用户取消了步骤 3 启动")
            return

        for b in ready:
            if b["run_state"] != "未开始":
                b["run_state"] = "未开始"

        self.running = True
        self.run_browser_queue = [active_entries[i:i + g_size] for i in range(0, len(active_entries), g_size)]
        self.run_total_groups = len(self.run_browser_queue)
        self.run_current_group_idx = 0
        self.run_released_cids = set()
        self.run_next_group_deadline = 0

        total_pts = sum(b.get("points", 0) for b in ready)
        self._log(
            f"🚀 步骤3 开始：{len(ready)} 批任务（共 {total_pts} 积分）将发送到 {len(active_entries)} 个浏览器，"
            f"分 {self.run_total_groups} 批启动（每批 {g_size} 个，间隔等待 {wait_sec} 秒）"
        )
        self._start_next_run_group()
        self._schedule_refresh()

    def _start_next_run_group(self):
        if not self.running or not self.run_browser_queue:
            self.run_group_timer.stop()
            if self.running and self.run_total_groups > 1:
                self.lbl_run_group_status.setText(f"✅ 全部 {self.run_total_groups} 批浏览器已启动")
            else:
                self.lbl_run_group_status.setText("")
            return

        group = self.run_browser_queue.pop(0)
        self.run_current_group_idx += 1
        for entry in group:
            self.run_released_cids.add(entry["cid"])

        self._log(
            f"🚀 步骤3 第 {self.run_current_group_idx}/{self.run_total_groups} 批启动："
            f"正在向本批 {len(group)} 个浏览器发送任务..."
        )
        for entry in group:
            self._dispatch_next(entry)

        if self.run_browser_queue:
            wait_sec = self.spin_run_wait.value()
            self.run_next_group_deadline = time.time() + wait_sec
            next_count = len(self.run_browser_queue[0])
            self._log(
                f"⏳ 将等待 {wait_sec} 秒后（无论本批是否完成）自动启动第 "
                f"{self.run_current_group_idx + 1}/{self.run_total_groups} 批（{next_count} 个浏览器）..."
            )
            self.lbl_run_group_status.setText(
                f"⏳ 已启动第 {self.run_current_group_idx}/{self.run_total_groups} 批 · 距下一批启动还有 {wait_sec} 秒"
            )
            if not self.run_group_timer.isActive():
                self.run_group_timer.start()
        else:
            self.run_group_timer.stop()
            if self.run_total_groups > 1:
                self.lbl_run_group_status.setText(f"✅ 全部 {self.run_total_groups} 批浏览器已启动")
            else:
                self.lbl_run_group_status.setText("")
        self._schedule_refresh()

    def _run_group_tick(self):
        if not self.running or not self.run_browser_queue:
            self.run_group_timer.stop()
            return
        rem = int(round(self.run_next_group_deadline - time.time()))
        if rem <= 0:
            self._log(f"⏰ 等待时间已到，开始启动下一批浏览器（无论上一批是否完成）...")
            self._start_next_run_group()
        else:
            self.lbl_run_group_status.setText(
                f"⏳ 已启动第 {self.run_current_group_idx}/{self.run_total_groups} 批 · 距下一批启动还有 {rem} 秒"
            )

    def _dispatch_next(self, entry):
        if not self.running:
            return
        if self.run_released_cids and entry["cid"] not in self.run_released_cids:
            return   # 该浏览器所属批次尚未到达启动时间
        mine = [b for b in self.batches if b["id"] in entry["batch_ids"]]
        if any(b["run_state"] in ("已发送", "生成中") for b in mine):
            return   # 该浏览器还在跑上一批
        nxt = next((b for b in mine if b["run_state"] == "未开始" and b["upload_state"] == "成功"), None)
        if not nxt:
            self._check_all_done()
            return
        c = self._resolve_client(entry)
        if not c:
            nxt["run_state"] = "连接断开"
            self._log(f"❌ {self._label(entry)} 未连接，{nxt['short']} 无法发送")
            self._schedule_refresh()
            return
        nxt["run_state"] = "已发送"
        self._sync_latest_project_presets([nxt])
        clean_tasks = [{k: v for k, v in t.items() if not k.startswith("_")} for t in nxt["tasks"]]
        req = self.plugin_server.send_rpc_action(c["client_id"], "run_tasks",
                                                 {"batch_id": nxt["id"], "tasks": clean_tasks, "clear_existing": True})
        if not req:
            nxt["run_state"] = "发送失败"
        else:
            self._log(f"📨 已发送 {nxt['short']}（{len(clean_tasks)} 个任务）→ {self._label(entry)}")
        self._schedule_refresh()

    def _on_hosted_event(self, payload):
        msg = payload.get("message") or {}
        b = self._batch(msg.get("batch_id"))
        if not b:
            return
        if payload.get("type") == "hosted_task_status":
            if msg.get("status") == "success":
                self._record_success(b, msg.get("download_path", ""))
            self._schedule_refresh()
            return

        # hosted_batch_finished —— 以插件最终报告为准
        for r in msg.get("results") or []:
            dp = r.get("download_path", "")
            if r.get("status") == "success":
                self._record_success(b, dp)
            elif dp not in b["done_paths"]:
                b["fail_msgs"][dp] = r.get("message") or "失败"
        b["ok"] = len(b["done_paths"])
        b["fail"] = len([k for k in b["fail_msgs"] if k not in b["done_paths"]])
        b["run_state"] = "完成"
        self._log(f"🏁 {b['short']} 完成：✅ 成功 {b['ok']}，❌ 失败 {b['fail']}"
                  + (("：" + "、".join(Path(k).name for k in b["fail_msgs"] if k not in b["done_paths"])) if b["fail"] else "")
                  + ("（插件被手动停止）" if msg.get("stopped") else ""))
        self._after_project_change(b["project_path"], reload_list=True)
        entry = self.plan.get(b["cid"])
        self._schedule_refresh()
        if entry:
            QTimer.singleShot(1500, lambda e=entry: self._dispatch_next(e))

    def _record_success(self, b, dl_path):
        if not dl_path or dl_path in b["done_paths"]:
            return
        b["done_paths"].add(dl_path)
        b["fail_msgs"].pop(dl_path, None)
        b["ok"] = len(b["done_paths"])
        name = Path(dl_path).name
        self._log(f"   🎬 视频已下载: {name}（保留在 Flow 目录，待后续批量检查归位）")

    def _after_project_change(self, project_path, reload_list=False):
        try:
            d = self.mw.detail_widget
            if d.project_path and str(d.project_path) == str(project_path):
                d.populate_segments_table()
            if reload_list:
                QTimer.singleShot(300, self.mw.reload_projects_list)
        except Exception as e:
            logger.warning(f"刷新项目界面失败: {e}")

    def _check_all_done(self):
        if not self.running:
            return
        if self.run_browser_queue:
            return
        active = [b for b in self.batches if b["run_state"] in ("已发送", "生成中")]
        waiting = [b for b in self.batches if b["cid"] and b["run_state"] == "未开始" and b["upload_state"] == "成功"]
        if active or waiting:
            return
        self.running = False
        self.run_group_timer.stop()
        self.lbl_run_group_status.setText("")
        ok = sum(b["ok"] for b in self.batches)
        fail = sum(b["fail"] for b in self.batches)
        self._log(f"🎉 全部批次执行结束：✅ 成功 {ok} 个视频，❌ 失败 {fail} 个。"
                  + ("失败的分句可再次点击「分配」重新生成（已成功的会自动排除）" if fail else ""))
        self._schedule_refresh()

    def stop_run(self):
        stopped_upload = bool(self.upload_queue or self.upload_group_active)
        self.upload_queue = []
        if stopped_upload:
            for job in self.upload_pending.values():
                self._mark_upload_result(job["entry"], [], job["paths"], {p: "已手动停止" for p in job["paths"]})
            self.upload_pending = {}
            self.upload_group_active = False
            self.upload_timer.stop()
            self._log("⏹ 已停止上传")
        if self.running or self.run_browser_queue:
            self.running = False
            self.run_browser_queue = []
            self.run_group_timer.stop()
            self.lbl_run_group_status.setText("")
            for b in self.batches:
                if b["run_state"] in ("已发送", "生成中"):
                    c = self._resolve_client(self.plan.get(b["cid"], {"cid": b["cid"], "email": b["email"]}))
                    if c:
                        self.plugin_server.send_rpc_action(c["client_id"], "stop_tasks", {})
            self._log("⏹ 已停止派发，并通知正在生成的插件停止（已提交到 Flow 的不会取消）")
        self._schedule_refresh()

    def _on_client_disconnected(self, client_id):
        for b in self.batches:
            if b.get("cid") == client_id and b["run_state"] in ("已发送", "生成中"):
                b["run_state"] = "连接断开"
                self._log(f"⚠️ {self._label(b)} 断开连接，{b['short']} 中断（重新连接后可再次点击步骤3继续）")
        self._schedule_refresh()
        QTimer.singleShot(200, self._check_all_done)
