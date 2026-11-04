# -*- coding: utf-8 -*-
"""全局巡航（单次 / 循环依次展开唤醒浏览器窗口）。

由 HostedModeWidget 通过多重继承组合使用，方法内的 self 即 HostedModeWidget 实例。"""
from views.hosted.common import *  # noqa: F401,F403
from views.hosted.common import logger  # noqa: F401


class CruiseMixin:
    # ──────────────────────────────── 全局巡航（单次巡航 / 循环巡航）
    def _get_client_assigned_batches(self, c):
        """获取指定浏览器 c 已分配的所有批次列表。"""
        if not c:
            return []
        cid = c.get("client_id", "")
        iid = self._iid(c)
        batch_ids = set()

        entry = self.plan.get(cid)
        if not entry and iid:
            for e in self.plan.values():
                if self._iid(e) == iid:
                    entry = e
                    break
        if entry:
            batch_ids.update(entry.get("batch_ids") or [])

        result = []
        for b in getattr(self, "batches", []):
            if b.get("id") in batch_ids or (cid and b.get("cid") == cid):
                result.append(b)
        return result

    def _is_client_executing_task(self, c) -> bool:
        """
        判断浏览器 c 是否「已分配任务且任务正在执行中」：
        - 未分配任务的浏览器 -> False（不打开）
        - 已分配任务但全部显示已完成的浏览器 -> False（不打开）
        - 已分配任务但还没开始的浏览器 -> False（不打开）
        - 仅当存在正在执行中的任务（生成状态为「已发送」/「生成中」，或图片状态为「上传中」）-> True（需要打开）
        """
        assigned = self._get_client_assigned_batches(c)
        if not assigned:
            return False
        for b in assigned:
            run_st = b.get("run_state", "未开始")
            up_st = b.get("upload_state", "未上传")
            if run_st in ("已发送", "生成中") or up_st == "上传中":
                return True
        return False

    def _get_cruise_target_clients(self):
        """获取需要巡航展开的浏览器列表：仅包含已分配任务且正在执行中的主标签页浏览器。"""
        clients = self._clients()
        primary = [c for c in clients if not c.get("secondary_tab")]
        candidates = primary if primary else clients
        return [c for c in candidates if self._is_client_executing_task(c)]

    def _update_cruise_buttons(self):
        if not hasattr(self, "btn_cruise_once"):
            return
        self.btn_cruise_once.setEnabled(not self.cruise_active)
        self.btn_cruise_loop.setEnabled(not self.cruise_active)
        self.btn_cruise_stop.setEnabled(self.cruise_active)
        if self.cruise_active and self.cruise_loop_mode:
            self.btn_cruise_loop.setText("🔁 循环巡航运行中...")
        else:
            self.btn_cruise_loop.setText("🔁 开启循环巡航")

    def start_cruise(self, loop_mode=False):
        self._flush_pending_settings()
        """启动单次巡航或循环巡航：依次将每个正在执行任务的浏览器窗口展开并切到画面最上面。"""
        if self.cruise_active:
            self.stop_cruise(finished_naturally=False)

        if not self._is_recognizing():
            if not self.start_recognition():
                return

        if not self._clients():
            QMessageBox.information(
                self,
                "提示",
                "当前没有已连接的浏览器。\n\n请确认已打开 Google Flow 页面，且上方「开始识别浏览器」已开启（开启后约 5~10 秒自动连接）。"
            )
            return

        targets = self._get_cruise_target_clients()
        if not targets:
            QMessageBox.information(
                self,
                "提示",
                "当前没有正在执行任务的浏览器。\n\n"
                "💡 巡航功能仅会展开【已分配任务且任务正在执行中（上传中 / 已发送 / 生成中）】的浏览器；\n"
                "未分配任务、尚未开始执行或已全部完成的浏览器均不会打开。"
            )
            return

        self.cruise_active = True
        self.cruise_loop_mode = bool(loop_mode)
        self.cruise_round = 1
        self.cruise_queue = list(targets)
        self.cruise_total_in_round = len(self.cruise_queue)
        self.cruise_current_idx = 0
        self.cruise_waiting_next_round = False
        self.cruise_next_round_deadline = 0
        self._update_cruise_buttons()

        dwell = self.spin_cruise_dwell.value()
        if self.cruise_loop_mode:
            interval_min = self.spin_cruise_interval.value()
            self._log(
                f"🔁 开启全局循环巡航：共 {self.cruise_total_in_round} 个正在执行任务的浏览器，每个停留 {dwell:g} 秒，"
                f"每轮结束后等待 {interval_min:g} 分钟自动进行下一轮（直至点击「⏹ 停止巡航」）"
            )
        else:
            self._log(f"🧭 开始单次巡航：共 {self.cruise_total_in_round} 个正在执行任务的浏览器，每个停留 {dwell:g} 秒...")

        self._cruise_step()

    def stop_cruise(self, finished_naturally=False):
        """停止全局巡航（单次或循环）。"""
        was_active = self.cruise_active
        was_loop = self.cruise_loop_mode
        self.cruise_active = False
        self.cruise_loop_mode = False
        self.cruise_queue = []
        self.cruise_waiting_next_round = False
        self.cruise_step_timer.stop()
        self.cruise_wait_timer.stop()
        self._update_cruise_buttons()
        if not finished_naturally and was_active:
            mode_str = "循环巡航" if was_loop else "单次巡航"
            self.lbl_cruise_status.setText(f"⏹ 已停止{mode_str}")
            self._log(f"⏹ 用户已手动停止{mode_str}")

    def _cruise_step(self):
        """展开当前轮队列中的下一个正在执行任务的浏览器窗口，并在停留指定秒数后继续下一个。"""
        if not self.cruise_active:
            return

        # 跳过在排队期间已经执行完成或不再处于执行状态的浏览器
        c = None
        while self.cruise_queue:
            candidate = self.cruise_queue.pop(0)
            if self._is_client_executing_task(candidate):
                c = candidate
                break

        if c is None:
            # 本轮所有正在执行任务的浏览器已全部展开完毕
            if not self.cruise_loop_mode:
                total = self.cruise_current_idx
                self._log(f"✅ 单次巡航完成：已依次展开全部 {total} 个正在执行任务的浏览器窗口！")
                self.lbl_cruise_status.setText(f"✅ 单次巡航已完成（共展开 {total} 个执行中浏览器）")
                self.stop_cruise(finished_naturally=True)
                return

            # 循环巡航模式：进入轮次等待倒计时
            wait_min = self.spin_cruise_interval.value()
            wait_sec = max(5.0, wait_min * 60.0)
            self.cruise_waiting_next_round = True
            self.cruise_next_round_deadline = time.time() + wait_sec
            self._log(
                f"✅ 循环巡航第 {self.cruise_round} 轮完成（已展开 {self.cruise_current_idx} 个执行中浏览器），"
                f"将等待 {wait_min:g} 分钟后自动开始第 {self.cruise_round + 1} 轮巡航..."
            )
            self._cruise_wait_tick()
            if not self.cruise_wait_timer.isActive():
                self.cruise_wait_timer.start()
            return

        self.cruise_current_idx += 1
        cid = c.get("client_id", "")
        label = self._label(c)
        dwell = max(0.1, float(self.spin_cruise_dwell.value()))

        # 在浏览器表格中高亮当前正在巡航的浏览器行
        cids = getattr(self, "_browser_row_cids", [])
        if cid in cids:
            row_idx = cids.index(cid)
            self.tbl_browsers.selectRow(row_idx)

        if self.plugin_server and cid:
            self.plugin_server.cruise_activate_client(cid)

        prefix = f"🔁 循环巡航(第{self.cruise_round}轮)" if self.cruise_loop_mode else "🧭 单次巡航"
        self.lbl_cruise_status.setText(
            f"{prefix}：[{self.cruise_current_idx}/{self.cruise_total_in_round}] 正在展开 {label}（停留 {dwell:g}s）"
        )
        self._log(f"{prefix} [{self.cruise_current_idx}/{self.cruise_total_in_round}] → 已展开浏览器：{label}")

        self.cruise_step_timer.start(max(100, int(round(dwell * 1000))))

    def _cruise_wait_tick(self):
        """循环巡航轮次间的倒计时检查，倒计时结束自动开启下一轮。"""
        if not self.cruise_active or not self.cruise_loop_mode or not self.cruise_waiting_next_round:
            self.cruise_wait_timer.stop()
            return

        rem = int(round(self.cruise_next_round_deadline - time.time()))
        if rem <= 0:
            self.cruise_wait_timer.stop()
            self.cruise_waiting_next_round = False
            targets = self._get_cruise_target_clients()
            if not targets:
                assigned_batches = [b for b in getattr(self, "batches", []) if b.get("cid")]
                if (
                    assigned_batches
                    and not getattr(self, "running", False)
                    and not getattr(self, "upload_group_active", False)
                    and all(b.get("run_state") == "完成" for b in assigned_batches)
                ):
                    self._log("✅ 循环巡航结束：所有已分配任务的浏览器均已执行完成，自动停止循环巡航。")
                    self.lbl_cruise_status.setText("✅ 所有分配任务已全部完成，循环巡航已自动结束")
                    self.stop_cruise(finished_naturally=True)
                    return

                # 若暂时无正在执行任务的浏览器（例如正在等待下一批发送），再等 10 秒探测
                self.lbl_cruise_status.setText("🔁 循环巡航：当前暂无正在执行任务的浏览器，10 秒后继续检测...")
                self.cruise_waiting_next_round = True
                self.cruise_next_round_deadline = time.time() + 10
                self.cruise_wait_timer.start()
                return

            self.cruise_round += 1
            self.cruise_queue = list(targets)
            self.cruise_total_in_round = len(self.cruise_queue)
            self.cruise_current_idx = 0
            dwell = self.spin_cruise_dwell.value()
            self._log(
                f"🔁 循环巡航第 {self.cruise_round} 轮开始：共 {self.cruise_total_in_round} 个正在执行任务的浏览器（每个停留 {dwell:g} 秒）..."
            )
            self._cruise_step()
        else:
            mins, secs = divmod(rem, 60)
            time_str = f"{mins:02d}分{secs:02d}秒" if mins > 0 else f"{secs}秒"
            self.lbl_cruise_status.setText(
                f"🔁 循环巡航等待中（已完成 {self.cruise_round} 轮）：距下一轮巡航还有 {time_str}"
            )
