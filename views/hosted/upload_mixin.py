# -*- coding: utf-8 -*-
"""步骤 2：分组上传图片、失败重传 / 翻转，以及插件 RPC 响应处理。

由 HostedModeWidget 通过多重继承组合使用，方法内的 self 即 HostedModeWidget 实例。"""
from views.hosted.common import *  # noqa: F401,F403
from views.hosted.common import logger  # noqa: F401


class UploadMixin:
    # ──────────────────────────────── 步骤 2：分组上传
    def start_upload(self, retry_only):
        self._flush_pending_settings()
        if self._busy():
            QMessageBox.warning(self, "提示", "正在上传或生成中，请稍候。")
            return
        if not self.plan:
            QMessageBox.information(self, "提示", "请先完成步骤 1 的任务分配。")
            return
        if hasattr(self, "_sync_latest_project_presets"):
            self._sync_latest_project_presets(self.batches)
        jobs = []   # [(entry, paths)]
        missing_local = 0
        for cid, entry in self.plan.items():
            paths = []
            for b in self.batches:
                if b["id"] not in entry["batch_ids"] or b["run_state"] in ("完成", "生成中", "已发送"):
                    continue
                if retry_only:
                    if b["upload_state"] != "失败":
                        continue
                    targets = list(b["upload_failed"].keys())
                else:
                    if b["upload_state"] == "成功":
                        continue
                    targets = b["images"]
                    if not targets:
                        b["upload_state"] = "成功"
                        continue
                # 本地文件不存在的直接判失败
                ok_targets = []
                for p in targets:
                    if Path(p).exists():
                        ok_targets.append(p)
                    else:
                        b["upload_failed"][p] = "本地文件不存在"
                        b["upload_state"] = "失败"
                        missing_local += 1
                for p in ok_targets:
                    if p not in paths:
                        paths.append(p)
                if ok_targets:
                    b["upload_state"] = "上传中"
            if paths:
                jobs.append((entry, paths))
        if missing_local:
            self._log(f"❌ {missing_local} 张图片在本地不存在，已标记为失败")
        if not jobs:
            self._schedule_refresh()
            QMessageBox.information(self, "提示", "没有需要上传的图片。" if not retry_only else "没有上传失败的图片。")
            return

        g = self.spin_group.value()
        self.upload_queue = [jobs[i:i + g] for i in range(0, len(jobs), g)]
        self._log(f"📤 开始上传：{len(jobs)} 个浏览器，分 {len(self.upload_queue)} 组（每组 {g} 个）")
        self._schedule_refresh()
        self._start_next_group()
        self.upload_timer.start()

    def _start_next_group(self):
        self.upload_pending = {}
        if not self.upload_queue:
            self.upload_group_active = False
            self.upload_timer.stop()
            self._finish_upload_summary()
            return
        group = self.upload_queue.pop(0)
        timeout = self.spin_timeout.value()
        max_imgs = 0
        for entry, paths in group:
            c = self._resolve_client(entry)
            if not c:
                self._mark_upload_result(entry, [], paths, {p: "浏览器未连接" for p in paths})
                continue
            req = self.plugin_server.send_rpc_action(c["client_id"], "upload_images",
                                                     {"paths": paths, "timeout_seconds": timeout})
            if req:
                self.upload_pending[req] = {"entry": entry, "paths": paths}
                max_imgs = max(max_imgs, len(paths))
                self._log(f"   → {self._label(entry)}：上传 {len(paths)} 张")
            else:
                self._mark_upload_result(entry, [], paths, {p: "发送上传指令失败" for p in paths})
        self.upload_group_active = True
        # 插件端确认超时 = timeout；这里额外留出拖放耗时（每 10 张约 2 秒）+ 余量
        self.upload_group_deadline = time.time() + timeout + 3 * ((max_imgs + 9) // 10) + 10
        if not self.upload_pending:
            QTimer.singleShot(0, self._start_next_group)
        self._schedule_refresh()

    def _upload_tick(self):
        if not self.upload_group_active:
            return
        if not self.upload_pending:
            self._start_next_group()
            return
        if time.time() > self.upload_group_deadline:
            for req, job in list(self.upload_pending.items()):
                self._log(f"⏱️ {self._label(job['entry'])} 上传超时，强制进入下一组")
                self._mark_upload_result(job["entry"], [], job["paths"], {p: "上传超时（浏览器无响应）" for p in job["paths"]})
            self.upload_pending = {}
            self._start_next_group()

    def _mark_upload_result(self, entry, ok_paths, failed_paths, errors):
        ok_set = set(ok_paths)
        for b in self.batches:
            if b["id"] not in entry["batch_ids"]:
                continue
            touched = False
            for p in b["images"]:
                if p in ok_set:
                    b["upload_failed"].pop(p, None)
                    touched = True
                elif p in failed_paths:
                    b["upload_failed"][p] = errors.get(p) or errors.get("_all") or "上传失败"
                    touched = True
            if touched or b["upload_state"] == "上传中":
                b["upload_state"] = "失败" if b["upload_failed"] else "成功"
        self._schedule_refresh()

    def _finish_upload_summary(self):
        ok = sum(1 for b in self.batches if b["upload_state"] == "成功")
        bad = [b for b in self.batches if b["upload_state"] == "失败"]
        self._log(f"📤 上传结束：{ok} 批成功，{len(bad)} 批有失败图片" + ("（可点击「↔️ 一键翻转失败图片」或「🔁 重新上传失败图片」）" if bad else ""))
        for b in bad:
            self._log(f"   ❌ {b['short']}：" + "；".join(f"{Path(p).name}({r})" for p, r in b["upload_failed"].items()))
        self._schedule_refresh()

    def flip_failed_upload_images(self):
        """
        一键将所有上传失败的图片进行左右翻转：
        生成翻转后的新图片替换原来的老图片，继承原图片名称，并删除原图片文件。
        """
        if self._busy():
            QMessageBox.warning(self, "提示", "正在上传或生成中，请先停止后再翻转图片。")
            return

        failed_paths = []
        for b in self.batches:
            for p in (b.get("upload_failed") or {}).keys():
                if p and p not in failed_paths:
                    failed_paths.append(p)

        if not failed_paths:
            QMessageBox.information(self, "提示", "当前没有上传失败的图片。")
            return

        from views.project_detail_widget import flip_image_horizontally_replace, encode_image_to_data_url

        # 若当前打开的项目正显示预览图，先清空引用以免占用文件句柄
        detail = getattr(self.mw, "detail_widget", None)
        if detail and hasattr(detail, "lbl_preview"):
            detail.lbl_preview.clear()

        flipped_ok = []
        flipped_err = {}
        new_data_urls = {}

        for p in failed_paths:
            try:
                flip_image_horizontally_replace(p)
                flipped_ok.append(p)
                new_data_urls[p] = encode_image_to_data_url(p)
            except Exception as e:
                flipped_err[p] = str(e)

        # 同步更新批次任务中的 Base64 数据与失败提示说明
        ok_set = set(flipped_ok)
        for b in self.batches:
            for p in list((b.get("upload_failed") or {}).keys()):
                if p in ok_set:
                    b["upload_failed"][p] = "已左右翻转（待重新上传）"
            for t in b.get("tasks") or []:
                lp = t.get("local_image_path")
                if lp in new_data_urls and new_data_urls[lp]:
                    t["image_data_url"] = new_data_urls[lp]
                    t["imageDataUrl"] = new_data_urls[lp]
                elp = t.get("end_local_image_path")
                if elp in new_data_urls and new_data_urls[elp]:
                    t["end_image_data_url"] = new_data_urls[elp]
                    t["endImageDataUrl"] = new_data_urls[elp]

        # 同步刷新项目管理资源面板（若已打开）
        if detail and getattr(detail, "project_path", None):
            try:
                detail.refresh_media_list()
                detail.on_media_selection_changed(detail.list_media.currentItem(), None)
            except Exception:
                pass

        self._schedule_refresh()

        if flipped_ok:
            names_str = "、".join(Path(p).name for p in flipped_ok)
            self._log(f"↔️ 已左右翻转并替换 {len(flipped_ok)} 张失败图片：{names_str}")
        if flipped_err:
            err_str = "；".join(f"{Path(p).name}({r})" for p, r in flipped_err.items())
            self._log(f"❌ 有 {len(flipped_err)} 张图片翻转失败：{err_str}")

        if flipped_ok:
            err_note = f"\n\n⚠️ 另有 {len(flipped_err)} 张翻转失败：\n" + "\n".join(
                f"{Path(p).name}: {r}" for p, r in list(flipped_err.items())[:8]
            ) if flipped_err else ""
            reply = QMessageBox.question(
                self, "翻转完成",
                f"已成功将 {len(flipped_ok)} 张上传失败的图片左右翻转！\n"
                f"（新图片已替换并删除原图，保留原文件名）{err_note}\n\n"
                f"是否立即重新上传这些失败图片？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.start_upload(retry_only=True)
        else:
            QMessageBox.critical(
                self, "翻转失败",
                "所有失败图片翻转均未成功：\n\n" + "\n".join(f"{Path(p).name}: {r}" for p, r in list(flipped_err.items())[:10])
            )

    # ──────────────────────────────── RPC 响应
    def _on_rpc_response(self, payload):
        msg = payload.get("message") or {}
        action = msg.get("action", "")
        req = msg.get("request_id")
        if action == "upload_images_response":
            job = self.upload_pending.pop(req, None)
            data = msg.get("data") or {}
            ok_paths = list(data.get("uploaded") or []) + list(data.get("skipped") or [])
            failed = list(data.get("failed") or [])
            errors = data.get("errors") or {}
            if job:
                entry = job["entry"]
            else:
                # 超时后迟到的响应：仍然更新结果
                entry = next((e for e in self.plan.values() if e["cid"] == payload.get("client_id")), None)
                if not entry:
                    return
            self._mark_upload_result(entry, ok_paths, failed, errors)
            label = self._label(entry)
            verify = data.get("verify") or {}
            vc = {"name": 0, "count": 0, "registry": 0}
            for p in ok_paths:
                k = verify.get(p)
                if k in vc:
                    vc[k] += 1
            how = []
            if vc["name"]:
                how.append(f"按文件名确认 {vc['name']}")
            if vc["count"]:
                how.append(f"按新增图块数确认 {vc['count']}")
            if vc["registry"]:
                how.append(f"之前已确认上传 {vc['registry']}")
            if "page_images_before" in data:
                how.append(f"Flow 图片数 {data.get('page_images_before')}→{data.get('page_images_after', data.get('page_images_before'))}")
            how_txt = f"（{'；'.join(how)}）" if how else ""
            if failed:
                self._log(f"   ❌ {label}：成功 {len(ok_paths)} 张，失败 {len(failed)} 张：" + "、".join(Path(p).name for p in failed) + how_txt)
            else:
                self._log(f"   ✅ {label}：{len(ok_paths)} 张全部上传成功{how_txt}")
        elif action == "run_tasks_response":
            data = msg.get("data") or {}
            b = self._batch(data.get("batch_id"))
            if not b:
                return
            if msg.get("success"):
                b["run_state"] = "生成中"
                self._log(f"🚀 {b['short']} 已被 {self._label(b)} 接收（{data.get('count')} 个任务），开始生成")
            else:
                b["run_state"] = "发送失败"
                self._log(f"❌ {b['short']} 发送失败：{msg.get('error')}")
                QTimer.singleShot(500, lambda e=self.plan.get(b["cid"]): e and self._dispatch_next(e))
            self._schedule_refresh()
        elif action == "clear_tasks_response":
            label = self._label_for_client_id(payload.get("client_id", ""))
            data = msg.get("data", {}) or {}
            if msg.get("success"):
                self._log(f"✅ 已清空插件任务（{data.get('cleared', 0)} 个）: {label}")
            else:
                self._log(f"❌ 清空插件任务失败: {label} - {msg.get('error', '')}")
        elif action == "clear_media_response":
            label = self._label_for_client_id(payload.get("client_id", ""))
            data = msg.get("data", {}) or {}
            before, after = data.get("before", "?"), data.get("after", "?")
            if msg.get("success"):
                note = data.get("note")
                self._log(f"✅ 已清空 Flow 媒体: {label}" + (f"（{note}）" if note else f"（{before} → {after}）"))
            else:
                self._log(f"❌ 清空 Flow 媒体失败: {label} - {msg.get('error', '')}（{before} → {after}）")

    def _batch(self, bid):
        return next((b for b in self.batches if b["id"] == bid), None)
