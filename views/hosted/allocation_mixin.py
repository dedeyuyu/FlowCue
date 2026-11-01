# -*- coding: utf-8 -*-
"""步骤 1：后台拆批 + 低积分账号优先的任务分配。

由 HostedModeWidget 通过多重继承组合使用，方法内的 self 即 HostedModeWidget 实例。"""
from views.hosted.common import *  # noqa: F401,F403
from views.hosted.common import logger  # noqa: F401


class AllocationMixin:
    def _points_of(self, task):
        cm = getattr(self.mw, "config_manager", None)
        d = task.get("duration", 6)
        if cm:
            return cm.get_points_for_duration(d)
        return {10: 15, 8: 12, 6: 10, 4: 7}.get(d, 7)

    def _collect_project_items(self, all_projects):
        """返回 ([(项目路径, 显示名), ...], 错误列表)。"""
        detail = self.mw.detail_widget
        prev = detail.project_path
        if all_projects:
            items = []
            lst = self.mw.list_projects
            for i in range(lst.count()):
                it = lst.item(i)
                if it.checkState() == Qt.CheckState.Checked:
                    items.append((it.data(Qt.ItemDataRole.UserRole), it.text().replace("●", "").strip()))
        else:
            if not prev:
                return [], ["请先在「项目管理」中打开一个项目"]
            cur = self.mw.list_projects.currentItem()
            items = [(str(prev), cur.text().replace("●", "").strip() if cur else Path(prev).name)]
        return [(p, l) for p, l in items if p], []

    def _results_to_batches(self, results):
        """把拆批结果 [(path, label, res), ...] 转成托管批次结构，返回 (批次列表, 错误列表)。"""
        result, errors = [], []
        for path, label, res in results:
            if res.get("error"):
                if res.get("level") != "info":
                    errors.append(f"{label}：{res['error']}")
                continue
            for n, batch in enumerate(res["batches"], start=1):
                tasks, images, segs = [], [], []
                for t in batch:
                    segs.append(t.get("_original_index", 0))
                    clean = {k: v for k, v in t.items() if not k.startswith("_")}
                    clean["_mode_overridden"] = bool(t.get("_mode_overridden"))
                    tasks.append(clean)
                    for key in ("local_image_path", "end_local_image_path"):
                        p = clean.get(key)
                        if p and p not in images:
                            images.append(p)
                pts = sum(self._points_of(t) for t in tasks)
                pid = Path(path).name
                result.append({
                    "id": f"{pid}#B{n}", "short": f"{label.split()[0] if label else pid}-第{n}批",
                    "project_path": str(path), "project_label": label, "batch_no": n,
                    "tasks": tasks, "seg_indices": segs, "images": images, "points": pts,
                    "cid": None, "email": "", "to_low": False,
                    "upload_state": "未上传", "upload_failed": {},
                    "run_state": "未开始", "ok": 0, "fail": 0, "done_paths": set(), "fail_msgs": {},
                })
        return result, errors

    def _planner_open_project(self):
        """当前在项目管理打开的项目：先落盘，并带上界面上的实时选择。"""
        detail = self.mw.detail_widget
        if not detail.project_path or not detail.project_model:
            return None
        try:
            detail.project_model.save()
        except Exception:
            pass
        overrides = detail.get_live_batch_overrides() if hasattr(detail, "get_live_batch_overrides") else {}
        return (str(detail.project_path), overrides)

    def _collect_project_batches(self, all_projects):
        """同步版本（保留兼容）：调用与项目管理完全相同的拆批逻辑，返回 (批次列表, 错误列表)。"""
        from services.batch_planner import compute_project_batches
        from models.project_model import ProjectModel
        items, errors = self._collect_project_items(all_projects)
        if errors:
            return [], errors
        open_proj = self._planner_open_project()
        tm = getattr(self.mw, "template_manager", None)
        cm = getattr(self.mw, "config_manager", None)
        results = []
        for path, label in items:
            kwargs = dict(open_proj[1]) if open_proj and open_proj[0] == str(path) else {}
            try:
                res = compute_project_batches(ProjectModel(Path(path)), path, tm, cm, **kwargs)
            except Exception as e:
                res = {"batches": [], "skipped": 0, "error": f"拆批异常：{e}"}
            results.append((str(path), label, res))
        return self._results_to_batches(results)

    def on_allocate(self, all_projects):
        self._flush_pending_settings()
        if self._busy():
            QMessageBox.warning(self, "提示", "正在上传或生成中，请先停止后再重新分配。")
            return
        clients = self._clients()
        if not clients:
            QMessageBox.information(self, "提示", "当前没有已连接的浏览器。")
            return
        known = [c for c in clients if c.get("points_known") and not c.get("secondary_tab")]
        if not known:
            QMessageBox.information(self, "提示", "还没有读取到任何浏览器的积分，请先点击「刷新积分」。")
            return

        items, errors = self._collect_project_items(all_projects)
        if errors or not items:
            QMessageBox.information(self, "提示", "\n".join(errors) if errors else "没有勾选任何项目。")
            return
        old_th = getattr(self, "_planner_thread", None)
        if old_th is not None:
            try:
                if old_th.isRunning():
                    return
            except RuntimeError:
                pass
            self._planner_thread = None

        # 拆批放到后台线程执行，界面不卡；完成后回到主线程继续分配
        from services.batch_planner import ProjectBatchPlannerThread
        self._set_allocate_buttons_enabled(False)
        self._log(f"⏳ 正在后台拆批（{len(items)} 个项目），界面可继续操作…")
        th = ProjectBatchPlannerThread(items, getattr(self.mw, "template_manager", None),
                                       getattr(self.mw, "config_manager", None),
                                       open_project=self._planner_open_project(), parent=self)
        th.progress_signal.connect(lambda n, total, label: self.lbl_summary.setText(f"⏳ 拆批中 {n}/{total}：{label}"))
        th.finished_signal.connect(self._on_planner_finished)

        def _on_planner_thread_done(t=th):
            if getattr(self, "_planner_thread", None) is t:
                self._planner_thread = None
            try:
                t.deleteLater()
            except RuntimeError:
                pass

        th.finished.connect(_on_planner_thread_done)
        self._planner_thread = th
        th.start()

    def _set_allocate_buttons_enabled(self, on):
        for b in (getattr(self, "btn_alloc_current", None), getattr(self, "btn_alloc_all", None)):
            if b is not None:
                b.setEnabled(on)

    def _on_planner_finished(self, results):
        self._set_allocate_buttons_enabled(True)
        self._planner_thread = None
        batches, errors = self._results_to_batches(results)
        if errors:
            self._log("⚠️ 以下项目未能拆批：\n  " + "\n  ".join(errors))
        if not batches:
            self._schedule_refresh()
            QMessageBox.information(self, "提示", "没有需要生成的批次。\n\n" + ("\n".join(errors[:8]) if errors else "所有分句都已生成。"))
            return
        if self._busy():
            QMessageBox.warning(self, "提示", "拆批期间已开始上传或生成，本次分配已取消。")
            return
        known = [c for c in self._clients() if c.get("points_known") and not c.get("secondary_tab")]
        if not known:
            QMessageBox.information(self, "提示", "浏览器已断开或未读取到积分，请刷新积分后重新分配。")
            return
        self._allocate_batches(batches, known)

    def _allocate_batches(self, batches, known):

        # —— 分配算法（低积分账号优先）——
        # 不再使用固定大小的批次：先把所有待生成分镜打散，再按「剩余积分从低到高」依次为每个浏览器
        # 量身打包一批（不超过该浏览器的剩余积分，也不超过规则设置中的单批积分上限）。
        # 每轮每个浏览器最多分 1 批，多轮循环直到任务分完或没有浏览器还能接得下，
        # 这样 12 / 15 / 30 积分这类低积分号会被优先用满，同时仍保持多浏览器并行。
        cm = getattr(self.mw, "config_manager", None)
        max_batch = int(getattr(cm, "max_batch_points", 50) or 50) if cm else 50
        cap = {c["client_id"]: int(c.get("remaining_points", 0)) for c in known}
        count = {cid: 0 for cid in cap}
        by_id = {c["client_id"]: c for c in known}
        order = sorted(cap.keys(), key=lambda cid: (cap[cid], cid))
        self.plan = {}

        # 打散为分镜池（按项目分组、保持原有顺序）
        proj_order, pools, proj_meta = [], {}, {}
        for b in batches:
            pp = b["project_path"]
            if pp not in pools:
                proj_order.append(pp)
                pools[pp] = []
                proj_meta[pp] = (b["project_label"], b.get("short", ""))
            for t, s in zip(b["tasks"], b["seg_indices"]):
                pools[pp].append({"task": t, "seg": s, "pts": self._points_of(t)})
        batch_counter = {pp: 0 for pp in proj_order}

        def make_batch(pp, items):
            batch_counter[pp] += 1
            n = batch_counter[pp]
            items = sorted(items, key=lambda x: x["seg"])
            tasks = [x["task"] for x in items]
            images = []
            for t in tasks:
                for key in ("local_image_path", "end_local_image_path"):
                    p = t.get(key)
                    if p and p not in images:
                        images.append(p)
            label = proj_meta[pp][0]
            pid = Path(pp).name
            return {
                "id": f"{pid}#B{n}", "short": f"{label.split()[0] if label else pid}-第{n}批",
                "project_path": pp, "project_label": label, "batch_no": n,
                "tasks": tasks, "seg_indices": [x["seg"] for x in items], "images": images,
                "points": sum(x["pts"] for x in items),
                "cid": None, "email": "", "to_low": False,
                "upload_state": "未上传", "upload_failed": {},
                "run_state": "未开始", "ok": 0, "fail": 0, "done_paths": set(), "fail_msgs": {},
            }

        def pack(limit):
            """从分镜池中取出一个项目内、总积分不超过 limit 的最优组合（大任务优先装入）。"""
            for pp in proj_order:
                pool = pools[pp]
                if not pool:
                    continue
                picked, used = [], 0
                for x in sorted(pool, key=lambda x: -x["pts"]):
                    if used + x["pts"] <= limit:
                        picked.append(x)
                        used += x["pts"]
                if picked:
                    ids = {id(x) for x in picked}
                    pools[pp] = [x for x in pool if id(x) not in ids]
                    return pp, picked
            return None, []

        def assign(b, cid):
            to_low = self._is_low(by_id[cid])
            cap[cid] -= b["points"]
            count[cid] += 1
            c = by_id[cid]
            b["cid"], b["email"], b["to_low"] = cid, self._email(c), to_low
            b["iid"], b["who"] = self._iid(c), self._who(c)
            e = self.plan.setdefault(cid, {"cid": cid, "email": self._email(c), "iid": self._iid(c), "who": self._who(c),
                                           "points": int(c.get("remaining_points", 0)),
                                           "low": to_low, "batch_ids": []})
            e["batch_ids"].append(b["id"])

        new_batches = []
        progress = True
        while progress and any(pools.values()):
            progress = False
            for cid in order:
                if not any(pools.values()):
                    break
                limit = min(cap[cid], max_batch)
                if limit <= 0:
                    continue
                pp, picked = pack(limit)
                if not picked:
                    continue
                b = make_batch(pp, picked)
                assign(b, cid)
                new_batches.append(b)
                progress = True

        # 剩余没有浏览器接得下的分镜：按单批上限打包，标记为未分配
        for pp in proj_order:
            while pools[pp]:
                _, picked = pack(max_batch)
                if not picked:
                    # 单个分镜就超过单批上限，单独成批
                    picked = [pools[pp].pop(0)]
                new_batches.append(make_batch(pp, picked))

        # 保持项目/批次顺序展示
        new_batches.sort(key=lambda b: (proj_order.index(b["project_path"]), b["batch_no"]))
        batches = new_batches
        self.batches = batches
        un = [b for b in batches if not b["cid"]]
        self._log(f"✅ 分配完成：{len(batches)} 批，已分配 {len(batches) - len(un)} 批，"
                  f"涉及 {len(self.plan)} 个浏览器" + (f"；⚠️ {len(un)} 批因积分不足未分配" if un else ""))
        for b in batches:
            if b["cid"]:
                self._log(f"   {b['short']}（{b['points']} 积分）→ {self._label(b)}" + (" [低积分号]" if b["to_low"] else ""))
        self._schedule_refresh()
