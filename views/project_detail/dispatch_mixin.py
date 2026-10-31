# -*- coding: utf-8 -*-
"""拆批 / 导出 JSON / 导入报告 / 自动轮询分发相关方法。

由 ProjectDetailWidget 通过多重继承组合使用，方法内的 self 即 ProjectDetailWidget 实例。"""
from views.project_detail.common import *  # noqa: F401,F403
from views.project_detail.common import logger  # noqa: F401


class DispatchMixin:
    def export_batch_json(self):
        """Generates task list JSON and opens batch copy dialog partitioned by points budget <= 50."""
        if self.config_manager:
            self.config_manager.load()
        res = self.build_batches()
        if res.get("error"):
            level = res.get("level", "warning")
            if level == "info":
                QMessageBox.information(self, "提示", res["error"])
            else:
                QMessageBox.warning(self, "提示", res["error"])
            return

        default_aspect = getattr(self.config_manager, "default_aspect_ratio", "9:16") if self.config_manager else "9:16"
        if default_aspect == "16:9":
            reply = QMessageBox.question(
                self,
                "🚨 画幅尺寸确认提醒 (16:9 横屏)",
                "⚠️ 当前【规则设置】中的默认画面尺寸为 16:9（横屏）！\n\n"
                "请确认本次导出的批量生成 JSON 是否确实需要 16:9 横屏尺寸？\n\n"
                "• 点击「Yes / 是」：确认尺寸正确，继续导出批量生成 JSON\n"
                "• 点击「No / 否」：取消导出（可前往「⚙️ 规则设置」修改为 9:16 竖屏）",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        from views.project_detail.batch_export_dialog import BatchExportDialog
        dialog = BatchExportDialog(self, res["batches"], self.config_manager, skipped_count=res["skipped"])
        dialog.exec()

    def _get_project_short_name(self):
        """Returns project number (e.g. 01) + first 10 chars of user's project name."""
        from services.batch_planner import project_short_name
        return project_short_name(self.project_model, self.project_path)

    def build_batches(self):
        """
        按积分上限把当前项目未完成的分句拆成批次（与「导出批量 JSON」完全同一套逻辑）。
        返回 {"batches": [[task,...],...], "skipped": int, "error": str, "level": "warning"/"info"}
        实际计算由 services.batch_planner.compute_project_batches 完成（全局托管后台拆批也用同一函数）。
        """
        if not self.project_model:
            return {"batches": [], "skipped": 0, "error": "请先打开一个工程项目。"}
        from services.batch_planner import compute_project_batches
        if not hasattr(self, "copied_rows"):
            self.copied_rows = set()
        return compute_project_batches(
            self.project_model, self.project_path, self.template_manager, self.config_manager,
            global_tpl_id=self.combo_templates.currentData() or "",
            global_motion_id=self.combo_motions.currentData() or "",
            enable_end_frame=bool(getattr(self, "enable_end_frame", False)),
            short_name=self._get_project_short_name(),
            copied_rows=self.copied_rows,
        )

    def get_live_batch_overrides(self):
        """当前界面上的实时选择（供全局托管后台拆批使用，保证与界面所见一致）。"""
        return {
            "global_tpl_id": self.combo_templates.currentData() or "",
            "global_motion_id": self.combo_motions.currentData() or "",
            "enable_end_frame": bool(getattr(self, "enable_end_frame", False)),
        }

    def open_settings_dialog(self):
        """Opens rules and points settings dialog."""
        from views.settings_dialog import SettingsDialog
        if not self.config_manager:
            main_win = self.window()
            if hasattr(main_win, "config_manager"):
                self.config_manager = main_win.config_manager
                
        if self.config_manager:
            dialog = SettingsDialog(self.config_manager, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.refresh_prop_template_motion_combos()
                self.populate_segments_table()

    def check_video_completeness(self):
        """Scans disk for generated video files and displays completeness inspection dialog."""
        if not self.project_model:
            QMessageBox.warning(self, "提示", "请先打开一个工程项目。")
            return
            
        from services.video_checker import VideoChecker
        from views.video_check_dialog import VideoCheckDialog
        
        base_storage_path = None
        main_win = self.window()
        if hasattr(main_win, "storage_manager") and main_win.storage_manager:
            base_storage_path = main_win.storage_manager.get_base_path()
        if not base_storage_path and self.project_path:
            base_storage_path = Path(self.project_path).parent
            
        report = VideoChecker.check_project_videos(self.project_model, self.project_path, base_storage_path=base_storage_path)
        dialog = VideoCheckDialog(report, self.project_model, self.project_path, base_storage_path=base_storage_path, parent=self)
        dialog.exec()

    def import_execution_report(self):
        """Reads status report from clipboard and relocates downloaded videos to their target paths."""
        if not self.project_model:
            QMessageBox.warning(self, "提示", "请先打开一个工程项目。")
            return
            
        clipboard = QGuiApplication.clipboard()
        report_text = clipboard.text().strip()
        if not report_text:
            QMessageBox.warning(self, "提示", "剪贴板为空，请先从浏览器插件复制运行报告。")
            return
            
        import json
        import re
        
        # Try to extract JSON list or object block from clipboard text
        match = re.search(r'(\[.*\]|\{.*\})', report_text, re.DOTALL)
        json_candidate = match.group(1) if match else report_text
        
        try:
            report_data = json.loads(json_candidate)
            if isinstance(report_data, dict):
                report_data = [report_data]
            elif not isinstance(report_data, list):
                raise ValueError("解析的数据既不是 JSON 数组也不是 JSON 对象")
        except Exception as e:
            preview = report_text[:80] + "..." if len(report_text) > 80 else report_text
            QMessageBox.critical(
                self, "解析失败", 
                f"解析剪贴板 JSON 失败: {e}\n\n"
                f"当前剪贴板文本预览：\n{preview}\n\n"
                f"请确保您已点击 Chrome 插件的“复制报告”按钮，或剪贴板中是合法的 JSON 格式报告。"
            )
            return
            
        from pathlib import Path
        import shutil
        
        success_count = 0
        fail_count = 0
        not_found_paths = []
        
        chrome_downloads = Path.home() / "Downloads"
        
        for item in report_data:
            target_path_str = item.get("download_path")
            status = item.get("status")
            
            if not target_path_str or status != "success":
                continue
                
            target_path = Path(target_path_str)
            filename = target_path.name
            
            possible_sources = [
                chrome_downloads / "Flow" / self.project_model.project_id / filename,
                chrome_downloads / "Flow" / f"{self.project_model.project_id}-flow" / filename,
                chrome_downloads / "Flow" / filename,
                chrome_downloads / filename,
            ]
            
            source_file = None
            for p in possible_sources:
                if p.exists() and p.is_file():
                    source_file = p
                    break
                    
            if not source_file:
                flow_dir = chrome_downloads / "Flow"
                if flow_dir.exists():
                    found_files = list(flow_dir.glob(f"**/{filename}"))
                    if found_files:
                        source_file = found_files[0]
                        
            if not source_file:
                found_files = list(chrome_downloads.glob(f"**/{filename}"))
                if found_files:
                    source_file = found_files[0]
                    
            if source_file:
                try:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(source_file), str(target_path))
                    success_count += 1
                except Exception as err:
                    print(f"Error moving file {source_file} to {target_path}: {err}")
                    fail_count += 1
            else:
                not_found_paths.append(filename)
                
        self.refresh_media_list()
        
        if self.project_model:
            self.project_model.update_media_files()
            main_win = self.window()
            if hasattr(main_win, "reload_projects_list"):
                main_win.reload_projects_list()
            
        msg = f"已成功移入并归档 {success_count} 个视频文件！\n"
        if fail_count > 0:
            msg += f"移动失败 {fail_count} 个文件。\n"
        if not_found_paths:
            msg += f"\n未在下载目录中找到以下 {len(not_found_paths)} 个视频（请确认浏览器下载已完成）：\n"
            msg += "\n".join(f"- {name}" for name in not_found_paths[:5])
            if len(not_found_paths) > 5:
                msg += f"\n... 以及其他 {len(not_found_paths) - 5} 个文件"
                
        if success_count > 0:
            QMessageBox.information(self, "归档结果", msg)
        else:
            QMessageBox.warning(self, "未找到文件", msg)

    def on_plugin_report_received(self, report_data):
        """Processes execution report received via WebSocket from a browser plugin."""
        if not self.project_model:
            return
            
        data = report_data.get("data", [])
        segments = self.project_model.spanish_segments
        chrome_downloads = Path.home() / "Downloads"
        import base64
        import shutil

        updated_count = 0
        for item in data:
            idx = item.get("index")
            status = item.get("status", "success")
            download_url = item.get("download_url")
            target_path_str = item.get("download_path")
            base64_data = item.get("base64Data") or item.get("base64_data")

            # 兼容通过 prompt 反查 index
            if (idx is None or not isinstance(idx, int) or idx < 0 or idx >= len(segments)) and item.get("prompt"):
                for s_idx, seg in enumerate(segments):
                    if item.get("prompt") in seg.get("text", ""):
                        idx = s_idx
                        break

            # 兼容 1-indexed 索引 (例如 1..len(segments))
            if idx is not None and isinstance(idx, int):
                if idx >= len(segments) and idx - 1 < len(segments):
                    idx = idx - 1

            if idx is not None and isinstance(idx, int) and 0 <= idx < len(segments):
                if hasattr(self, 'dispatched_indices') and idx in self.dispatched_indices:
                    self.dispatched_indices.discard(idx)

            if status == "success" and idx is not None and isinstance(idx, int) and 0 <= idx < len(segments):
                segments[idx]["copied"] = True
                segments[idx]["completed"] = True
                segments[idx]["status"] = "success"
                self.copied_rows.add(idx)
                updated_count += 1
                
                # 如果没有显式指定 target_path_str，自动推导为 project_path/downloads/videos/01.mp4 等标准路径
                if not target_path_str and self.project_path:
                    videos_dir = self.project_path / "downloads" / "videos"
                    videos_dir.mkdir(parents=True, exist_ok=True)
                    target_path_str = str((videos_dir / f"{idx + 1:02d}.mp4").resolve())

                download_success = False
                target_filename = item.get("target_filename")
                project_name = item.get("project_name")
                
                # 1. 优先扫描 Chrome Downloads 目录并自动移动/复制至当前工程目录
                possible_sources = []
                if project_name and target_filename:
                    possible_sources.append(chrome_downloads / "Flow" / project_name / target_filename)
                if target_filename:
                    possible_sources.append(chrome_downloads / "Flow" / target_filename)
                
                if self.project_model:
                    p_id = self.project_model.project_id
                    filename = Path(target_path_str).name
                    possible_sources.extend([
                        chrome_downloads / "Flow" / p_id / filename,
                        chrome_downloads / "Flow" / f"{p_id}-flow" / filename,
                        chrome_downloads / "Flow" / filename,
                        chrome_downloads / filename,
                    ])

                source_file = None
                for p in possible_sources:
                    if p.exists() and p.is_file() and p.stat().st_size > 1024:
                        source_file = p
                        break
                
                # 通配扫描最近在 Downloads/Flow 目录中生成的 mp4 文件
                if not source_file:
                    flow_dir = chrome_downloads / "Flow"
                    if flow_dir.exists():
                        recent_mp4s = list(flow_dir.glob("**/*.mp4"))
                        recent_mp4s.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                        if recent_mp4s:
                            # 取最新的一个 mp4 文件
                            source_file = recent_mp4s[0]

                if source_file and target_path_str:
                    try:
                        target_path = Path(target_path_str)
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source_file, target_path)
                        download_success = True
                        logger.info(f"✅ [Chrome 下载扫描成功] 成功将下载文件 {source_file} 归档至: {target_path}")
                    except Exception as copy_err:
                        logger.warning(f"复制 Chrome 下载文件异常: {copy_err}")

                # 2. 次选方案：解码 Base64 视频字节流直接写入
                if not download_success and base64_data and target_path_str:
                    try:
                        target_path = Path(target_path_str)
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        video_bytes = base64.b64decode(base64_data)
                        if len(video_bytes) > 1024:
                            with open(target_path, "wb") as f:
                                f.write(video_bytes)
                            download_success = True
                            logger.info(f"✅ Base64 视频字节流成功写入: {target_path}")
                    except Exception as b64_err:
                        logger.warning(f"解码 Base64 视频失败: {b64_err}")

                # 3. 备用方案：HTTP 直连流下载
                if not download_success and download_url and target_path_str:
                    try:
                        import requests
                        target_path = Path(target_path_str)
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        headers = {
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                        }
                        resp = requests.get(download_url, headers=headers, allow_redirects=True, stream=True, timeout=60)
                        if resp.status_code == 200:
                            with open(target_path, "wb") as f:
                                for chunk in resp.iter_content(chunk_size=16384):
                                    f.write(chunk)
                            download_success = True
                            logger.info(f"✅ HTTP 直连下载成功: {target_path}")
                    except Exception as dl_err:
                        logger.warning(f"HTTP 直连下载异常: {dl_err}")

                # 4. 延迟 1.5 秒与 4 秒再次扫描 Chrome 下载目录 (解决 Chrome 写入未完成问题)
                if not download_success and target_path_str:
                    def try_delayed_copy(tp_str=target_path_str):
                        tp = Path(tp_str)
                        flow_dir = chrome_downloads / "Flow"
                        if flow_dir.exists():
                            recent_mp4s = list(flow_dir.glob("**/*.mp4"))
                            recent_mp4s.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                            if recent_mp4s:
                                try:
                                    tp.parent.mkdir(parents=True, exist_ok=True)
                                    shutil.copy2(recent_mp4s[0], tp)
                                    logger.info(f"✅ 延迟扫描归档成功复制 {recent_mp4s[0]} 至: {tp}")
                                    if hasattr(self, 'populate_segments_table'):
                                        self.populate_segments_table()
                                except Exception as e:
                                    logger.warning(f"延迟复制视频失败: {e}")

                    QTimer.singleShot(1500, try_delayed_copy)
                    QTimer.singleShot(4000, try_delayed_copy)

        if updated_count > 0:
            self.project_model.save()
            self.populate_segments_table()
            
        if self.is_auto_polling_active:
            QTimer.singleShot(300, self.run_polling_dispatcher_cycle)

    def pack_batch_for_capacity(self, capacity_points, max_tasks=None):
        """
        Packs a task batch from current project's uncompleted segments to fit capacity_points,
        optionally limiting to max_tasks for optimal load-balancing across multiple online workers.
        """
        if not self.project_model or not self.project_model.spanish_segments:
            return []

        segments = self.project_model.spanish_segments
        all_unprocessed_tasks = []
        for idx, seg in enumerate(segments):
            # 排除已经被分配给其他正在运行 Worker 的任务
            if hasattr(self, 'dispatched_indices') and idx in self.dispatched_indices:
                continue

            # 超过 3 次重试失败的顽固片段，先临时跳过，防止阻塞整个工程与流水线
            if hasattr(self, 'failed_skip_indices') and idx in self.failed_skip_indices:
                continue

            videos_dir = self.project_path / "downloads" / "videos" if self.project_path else Path("downloads/videos")
            download_name = f"{idx+1:02d}.mp4"
            download_path_obj = (videos_dir / download_name).resolve()
            download_path = str(download_path_obj)

            # 核心判重与断点续跑：以本地硬盘是否真实存在该序号的非空 mp4 视频文件为唯一判重标准！
            if download_path_obj.exists() and download_path_obj.stat().st_size > 0:
                seg["copied"] = True
                seg["completed"] = True
                if hasattr(self, 'copied_rows'):
                    self.copied_rows.add(idx)
                if hasattr(self, 'segment_retry_counts'):
                    self.segment_retry_counts.pop(idx, None)
                if hasattr(self, 'failed_skip_indices'):
                    self.failed_skip_indices.discard(idx)
                continue
            else:
                seg["copied"] = False
                seg["completed"] = False
                if hasattr(self, 'copied_rows'):
                    self.copied_rows.discard(idx)

            raw_text = seg.get("text", "")
            text = TextProcessor.remove_punctuation(raw_text)
            
            tpl, motion = self.get_effective_template_and_motion(idx)
            template_content = tpl["content"] if tpl else "{spanish_text}"
            motion_content = motion["content"] if motion else ""
            
            final_prompt = template_content.replace("{spanish_text}", text)
            final_prompt = final_prompt.replace("{camera_motion}", motion_content)
            final_prompt = re.sub(r' +', ' ', final_prompt).strip()
            
            image_name, local_image_path, image_data_url = self.resolve_segment_image_and_data(idx, seg)
            end_image_name, end_local_image_path, end_image_data_url = self.resolve_segment_end_image_and_data(idx, seg)
            
            default_mode = getattr(self.config_manager, "default_generation_mode", "VIDEO_FRAMES") if self.config_manager else "VIDEO_FRAMES"
            default_aspect = getattr(self.config_manager, "default_aspect_ratio", "9:16") if self.config_manager else "9:16"
            default_model = getattr(self.config_manager, "default_video_model", "omni_1_1_flash") if self.config_manager else "omni_1_1_flash"
            task_interval = getattr(self.config_manager, "task_interval", 5) if self.config_manager else 5
            
            if seg.get("mode_overridden") and seg.get("mode") in ("VIDEO_FRAMES", "VIDEO_REFERENCES"):
                mode = seg.get("mode")
            else:
                mode = default_mode
            is_edge = (idx == 0 or idx == len(segments) - 1)
            if self.config_manager:
                duration = self.config_manager.get_duration_for_length(len(text), is_edge=is_edge)
                seg["duration"] = duration
            else:
                duration = seg.get("duration", 6)
                
            videos_dir = self.project_path / "downloads" / "videos" if self.project_path else Path("downloads/videos")
            download_name = f"{idx+1:02d}.mp4"
            download_path = str((videos_dir / download_name).resolve())
            
            project_id_str = getattr(self.project_model, "project_id", "") or (self.project_path.name if self.project_path else "")
            project_short_str = self._get_project_short_name()
            task_dict = {
                "project_id": project_id_str,
                "project_short": project_short_str,
                "segment_index": idx + 1,
                "segment_no": f"{idx+1:02d}",
                "index": idx,
                "prompt": final_prompt,
                "mode": mode,
                "aspect_ratio": default_aspect,
                "model": default_model,
                "interval": task_interval,
                "image_name": image_name,
                "local_image_path": local_image_path,
                "image_data_url": image_data_url,
                "imageDataUrl": image_data_url,
                "duration": duration,
                "download_path": download_path,
                "_raw_duration": duration,
                "_original_index": idx,
                "_text_len": len(text)
            }
            if getattr(self, "enable_end_frame", False) and end_image_name:
                task_dict["end_image_name"] = end_image_name
                task_dict["end_local_image_path"] = end_local_image_path
                task_dict["end_image_data_url"] = end_image_data_url
                task_dict["endImageDataUrl"] = end_image_data_url

            all_unprocessed_tasks.append(task_dict)

        if not all_unprocessed_tasks or capacity_points < 7:
            return []

        def get_task_points_val(dur):
            if self.config_manager:
                return self.config_manager.get_points_for_duration(dur)
            points_map = {10: 15, 8: 12, 6: 10, 4: 7}
            return points_map.get(dur, 7)

        def get_task_points(task):
            return get_task_points_val(task.get("duration", task.get("_raw_duration", 6)))

        # Sort tasks descending by points
        sorted_tasks = sorted(all_unprocessed_tasks, key=get_task_points, reverse=True)

        batch = []
        cur_pts = 0
        for task in sorted_tasks:
            if max_tasks is not None and len(batch) >= max_tasks:
                break
            pts = get_task_points(task)
            if cur_pts + pts <= capacity_points:
                batch.append(task)
                cur_pts += pts

        if not batch:
            return []

        batch.sort(key=lambda t: t["_original_index"])
        
        cleaned_batch = []
        for item in batch:
            cleaned_item = {k: v for k, v in item.items() if not k.startswith("_")}
            cleaned_batch.append(cleaned_item)
            
        return cleaned_batch

    def start_auto_polling_dispatcher(self):
        """Starts the auto-polling task dispatcher for the current project."""
        if not self.plugin_server:
            QMessageBox.warning(self, "提示", "WebSocket 插件服务端未启动。")
            return

        tpl_id = self.combo_templates.currentData() if hasattr(self, "combo_templates") else None
        if not tpl_id:
            QMessageBox.warning(self, "提示", "⚠️ 请先在上方为当前工程选择【统一提示词模板】后再启动自动分发！")
            return

        clients = self.plugin_server.get_online_clients()
        if not clients:
            QMessageBox.warning(self, "提示", "⚠️ 当前没有在线的浏览器 Worker。\n\n请在 Chrome 浏览器中打开 Google Flow 网页。")
            return

        # 启动时彻底清空历史锁定索引、跳过记录与重试计数，确保每次启动所有未完成句子都能全量正常生成
        self.dispatched_indices = set()
        self.failed_skip_indices = set()
        self.segment_retry_counts = {}
        for socket, info in self.plugin_server.clients.items():
            if info.get("remaining_points", 0) >= 7:
                info["status"] = "idle"
            else:
                info["status"] = "low_points"
            info["current_batch"] = None

        usable_clients = [c for c in clients if c.get("remaining_points", 0) >= 7]
        if not usable_clients:
            total_pts = sum(c.get("remaining_points", 0) for c in clients)
            QMessageBox.warning(
                self, "积分不足提示",
                f"⚠️ 当前在线的 {len(clients)} 个浏览器 Worker 积分均不足 7 点（当前总积分剩余 {total_pts} 点，不足以支付一个视频）。\n\n"
                "请点击【🔄 刷新点数】重新探测，或更换有积分的 Google 账号。"
            )
            return
            
        self.is_auto_polling_active = True
        if not hasattr(self, "polling_timer") or not self.polling_timer:
            self.polling_timer = QTimer(self)
            self.polling_timer.timeout.connect(self.run_polling_dispatcher_cycle)
            
        self.run_polling_dispatcher_cycle()
        self.polling_timer.start(4000) # Poll every 4 seconds

    def stop_auto_polling_dispatcher(self):
        """Stops the auto-polling task dispatcher."""
        self.is_auto_polling_active = False
        if hasattr(self, "polling_timer") and self.polling_timer:
            self.polling_timer.stop()

    def run_polling_dispatcher_cycle(self):
        """Runs one cycle of the auto-polling dispatcher for this project."""
        if not self.is_auto_polling_active:
            return

        if not self.project_model or not self.project_model.spanish_segments:
            self.stop_auto_polling_dispatcher()
            return

        segments = self.project_model.spanish_segments
        videos_dir = self.project_path / "downloads" / "videos" if self.project_path else Path("downloads/videos")

        clients = self.plugin_server.get_online_clients()
        idle_clients = [c for c in clients if c.get("status") == "idle" and c.get("remaining_points", 0) >= 7]

        # 1. 动态释放任务锁定：若没有 busy Worker 在跑，彻底释放 dispatched_indices 供下一次重试！
        busy_workers = [c for c in clients if c.get("status") == "busy"]
        if not busy_workers and hasattr(self, 'dispatched_indices'):
            self.dispatched_indices.clear()

        def check_seg_done(i):
            p = (videos_dir / f"{i+1:02d}.mp4").resolve()
            return p.exists() and p.stat().st_size > 0

        # 2. 检查所有未完成的句子：若重试次数已达 3 次，立即加入 failed_skip_indices
        if not hasattr(self, 'failed_skip_indices'):
            self.failed_skip_indices = set()
        if not hasattr(self, 'segment_retry_counts'):
            self.segment_retry_counts = {}

        for idx, _ in enumerate(segments):
            if not check_seg_done(idx):
                if self.segment_retry_counts.get(idx, 0) >= 3:
                    self.failed_skip_indices.add(idx)

        uncompleted_count = sum(
            1 for idx, _ in enumerate(segments)
            if not (check_seg_done(idx) or idx in self.failed_skip_indices)
        )

        if uncompleted_count == 0:
            self.stop_auto_polling_dispatcher()
            skip_count = len(self.failed_skip_indices)
            if skip_count > 0:
                logger.info(f"🎉 当前工程已完成所有可生成视频（有 {skip_count} 句重试 3 次未出片已自动先跳过）！")
            else:
                logger.info("🎉 当前工程所有视频已全部在本地磁盘生成就绪！")
            if self.active_batch_dialog:
                self.active_batch_dialog.update_polling_ui()
            return

        if not idle_clients:
            return

        # 智能全并行负载均衡：计算每个 Worker 应分担的任务上限，确保所有在线浏览器全部动起来！
        remaining_tasks_count = sum(
            1 for idx, _ in enumerate(segments)
            if not (check_seg_done(idx) or (hasattr(self, 'dispatched_indices') and idx in self.dispatched_indices) or idx in self.failed_skip_indices)
        )
        
        tasks_per_worker = max(1, (remaining_tasks_count + len(idle_clients) - 1) // len(idle_clients)) if remaining_tasks_count > 0 else 5
        logger.info(f"🔄 调度周期: 剩余待分发任务数={remaining_tasks_count}, 空闲有分Worker数={len(idle_clients)}, 单Worker配额={tasks_per_worker}")

        for client in idle_clients:
            pts = client.get("remaining_points", 0)
            if pts < 7:
                continue
            batch_tasks = self.pack_batch_for_capacity(pts, max_tasks=tasks_per_worker)
            if batch_tasks:
                task_indices = [t["index"] for t in batch_tasks if "index" in t]
                for idx in task_indices:
                    self.dispatched_indices.add(idx)
                    # 记录并累加重试计数
                    self.segment_retry_counts[idx] = self.segment_retry_counts.get(idx, 0) + 1
                    
                    # 若重试达 3 次且本地仍无文件，加入跳过集合
                    if self.segment_retry_counts[idx] >= 3:
                        self.failed_skip_indices.add(idx)
                        logger.warning(f"⚠️ [智能熔断] 第 {idx+1} 句已累计重试 3 次未成功出片，自动先跳过以保障流水线顺畅推进！")

                batch_id = f"{self.project_model.project_id}_{int(QDateTime.currentMSecsSinceEpoch())}_{client['client_id']}"
                logger.info(f"🚀 向 Worker [{client['client_id']}] 派发任务 ({len(batch_tasks)}条, 序号: {task_indices})")
                self.plugin_server.send_tasks_to_client(client["client_id"], batch_id, batch_tasks)
                if self.active_batch_dialog and self.active_batch_dialog.isVisible():
                    self.active_batch_dialog.refresh_workers_list()
