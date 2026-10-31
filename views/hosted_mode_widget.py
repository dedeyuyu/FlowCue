# -*- coding: utf-8 -*-
"""
🤖 全局托管模式

步骤 1：刷新积分 → 标记低于阈值的浏览器 → 后台拆批后把任务分配给浏览器
        · 按浏览器剩余积分从低到高优先分配，为每个浏览器量身打包不超过其剩余积分（及单批上限）的任务
        · 每轮每个浏览器最多 1 批，多轮循环直到分完，兼顾低积分号优先与多浏览器并行
步骤 2：按浏览器分组上传图片（默认每组 5 个浏览器），一组全部完成或超时后再进入下一组；
        精确记录每张失败的图片，支持「重新上传失败图片」
步骤 3：把每批任务 JSON 直接发送给对应插件并自动开始生成，实时监控每个任务成功/失败，
        视频保存在 Flow 临时下载目录，后续由用户在「批量检查视频」中核对并手动完成归位
"""
from views.hosted.common import *  # noqa: F401,F403
from views.hosted.common import logger, GREEN, RED, YELLOW, BLUE, GRAY  # noqa: F401
from views.hosted.cruise_mixin import CruiseMixin
from views.hosted.browser_ops_mixin import BrowserOpsMixin
from views.hosted.allocation_mixin import AllocationMixin
from views.hosted.upload_mixin import UploadMixin
from views.hosted.run_mixin import RunMixin


class HostedModeWidget(CruiseMixin, BrowserOpsMixin, AllocationMixin, UploadMixin, RunMixin, QWidget):
    def __init__(self, plugin_server, main_window, parent=None):
        super().__init__(parent)
        self.plugin_server = plugin_server
        self.mw = main_window
        self.settings_file = Path(main_window.workspace_dir) / "hosted_mode.json"
        self.aliases_file = Path(main_window.workspace_dir) / "account_aliases.json"
        self.aliases = {}
        self._load_aliases()

        # 设置
        self.threshold = 50
        self.small_threshold = 40
        self.group_size = 5
        self.upload_timeout = 60
        self.run_group_size = 5
        self.run_wait_seconds = 60
        self.cruise_dwell_seconds = 1.0
        self.cruise_interval_minutes = 5.0
        self._load_settings()

        # 全局巡航状态
        self.cruise_active = False
        self.cruise_loop_mode = False
        self.cruise_round = 0
        self.cruise_queue = []
        self.cruise_total_in_round = 0
        self.cruise_current_idx = 0
        self.cruise_waiting_next_round = False
        self.cruise_next_round_deadline = 0

        self.cruise_step_timer = QTimer(self)
        self.cruise_step_timer.setSingleShot(True)
        self.cruise_step_timer.timeout.connect(self._cruise_step)

        self.cruise_wait_timer = QTimer(self)
        self.cruise_wait_timer.setInterval(500)
        self.cruise_wait_timer.timeout.connect(self._cruise_wait_tick)

        # 精准关闭管理
        self._pending_closes = {}
        self._close_timer = QTimer(self)
        self._close_timer.setInterval(400)
        self._close_timer.timeout.connect(self._poll_pending_closes)

        # 运行数据
        self.batches = []            # list[dict]
        self.plan = {}               # cid -> {"cid","email","label","points","low","remaining","batch_ids":[]}
        self.upload_queue = []       # 待上传的浏览器分组
        self.upload_pending = {}     # request_id -> {"cid","paths"}
        self.upload_group_deadline = 0
        self.upload_group_active = False
        self.upload_retry_only = False
        self.running = False         # 步骤 3 是否在运行
        self.run_browser_queue = []  # 步骤 3 待启动的浏览器分组队列
        self.run_released_cids = set()  # 步骤 3 已启动组的浏览器 cid 集合
        self.run_total_groups = 0
        self.run_current_group_idx = 0
        self.run_next_group_deadline = 0

        self._init_ui()

        self.upload_timer = QTimer(self)
        self.upload_timer.setInterval(500)
        self.upload_timer.timeout.connect(self._upload_tick)

        self.run_group_timer = QTimer(self)
        self.run_group_timer.setInterval(500)
        self.run_group_timer.timeout.connect(self._run_group_tick)

        if self.plugin_server:
            self.plugin_server.client_connected_signal.connect(self._schedule_refresh)
            self.plugin_server.client_updated_signal.connect(self._schedule_refresh)
            self.plugin_server.client_disconnected_signal.connect(self._on_client_disconnected)
            self.plugin_server.rpc_response_signal.connect(self._on_rpc_response)
            self.plugin_server.hosted_event_signal.connect(self._on_hosted_event)
        self._refresh_pending = False
        self.refresh_all()

    # ──────────────────────────────── 设置持久化
    def _load_aliases(self):
        try:
            if self.aliases_file.exists():
                self.aliases = json.loads(self.aliases_file.read_text(encoding="utf-8"))
            else:
                self.aliases = {}
        except Exception as e:
            logger.warning(f"读取账号备注失败: {e}")
            self.aliases = {}

    def _load_settings(self):
        try:
            if self.settings_file.exists():
                d = json.loads(self.settings_file.read_text(encoding="utf-8"))
                self.threshold = int(d.get("threshold", 50))
                self.small_threshold = int(d.get("small_threshold", 40))
                self.group_size = int(d.get("group_size", 5))
                self.upload_timeout = int(d.get("upload_timeout", 60))
                self.run_group_size = int(d.get("run_group_size", 5))
                self.run_wait_seconds = int(d.get("run_wait_seconds", 60))
                self.cruise_dwell_seconds = max(0.1, float(d.get("cruise_dwell_seconds", 1.0)))
                self.cruise_interval_minutes = max(0.5, float(d.get("cruise_interval_minutes", 5.0)))
        except Exception as e:
            logger.warning(f"读取托管设置失败: {e}")

    def _save_settings(self):
        self.threshold = self.spin_threshold.value()
        self.small_threshold = self.spin_small.value()
        self.group_size = self.spin_group.value()
        self.upload_timeout = self.spin_timeout.value()
        self.run_group_size = self.spin_run_group.value()
        self.run_wait_seconds = self.spin_run_wait.value()
        if hasattr(self, "spin_cruise_dwell"):
            self.cruise_dwell_seconds = round(float(self.spin_cruise_dwell.value()), 2)
        if hasattr(self, "spin_cruise_interval"):
            self.cruise_interval_minutes = round(float(self.spin_cruise_interval.value()), 2)
        try:
            self.settings_file.write_text(json.dumps({
                "threshold": self.threshold, "small_threshold": self.small_threshold,
                "group_size": self.group_size, "upload_timeout": self.upload_timeout,
                "run_group_size": self.run_group_size, "run_wait_seconds": self.run_wait_seconds,
                "cruise_dwell_seconds": self.cruise_dwell_seconds,
                "cruise_interval_minutes": self.cruise_interval_minutes},
                ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception as e:
            logger.warning(f"保存托管设置失败: {e}")
        self._schedule_refresh()

    def _schedule_save_settings(self):
        """参数输入防抖：连续修改数值时不再每按一次就写文件 + 重建两张表格，停止输入 400ms 后统一保存。"""
        if not hasattr(self, "_save_timer"):
            self._save_timer = QTimer(self)
            self._save_timer.setSingleShot(True)
            self._save_timer.timeout.connect(self._save_settings)
        self._save_timer.start(400)

    def _flush_pending_settings(self):
        t = getattr(self, "_save_timer", None)
        if t is not None and t.isActive():
            t.stop()
            self._save_settings()

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_refresh_dirty", False):
            self._refresh_dirty = False
            self._schedule_refresh()

    # ──────────────────────────────── UI
    @staticmethod
    def _btn(text, color, hover):
        b = QPushButton(text)
        b.setStyleSheet(f"QPushButton {{ background-color: {color}; color: white; font-weight: bold; padding: 7px 14px; border-radius: 4px; }}"
                        f"QPushButton:hover {{ background-color: {hover}; }} QPushButton:disabled {{ background-color: #9CA3AF; }}")
        return b

    def _spin(self, lo, hi, val, suffix):
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(val)
        s.setSuffix(suffix)
        s.setStyleSheet("padding: 3px; font-size: 13px;")
        s.valueChanged.connect(lambda _: self._schedule_save_settings())
        return s

    def _dspin(self, lo, hi, step, decimals, val, suffix):
        s = QDoubleSpinBox()
        s.setDecimals(decimals)
        s.setRange(lo, hi)
        s.setSingleStep(step)
        s.setValue(val)
        s.setSuffix(suffix)
        s.setStyleSheet("padding: 3px; font-size: 13px;")
        s.valueChanged.connect(lambda _: self._schedule_save_settings())
        return s

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # 步骤 1
        g1 = QGroupBox("步骤 1：刷新积分 · 标记低积分浏览器 · 按批次分配任务")
        l1 = QVBoxLayout(g1)
        r = QHBoxLayout()
        self.btn_recognize = self._btn("🔌 开始识别浏览器", "#0EA5E9", "#0284C7")
        self.btn_recognize.setToolTip("开启后，已打开 Flow 页面的浏览器插件会在几秒内自动连接到软件。\n"
                                      "不使用全局托管时请保持关闭，插件处于休眠状态，手动模式更流畅。")
        self.btn_recognize.clicked.connect(self.on_toggle_recognition)
        r.addWidget(self.btn_recognize)
        self.btn_refresh = self._btn("🔄 刷新积分", "#059669", "#047857")
        self.btn_refresh.clicked.connect(self.on_refresh_points)
        r.addWidget(self.btn_refresh)
        r.addWidget(QLabel("低积分阈值："))
        self.spin_threshold = self._spin(0, 100000, self.threshold, " 积分")
        r.addWidget(self.spin_threshold)
        r.addWidget(QLabel("小批次（低于）："))
        self.spin_small = self._spin(1, 100000, self.small_threshold, " 积分")
        self.spin_small.setToolTip("批次表中积分低于此值的批次会标注「(小)」，仅用于显示。\n"
                                   "分配规则：按浏览器剩余积分从低到高优先分配，为每个浏览器量身打包不超过其剩余积分的任务。")
        r.addWidget(self.spin_small)
        self.btn_close_marked = self._btn("🔴 关闭已标记的低积分浏览器", "#DC2626", "#B91C1C")
        self.btn_close_marked.clicked.connect(self.on_close_marked)
        r.addWidget(self.btn_close_marked)
        r.addStretch()
        self.lbl_conn = QLabel("")
        r.addWidget(self.lbl_conn)
        l1.addLayout(r)

        r = QHBoxLayout()
        self.btn_alloc_current = self._btn("📌 分配当前项目", "#2563EB", "#1D4ED8")
        self.btn_alloc_current.setToolTip("只分配「项目管理」中当前打开的项目")
        self.btn_alloc_current.clicked.connect(lambda: self.on_allocate(all_projects=False))
        r.addWidget(self.btn_alloc_current)
        self.btn_alloc_all = self._btn("📚 分配所有勾选的项目", "#7C3AED", "#6D28D9")
        self.btn_alloc_all.setToolTip("分配「项目管理」左侧列表中所有打勾的项目")
        self.btn_alloc_all.clicked.connect(lambda: self.on_allocate(all_projects=True))
        r.addWidget(self.btn_alloc_all)
        self.btn_clear_plan = self._btn("🧹 清空分配", "#6B7280", "#4B5563")
        self.btn_clear_plan.clicked.connect(self.on_clear_plan)
        r.addWidget(self.btn_clear_plan)

        r.addSpacing(15)
        self.btn_clear_media = self._btn("🗑️ 清空Flow媒体", "#475569", "#334155")
        self.btn_clear_media.setToolTip("在所有已连接浏览器中，删除当前 Flow 页面上的全部图片和视频（移入回收站）")
        self.btn_clear_media.clicked.connect(self.on_clear_media_clicked)
        r.addWidget(self.btn_clear_media)

        self.btn_clear_tasks = self._btn("🧹 清空插件任务", "#475569", "#334155")
        self.btn_clear_tasks.setToolTip("清空所有已连接浏览器插件中的全部任务列表")
        self.btn_clear_tasks.clicked.connect(self.on_clear_tasks_clicked)
        r.addWidget(self.btn_clear_tasks)

        r.addStretch()
        self.lbl_summary = QLabel("")
        r.addWidget(self.lbl_summary)
        l1.addLayout(r)
        root.addWidget(g1)

        # 步骤 2 / 3 / 全局巡航
        g2 = QGroupBox("步骤 2：分组上传图片    ·    步骤 3：按批次发送任务并开始生成    ·    🧭 全局巡航（展开唤醒浏览器）")
        l2_root = QVBoxLayout(g2)
        l2_root.setSpacing(6)

        # 第一行：步骤 2（上传图片）
        l2 = QHBoxLayout()
        lbl_s2 = QLabel("📤 步骤2（上传图片）：")
        lbl_s2.setStyleSheet("font-weight: bold; color: #0E7490;")
        l2.addWidget(lbl_s2)
        l2.addWidget(QLabel("每组浏览器数："))
        self.spin_group = self._spin(1, 50, self.group_size, " 个")
        l2.addWidget(self.spin_group)
        l2.addWidget(QLabel("单组超时："))
        self.spin_timeout = self._spin(15, 600, self.upload_timeout, " 秒")
        l2.addWidget(self.spin_timeout)
        self.btn_upload = self._btn("📤 步骤2：开始上传图片", "#0891B2", "#0E7490")
        self.btn_upload.clicked.connect(lambda: self.start_upload(retry_only=False))
        l2.addWidget(self.btn_upload)
        self.btn_reupload = self._btn("🔁 重新上传失败图片", "#EA580C", "#C2410C")
        self.btn_reupload.clicked.connect(lambda: self.start_upload(retry_only=True))
        l2.addWidget(self.btn_reupload)
        self.btn_flip_failed = self._btn("↔️ 一键翻转失败图片", "#0D9488", "#0F766E")
        self.btn_flip_failed.setToolTip("将所有上传失败的图片进行左右翻转，用新图片替换并删除原图（保留原文件名）")
        self.btn_flip_failed.clicked.connect(self.flip_failed_upload_images)
        l2.addWidget(self.btn_flip_failed)
        l2.addStretch()
        l2_root.addLayout(l2)

        # 第二行：步骤 3（分批发送任务并生成）
        l3 = QHBoxLayout()
        lbl_s3 = QLabel("🚀 步骤3（发送任务）：")
        lbl_s3.setStyleSheet("font-weight: bold; color: #15803D;")
        l3.addWidget(lbl_s3)
        l3.addWidget(QLabel("每批浏览器数："))
        self.spin_run_group = self._spin(1, 50, self.run_group_size, " 个")
        self.spin_run_group.setToolTip("每次同时启动多少个浏览器运行生成任务（默认 5 个）")
        l3.addWidget(self.spin_run_group)
        l3.addWidget(QLabel("批次等待时间："))
        self.spin_run_wait = self._spin(1, 3600, self.run_wait_seconds, " 秒")
        self.spin_run_wait.setToolTip("无论上一批是否完成，等待该秒数后自动启动下一批浏览器（默认 60 秒）")
        l3.addWidget(self.spin_run_wait)
        self.btn_run = self._btn("🚀 步骤3：发送任务并开始生成", "#16A34A", "#15803D")
        self.btn_run.clicked.connect(self.start_run)
        l3.addWidget(self.btn_run)
        self.btn_stop = self._btn("⏹ 停止", "#DC2626", "#B91C1C")
        self.btn_stop.clicked.connect(self.stop_run)
        l3.addWidget(self.btn_stop)
        self.lbl_run_group_status = QLabel("")
        self.lbl_run_group_status.setStyleSheet("color: #0369A1; font-weight: bold; font-size: 12px; margin-left: 8px;")
        l3.addWidget(self.lbl_run_group_status)
        l3.addStretch()
        l2_root.addLayout(l3)

        # 第三行：全局巡航（依次展开浏览器窗口到画面最上面，支持单次巡航与定时循环巡航）
        l_cruise = QHBoxLayout()
        lbl_cruise = QLabel("🧭 全局巡航（展开窗口）：")
        lbl_cruise.setStyleSheet("font-weight: bold; color: #6D28D9;")
        l_cruise.addWidget(lbl_cruise)
        l_cruise.addWidget(QLabel("单浏览器停留："))
        self.spin_cruise_dwell = self._dspin(0.1, 60.0, 0.1, 1, self.cruise_dwell_seconds, " 秒")
        self.spin_cruise_dwell.setToolTip("依次将每个已连接浏览器展开到画面最上方后停留的秒数（支持小数如 0.3 秒、0.5 秒，默认 1.0 秒）")
        l_cruise.addWidget(self.spin_cruise_dwell)
        l_cruise.addWidget(QLabel("循环等待间隔："))
        self.spin_cruise_interval = self._dspin(0.5, 180.0, 0.5, 1, self.cruise_interval_minutes, " 分钟")
        self.spin_cruise_interval.setToolTip("在「循环巡航」模式下，将所有浏览器全部展开一遍后等待多久再进行下一轮巡航（默认 5.0 分钟）")
        l_cruise.addWidget(self.spin_cruise_interval)

        self.btn_cruise_once = self._btn("🧭 单次巡航", "#0284C7", "#0369A1")
        self.btn_cruise_once.setToolTip("依次把每个已连接的浏览器窗口展开并切到画面最上方，全部巡航一遍后自动结束")
        self.btn_cruise_once.clicked.connect(lambda: self.start_cruise(loop_mode=False))
        l_cruise.addWidget(self.btn_cruise_once)

        self.btn_cruise_loop = self._btn("🔁 开启循环巡航", "#7C3AED", "#6D28D9")
        self.btn_cruise_loop.setToolTip("每隔设定的等待时间（如 5 分钟）自动将所有已连接的浏览器依次展开一遍，直到主动点击「停止巡航」为止")
        self.btn_cruise_loop.clicked.connect(lambda: self.start_cruise(loop_mode=True))
        l_cruise.addWidget(self.btn_cruise_loop)

        self.btn_cruise_stop = self._btn("⏹ 停止巡航", "#DC2626", "#B91C1C")
        self.btn_cruise_stop.setToolTip("立即停止正在进行的单次巡航或循环巡航")
        self.btn_cruise_stop.clicked.connect(lambda: self.stop_cruise(finished_naturally=False))
        self.btn_cruise_stop.setEnabled(False)
        l_cruise.addWidget(self.btn_cruise_stop)

        self.lbl_cruise_status = QLabel("")
        self.lbl_cruise_status.setStyleSheet("color: #6D28D9; font-weight: bold; font-size: 12px; margin-left: 8px;")
        l_cruise.addWidget(self.lbl_cruise_status)
        l_cruise.addStretch()
        l2_root.addLayout(l_cruise)

        root.addWidget(g2)

        # 表格
        split = QSplitter(Qt.Orientation.Vertical)

        bw = QWidget()
        bl = QVBoxLayout(bw)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(4)
        tool = QHBoxLayout()
        self.btn_locate = self._btn("📍 定位选中的浏览器", "#B45309", "#92400E")
        self.btn_locate.setToolTip("把选中的浏览器窗口切到最前面，并在页面上显示红色横幅（也可以直接双击表格中的行）")
        self.btn_locate.clicked.connect(self.on_locate_selected)
        tool.addWidget(self.btn_locate)
        self.btn_locate_failed = self._btn("📍 逐个定位上传失败的浏览器", "#DC2626", "#B91C1C")
        self.btn_locate_failed.setToolTip("每点一次，切换到下一个有上传失败图片的浏览器")
        self.btn_locate_failed.clicked.connect(self.on_locate_next_failed)
        tool.addWidget(self.btn_locate_failed)
        self.btn_rename = self._btn("✏️ 设置浏览器备注", "#4B5563", "#374151")
        self.btn_rename.setToolTip("给选中的浏览器起个名字（如 Brave-037），会同步显示在该浏览器的窗口标题上")
        self.btn_rename.clicked.connect(self.on_rename_selected)
        tool.addWidget(self.btn_rename)
        tip = QLabel("💡 每个浏览器的窗口标题前都会显示 [FC-XXXXX 备注]，可在任务栏直接找到；双击行即可定位")
        tip.setStyleSheet("color: #6B7280; font-size: 11px;")
        tool.addWidget(tip)
        tool.addStretch()
        bl.addLayout(tool)

        self.tbl_browsers = QTableWidget(0, 8)
        self.tbl_browsers.setHorizontalHeaderLabels(["状态标记", "浏览器ID（备注）", "浏览器配置", "账号（仅参考）", "积分", "分配批次", "计划消耗 / 剩余", "进度"])
        self._setup_table(self.tbl_browsers, stretch_cols=(5, 7))
        self.tbl_browsers.cellDoubleClicked.connect(self._on_browser_double_clicked)
        bl.addWidget(self.tbl_browsers)
        split.addWidget(bw)

        self.tbl_batches = QTableWidget(0, 7)
        self.tbl_batches.setHorizontalHeaderLabels(["项目", "批次", "分镜序号", "积分", "分配浏览器（双击定位）", "图片上传", "生成结果"])
        self._setup_table(self.tbl_batches, stretch_cols=(0, 4, 5, 6))
        self.tbl_batches.cellDoubleClicked.connect(self._on_batch_double_clicked)
        split.addWidget(self.tbl_batches)
        split.setSizes([240, 320])
        root.addWidget(split, stretch=1)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(130)
        self.log_text.setStyleSheet("background-color: #1E293B; color: #E2E8F0; font-family: Consolas, monospace; font-size: 11px; border-radius: 4px;")
        root.addWidget(self.log_text)

    @staticmethod
    def _setup_table(t, stretch_cols):
        hdr = t.horizontalHeader()
        for c in range(t.columnCount()):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch if c in stretch_cols
                                     else QHeaderView.ResizeMode.ResizeToContents)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setStyleSheet("QTableWidget { background-color: white; border: 1px solid #D7CCC8; border-radius: 4px; font-size: 12px; color: #5D4037; }"
                        "QHeaderView::section { background-color: #EDE0D4; color: #5D4037; font-weight: bold; padding: 5px; border: none; }")

    def _log(self, msg):
        self.log_text.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        logger.info(f"[Hosted] {msg}")

    # ──────────────────────────────── 浏览器信息
    def _clients(self):
        try:
            return self.plugin_server.get_online_clients() if self.plugin_server else []
        except Exception:
            return []

    @staticmethod
    def _email(c):
        e = c.get("email") or ""
        if e:
            return e
        cid = c.get("client_id", "")
        if c.get("instance_id"):
            return ""
        return cid.split(" (W#")[0] if " (W#" in cid else cid

    @staticmethod
    def _iid(c):
        return (c or {}).get("instance_id") or (c or {}).get("iid") or ""

    def _alias(self, key):
        """备注：优先按浏览器 ID，其次按邮箱（兼容旧数据）。key 可以是 dict 或字符串。"""
        if isinstance(key, dict):
            iid = self._iid(key)
            if iid and self.aliases.get(iid):
                return self.aliases[iid]
            if key.get("instance_name"):
                return key["instance_name"]
            em = key.get("email") or ""
            return self.aliases.get(em, "") if em else ""
        return self.aliases.get(key, "") if key else ""

    def _label(self, x):
        """
        浏览器显示名：FC-XXXXX（备注）· 配置 · 邮箱
        x 可以是在线 client dict、plan entry、batch dict，或旧的邮箱字符串。
        """
        if isinstance(x, dict):
            if x.get("who"):
                # plan entry / batch：用分配时记录的身份，再补上最新备注
                c = self._client_for(x)
                return self._who(c) if c else x["who"]
            return self._who(x)
        a = self._alias(x)
        return f"{x}（{a}）" if a else (x or "")

    def _who(self, c):
        iid = self._iid(c)
        alias = self._alias(c)
        email = self._email(c)
        prof = c.get("profile") or ""
        parts = []
        head = iid or email or c.get("client_id", "")
        if alias:
            head += f"（{alias}）"
        parts.append(head)
        if prof and prof not in ("未知端口",):
            parts.append(prof)
        if iid and email:
            parts.append(email)
        return " · ".join(parts)

    def _client_for(self, entry):
        """只查找，不修改 plan。"""
        clients = self._clients()
        cid = entry.get("cid")
        for c in clients:
            if cid and c.get("client_id") == cid:
                return c
        iid = self._iid(entry)
        if iid:
            for c in clients:
                if c.get("instance_id") == iid and not c.get("secondary_tab"):
                    return c
            for c in clients:
                if c.get("instance_id") == iid:
                    return c
        return None

    def _is_low(self, c):
        return bool(c.get("points_known")) and int(c.get("remaining_points", 0)) < self.threshold

    def _resolve_client(self, entry):
        """按 client_id → 浏览器唯一 ID 找在线浏览器（页面刷新/重连后 ID 不变）；旧版插件才退回按唯一邮箱匹配。"""
        clients = self._clients()
        for c in clients:
            if c.get("client_id") == entry["cid"]:
                return c
        m = []
        iid = self._iid(entry)
        if iid:
            m = [c for c in clients if c.get("instance_id") == iid]
            m.sort(key=lambda c: bool(c.get("secondary_tab")))
            m = m[:1]
        elif entry.get("email"):
            m = [c for c in clients if not c.get("instance_id") and c.get("email") == entry["email"]]
        if len(m) == 1:
            old = entry["cid"]
            entry["cid"] = m[0]["client_id"]
            if old in self.plan and old != entry["cid"]:
                self.plan[entry["cid"]] = self.plan.pop(old)
                if hasattr(self, "run_released_cids") and old in self.run_released_cids:
                    self.run_released_cids.discard(old)
                    self.run_released_cids.add(entry["cid"])
                for b in self.batches:
                    if b.get("cid") == old:
                        b["cid"] = entry["cid"]
            return m[0]
        return None

    # ──────────────────────────────── 刷新 UI
    def _schedule_refresh(self, *a):
        if self._refresh_pending:
            return
        self._refresh_pending = True
        QTimer.singleShot(250, self._do_refresh)

    def _do_refresh(self):
        self._refresh_pending = False
        # 页面不可见时（切到其它标签页）不重建表格，等切回来再统一刷新，避免后台持续卡顿
        if not self.isVisible():
            self._refresh_dirty = True
            return
        self.refresh_all()

    def refresh_all(self):
        # 批量写表期间暂停「按内容自适应列宽」的逐格重算（浏览器/批次多时这是卡顿主因）
        from views.table_delegates import bulk_table_update
        with bulk_table_update(self.tbl_browsers):
            self._refresh_browsers()
        with bulk_table_update(self.tbl_batches):
            self._refresh_batches()

    def _refresh_browsers(self):
        clients = self._clients()
        low = sum(1 for c in clients if self._is_low(c))
        no_id = sum(1 for c in clients if not c.get("instance_id"))
        self._update_recognize_btn()
        if not self._is_recognizing():
            self.lbl_conn.setText("⚪ 未开启识别（插件休眠中，手动模式不受影响）")
        else:
            self.lbl_conn.setText(f"🟢 识别中 | 在线浏览器 {len(clients)} 个 | 已标记低积分 {low} 个"
                                  + (f" | ⚠️ {no_id} 个插件为旧版（无浏览器ID）" if no_id else ""))

        # 同一邮箱出现在多个不同浏览器（邮箱读取不准或真的同号多开）→ 提示
        email_count = {}
        for c in clients:
            em = self._email(c)
            if em and not c.get("secondary_tab"):
                email_count[em] = email_count.get(em, 0) + 1

        rows = sorted(clients, key=lambda c: (bool(c.get("secondary_tab")), (self._alias(c) or "").lower(), self._iid(c) or c.get("client_id", "")))
        online_ids = {c.get("client_id") for c in clients}
        offline = [e for cid, e in self.plan.items() if cid not in online_ids and not self._client_for(e)]
        self._browser_row_cids = [c.get("client_id") for c in rows] + [e["cid"] for e in offline]
        self.tbl_browsers.setUpdatesEnabled(False)
        try:
            self.tbl_browsers.setRowCount(len(rows) + len(offline))
            for i, c in enumerate(rows):
                cid = c.get("client_id")
                email = self._email(c)
                known = bool(c.get("points_known"))
                pts = int(c.get("remaining_points", 0)) if known else None
                entry = self.plan.get(cid)
                if not known:
                    mark, color = "⚪ 未读取积分", GRAY
                elif self._is_low(c):
                    mark, color = "🔴 低积分（已标记）", RED
                else:
                    mark, color = "🟢 正常", None
                if c.get("bg_ok") is False:
                    mark, color = mark + " | ⚠️插件后台未更新", YELLOW
                elif "bg_ok" not in c:
                    mark = mark + " | ❔后台版本未知"
                if c.get("secondary_tab"):
                    mark, color = "🟡 同一浏览器的第2个Flow标签页（不分配任务）", YELLOW
                if not c.get("instance_id"):
                    mark = mark + " | ⚠️旧版插件"
                iid = self._iid(c)
                alias = self._alias(c)
                saved = self.aliases.get(iid) if iid else ""
                if saved and (c.get("instance_name") or "") != saved and not c.get("_name_pushed"):
                    c["_name_pushed"] = True
                    self.plugin_server.set_instance_name(cid, saved)
                id_txt = (iid or "(旧版插件无ID)") + (f"（{alias}）" if alias else "")
                email_txt = email or "(未识别账号)"
                if email and email_count.get(email, 0) > 1:
                    email_txt += "  ⚠️同邮箱多个浏览器"
                tip = f"client_id: {cid}\n浏览器进程 PID: {c.get('browser_pid') or '-'}\n用户数据目录: {c.get('user_data_dir') or '-'}"
                self._put(self.tbl_browsers, i, 0, mark, color)
                self._put(self.tbl_browsers, i, 1, id_txt, color, tip=tip)
                self._put(self.tbl_browsers, i, 2, c.get("profile") or "识别中...", color, tip=c.get("user_data_dir") or None)
                self._put(self.tbl_browsers, i, 3, email_txt, color)
                self._put(self.tbl_browsers, i, 4, "-" if pts is None else str(pts), color, center=True)
                if entry:
                    bl = [b for b in self.batches if b["id"] in entry["batch_ids"]]
                    self._put(self.tbl_browsers, i, 5, "、".join(b["short"] for b in bl), color)
                    planned = sum(b["points"] for b in bl)
                    self._put(self.tbl_browsers, i, 6, f"{planned} / {(pts or 0) - planned}", color, center=True)
                    self._put(self.tbl_browsers, i, 7, self._browser_progress(bl), color)
                else:
                    for col in (5, 6, 7):
                        self._put(self.tbl_browsers, i, col, "", color)
            for j, e in enumerate(offline):
                i = len(rows) + j
                self._put(self.tbl_browsers, i, 0, "⚫ 已断开", GRAY)
                self._put(self.tbl_browsers, i, 1, e.get("who") or e.get("iid") or e["email"], GRAY)
                self._put(self.tbl_browsers, i, 2, "", GRAY)
                self._put(self.tbl_browsers, i, 3, e.get("email", ""), GRAY)
                self._put(self.tbl_browsers, i, 4, str(e.get("points", "-")), GRAY, center=True)
                bl = [b for b in self.batches if b["id"] in e["batch_ids"]]
                self._put(self.tbl_browsers, i, 5, "、".join(b["short"] for b in bl), GRAY)
                self._put(self.tbl_browsers, i, 6, "", GRAY)
                self._put(self.tbl_browsers, i, 7, self._browser_progress(bl), GRAY)
        finally:
            self.tbl_browsers.setUpdatesEnabled(True)

    @staticmethod
    def _browser_progress(bl):
        if not bl:
            return ""
        up_ok = sum(1 for b in bl if b["upload_state"] == "成功")
        done = sum(1 for b in bl if b["run_state"] == "完成")
        ok = sum(b["ok"] for b in bl)
        fail = sum(b["fail"] for b in bl)
        return f"上传 {up_ok}/{len(bl)} 批 | 生成完成 {done}/{len(bl)} 批 | ✅{ok} ❌{fail}"

    def _refresh_batches(self):
        total_pts = sum(b["points"] for b in self.batches)
        unassigned = [b for b in self.batches if not b.get("cid")]
        self.lbl_summary.setText(
            f"共 {len(self.batches)} 批 · {total_pts} 积分" + (f" · ⚠️ 未分配 {len(unassigned)} 批" if unassigned else ""))
        self.tbl_batches.setUpdatesEnabled(False)
        try:
            self.tbl_batches.setRowCount(len(self.batches))
            for i, b in enumerate(self.batches):
                self._put(self.tbl_batches, i, 0, b["project_label"], tip=b["project_path"])
                self._put(self.tbl_batches, i, 1, f"第 {b['batch_no']} 批", center=True)
                self._put(self.tbl_batches, i, 2, ", ".join(str(x + 1) for x in b["seg_indices"]))
                small = b["points"] < self.small_threshold
                self._put(self.tbl_batches, i, 3, f"{b['points']}" + (" (小)" if small else ""), center=True)
                if b.get("cid"):
                    self._put(self.tbl_batches, i, 4, self._label(b) + ("  [低积分号]" if b.get("to_low") else ""))
                else:
                    self._put(self.tbl_batches, i, 4, "⚠️ 未分配（没有积分足够的浏览器）", YELLOW)

                # 上传
                st = b["upload_state"]
                fails = b["upload_failed"]
                if st == "成功":
                    txt, col = f"✅ 成功 {len(b['images'])}/{len(b['images'])}", GREEN
                elif st == "失败":
                    names = "、".join(Path(p).name for p in fails)
                    txt, col = f"❌ 失败 {len(fails)} 张：{names}", RED
                elif st == "上传中":
                    txt, col = "⏳ 上传中...", BLUE
                else:
                    txt, col = f"未上传（{len(b['images'])} 张）", None
                tip = "\n".join(f"{Path(p).name}: {r}" for p, r in fails.items()) if fails else "\n".join(b["images"])
                self._put(self.tbl_batches, i, 5, txt, col, tip=tip)

                # 生成
                rs = b["run_state"]
                n = len(b["tasks"])
                col = {"完成": GREEN if b["fail"] == 0 else YELLOW, "生成中": BLUE, "已发送": BLUE,
                       "发送失败": RED, "连接断开": RED}.get(rs)
                txt = rs
                if rs == "未开始" and self.running and b.get("cid") and b["upload_state"] == "成功" and b["cid"] not in self.run_released_cids:
                    txt = "⏳ 排队等待下一批"
                    col = YELLOW
                elif rs in ("生成中", "完成", "连接断开", "已发送"):
                    txt = f"{rs} | ✅{b['ok']} ❌{b['fail']} / {n}"
                fail_tip = "\n".join(f"{Path(k).name}: {v}" for k, v in b["fail_msgs"].items())
                self._put(self.tbl_batches, i, 6, txt, col, tip=fail_tip or None)
        finally:
            self.tbl_batches.setUpdatesEnabled(True)

    def _put(self, table, row, col, text, color=None, center=False, tip=None):
        it = QTableWidgetItem(str(text))
        if center:
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if color:
            it.setBackground(QColor(color))
        if tip:
            it.setToolTip(str(tip))
        table.setItem(row, col, it)
