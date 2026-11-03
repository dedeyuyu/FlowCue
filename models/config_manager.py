# -*- coding: utf-8 -*-
import json
from pathlib import Path

class ConfigManager:
    """Manages application-wide settings in .app_config.json."""
    
    CONFIG_FILE_NAME = ".app_config.json"
    
    DEFAULT_MAX_BATCH_POINTS = 50
    DEFAULT_MAX_SUBTASKS_PER_BATCH = 10  # Default max subtasks per batch/account in hosted mode (0 means unlimited)
    DEFAULT_MIN_SEGMENT_CHARS = 45  # Default 45 chars (0 means disabled)
    DEFAULT_EDGE_EXTRA_DURATION = 2  # Default extra seconds for first & last segments (capped at max 10s)
    DEFAULT_CHAR_DURATION_RULES = [
        {"max_chars": 40, "duration": 4},
        {"max_chars": 90, "duration": 6},
        {"max_chars": 130, "duration": 8},
        {"max_chars": 170, "duration": 10}
    ]
    DEFAULT_DURATION_POINTS_RULES = [
        {"duration": 4, "points": 7},
        {"duration": 6, "points": 10},
        {"duration": 8, "points": 12},
        {"duration": 10, "points": 15}
    ]
    
    DEFAULT_FORCED_SPLIT_MARKER = "///"
    
    # Speech extraction defaults
    DEFAULT_SPEECH_LANGUAGE = "es"  # Default: Spanish
    SUPPORTED_LANGUAGES = [
        ("es", "西班牙语 (Spanish)"),
        ("en", "英语 (English)"),
        ("zh", "中文 (Chinese)"),
        ("pt", "葡萄牙语 (Portuguese)"),
        ("fr", "法语 (French)"),
        ("de", "德语 (German)"),
        ("it", "意大利语 (Italian)"),
        ("ja", "日语 (Japanese)"),
        ("ko", "韩语 (Korean)"),
        ("ar", "阿拉伯语 (Arabic)"),
        ("ne", "尼泊尔语 (Nepali)"),
    ]

    # Auto breath-trimming default padding (前留白 / 后留白, seconds)
    DEFAULT_BREATH_PAD_BEFORE = 0.10
    DEFAULT_BREATH_PAD_AFTER = 0.15

    # Speech-verify concurrency defaults
    # Each Gladia API key supports at most 3 concurrent requests → max total = num_keys * 3
    SPEECH_MAX_CONCURRENT_PER_KEY = 3
    DEFAULT_VERIFY_PARALLEL_TASKS = 4      # 任务并行数 (1..4)
    DEFAULT_VERIFY_PARALLEL_SEGMENTS = 10  # 分段并行数 (1..40)
    MAX_VERIFY_PARALLEL_TASKS = 4
    MAX_VERIFY_PARALLEL_SEGMENTS = 40

    # Batch splice concurrency defaults
    DEFAULT_SPLICE_PARALLEL_TASKS = 4      # 并行线程数 (1..4)
    MAX_SPLICE_PARALLEL_TASKS = 4
    
    # Video generation default rules
    DEFAULT_TASK_INTERVAL = 5
    DEFAULT_GENERATION_MODE = "VIDEO_FRAMES"
    DEFAULT_ASPECT_RATIO = "9:16"
    DEFAULT_BATCH_ASPECT_RATIO = "9:16"
    DEFAULT_VIDEO_MODEL = "omni_1_1_flash"
    DEFAULT_THEME_MODE = "light"

    SUPPORTED_THEME_MODES = [
        ("light", "☀️ 亮色模式 (Light)"),
        ("dark", "🌙 暗色模式 (Dark)"),
    ]
    
    SUPPORTED_GENERATION_MODES = [
        ("VIDEO_FRAMES", "帧模式 (First Frame / 影格)"),
        ("VIDEO_REFERENCES", "素材模式 (Ingredients / 素材)"),
    ]
    
    SUPPORTED_ASPECT_RATIOS = [
        ("9:16", "9:16 (竖屏)"),
        ("16:9", "16:9 (横屏)"),
    ]
    
    SUPPORTED_VIDEO_MODELS = [
        ("omni_1_1_flash", "Omni 1.1 Flash (默认)"),
        ("veo_3_1_lite", "Veo 3.1 - Lite"),
        ("veo_3_1_fast", "Veo 3.1 - Fast"),
        ("veo_3_1_quality", "Veo 3.1 - Quality"),
        ("veo_3_1_lite_low_priority", "Veo 3.1 - Lite [Lower Priority]"),
    ]
    
    # New Import column mapping defaults & supported types
    DEFAULT_IMPORT_COLUMNS = [
        "name",      # 第 1 列：名字
        "empty",     # 第 2 列：空列
        "empty",     # 第 3 列：空列
        "chinese",   # 第 4 列：中文文案
        "original",  # 第 5 列：原文文案
        "link",      # 第 6 列：链接
        "name",      # 第 7 列：名字（补充）
    ]
    
    SUPPORTED_IMPORT_COLUMN_TYPES = [
        ("name", "🏷️ 名字 (任务名称)"),
        ("chinese", "🇨🇳 中文 (中文文案)"),
        ("original", "📝 原文 (外语文案)"),
        ("link", "🔗 链接 (云盘链接)"),
        ("empty", "⬜ 空列 (忽略不读取)"),
    ]
    
    REQUIRED_IMPORT_COLUMN_TYPES = [
        ("name", "名字"),
        ("chinese", "中文"),
        ("original", "原文"),
        ("link", "链接"),
    ]
    
    def __init__(self, workspace_dir):
        self.workspace_dir = Path(workspace_dir)
        self.config_path = self.workspace_dir / self.CONFIG_FILE_NAME
        
        self.base_path = ""
        self.max_batch_points = self.DEFAULT_MAX_BATCH_POINTS
        self.max_subtasks_per_batch = self.DEFAULT_MAX_SUBTASKS_PER_BATCH
        self.min_segment_chars = self.DEFAULT_MIN_SEGMENT_CHARS
        self.edge_extra_duration = self.DEFAULT_EDGE_EXTRA_DURATION
        self.forced_split_marker = self.DEFAULT_FORCED_SPLIT_MARKER
        self.char_duration_rules = [dict(r) for r in self.DEFAULT_CHAR_DURATION_RULES]
        self.duration_points_rules = [dict(r) for r in self.DEFAULT_DURATION_POINTS_RULES]
        
        # Speech extraction settings
        self.gladia_api_keys = []      # List of Gladia API keys for round-robin
        self.elevenlabs_api_keys = []   # List of ElevenLabs API keys for round-robin
        self.speech_language = self.DEFAULT_SPEECH_LANGUAGE
        self._gladia_key_index = 0     # Current rotation index
        self._elevenlabs_key_index = 0 # Current rotation index

        # Auto breath-trimming default padding (前留白 / 后留白)
        self.breath_pad_before = self.DEFAULT_BREATH_PAD_BEFORE
        self.breath_pad_after = self.DEFAULT_BREATH_PAD_AFTER

        # Speech-verify / batch-splice concurrency settings
        self.verify_parallel_tasks = self.DEFAULT_VERIFY_PARALLEL_TASKS
        self.verify_parallel_segments = self.DEFAULT_VERIFY_PARALLEL_SEGMENTS
        self.splice_parallel_tasks = self.DEFAULT_SPLICE_PARALLEL_TASKS
        
        # Plugin server settings
        self.enable_plugin_server = True
        self.plugin_server_port = 18188
        
        # End frame settings
        self.DEFAULT_ENABLE_END_FRAME = False
        self.enable_end_frame = self.DEFAULT_ENABLE_END_FRAME
        
        # Video generation default rules
        self.task_interval = self.DEFAULT_TASK_INTERVAL
        self.default_generation_mode = self.DEFAULT_GENERATION_MODE
        self.default_aspect_ratio = self.DEFAULT_ASPECT_RATIO
        self.batch_default_aspect_ratio = self.DEFAULT_BATCH_ASPECT_RATIO
        self.default_video_model = self.DEFAULT_VIDEO_MODEL
        
        # Import columns mapping
        self.import_columns = list(self.DEFAULT_IMPORT_COLUMNS)

        # UI Theme mode ("light" or "dark")
        self.theme_mode = self.DEFAULT_THEME_MODE
        
        self._load_dotenv()
        self.load()

    def _load_dotenv(self):
        """Loads environment variables from .env file if it exists."""
        env_file = self.workspace_dir / ".env"
        if env_file.exists():
            try:
                import os
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
            except Exception:
                pass

    def load(self):
        """Loads configuration from .app_config.json."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.base_path = data.get("base_path", self.base_path)
                    self.max_batch_points = data.get("max_batch_points", self.DEFAULT_MAX_BATCH_POINTS)
                    self.max_subtasks_per_batch = self._clamp_int(
                        data.get("max_subtasks_per_batch", self.DEFAULT_MAX_SUBTASKS_PER_BATCH),
                        0, 100, self.DEFAULT_MAX_SUBTASKS_PER_BATCH,
                    )
                    self.min_segment_chars = data.get("min_segment_chars", self.DEFAULT_MIN_SEGMENT_CHARS)
                    try:
                        raw_edge_extra = data.get("edge_extra_duration", self.DEFAULT_EDGE_EXTRA_DURATION)
                        self.edge_extra_duration = max(0, min(10, int(raw_edge_extra)))
                    except (ValueError, TypeError):
                        self.edge_extra_duration = self.DEFAULT_EDGE_EXTRA_DURATION
                    self.forced_split_marker = data.get("forced_split_marker", self.DEFAULT_FORCED_SPLIT_MARKER)
                    
                    char_rules = data.get("char_duration_rules")
                    if char_rules and isinstance(char_rules, list):
                        self.char_duration_rules = char_rules
                    else:
                        self.char_duration_rules = [dict(r) for r in self.DEFAULT_CHAR_DURATION_RULES]
                        
                    dur_rules = data.get("duration_points_rules")
                    if dur_rules and isinstance(dur_rules, list):
                        self.duration_points_rules = dur_rules
                    else:
                        self.duration_points_rules = [dict(r) for r in self.DEFAULT_DURATION_POINTS_RULES]
                    
                    # Load speech extraction settings
                    # (backward compatible: legacy single-key fields "gladia_api_key" / "elevenlabs_api_key"
                    #  and string values are merged into the key lists and count as one key each)
                    self.gladia_api_keys = self._normalize_key_list(
                        data.get("gladia_api_keys", []), data.get("gladia_api_key", "")
                    )
                    self.elevenlabs_api_keys = self._normalize_key_list(
                        data.get("elevenlabs_api_keys", []), data.get("elevenlabs_api_key", "")
                    )
                    self.speech_language = data.get("speech_language", self.DEFAULT_SPEECH_LANGUAGE)

                    # Auto breath-trimming default padding (前留白 / 后留白)
                    self.breath_pad_before = self._clamp_float(
                        data.get("breath_pad_before", self.DEFAULT_BREATH_PAD_BEFORE),
                        0.0, 2.0, self.DEFAULT_BREATH_PAD_BEFORE,
                    )
                    self.breath_pad_after = self._clamp_float(
                        data.get("breath_pad_after", self.DEFAULT_BREATH_PAD_AFTER),
                        0.0, 2.0, self.DEFAULT_BREATH_PAD_AFTER,
                    )

                    # Speech-verify / batch-splice concurrency settings
                    self.verify_parallel_tasks = self._clamp_int(
                        data.get("verify_parallel_tasks", self.DEFAULT_VERIFY_PARALLEL_TASKS),
                        1, self.MAX_VERIFY_PARALLEL_TASKS, self.DEFAULT_VERIFY_PARALLEL_TASKS,
                    )
                    self.verify_parallel_segments = self._clamp_int(
                        data.get("verify_parallel_segments", self.DEFAULT_VERIFY_PARALLEL_SEGMENTS),
                        1, self.MAX_VERIFY_PARALLEL_SEGMENTS, self.DEFAULT_VERIFY_PARALLEL_SEGMENTS,
                    )
                    self.splice_parallel_tasks = self._clamp_int(
                        data.get("splice_parallel_tasks", self.DEFAULT_SPLICE_PARALLEL_TASKS),
                        1, self.MAX_SPLICE_PARALLEL_TASKS, self.DEFAULT_SPLICE_PARALLEL_TASKS,
                    )
                    
                    # Environment variable overrides (supports comma- or newline-separated keys)
                    import os
                    env_gladia = os.environ.get("GLADIA_API_KEYS") or os.environ.get("GLADIA_API_KEY")
                    if env_gladia:
                        k_list = self._normalize_key_list(env_gladia)
                        if k_list:
                            self.gladia_api_keys = k_list
                            self._gladia_from_env = True

                    env_eleven = os.environ.get("ELEVENLABS_API_KEYS") or os.environ.get("ELEVENLABS_API_KEY")
                    if env_eleven:
                        k_list = self._normalize_key_list(env_eleven)
                        if k_list:
                            self.elevenlabs_api_keys = k_list
                            self._eleven_from_env = True

                    # Load plugin server settings
                    self.enable_plugin_server = data.get("enable_plugin_server", True)
                    self.plugin_server_port = data.get("plugin_server_port", 18188)
                    
                    # Load end frame setting
                    self.enable_end_frame = data.get("enable_end_frame", getattr(self, "DEFAULT_ENABLE_END_FRAME", False))
                    
                    # Load video generation default rules
                    try:
                        raw_interval = data.get("task_interval", self.DEFAULT_TASK_INTERVAL)
                        self.task_interval = max(0, int(raw_interval))
                    except (ValueError, TypeError):
                        self.task_interval = self.DEFAULT_TASK_INTERVAL
                        
                    mode_val = data.get("default_generation_mode", self.DEFAULT_GENERATION_MODE)
                    valid_modes = {m[0] for m in self.SUPPORTED_GENERATION_MODES}
                    self.default_generation_mode = mode_val if mode_val in valid_modes else self.DEFAULT_GENERATION_MODE
                    
                    aspect_val = data.get("default_aspect_ratio", self.DEFAULT_ASPECT_RATIO)
                    valid_aspects = {a[0] for a in self.SUPPORTED_ASPECT_RATIOS}
                    self.default_aspect_ratio = aspect_val if aspect_val in valid_aspects else self.DEFAULT_ASPECT_RATIO
                    
                    batch_aspect_val = data.get("batch_default_aspect_ratio", self.default_aspect_ratio)
                    self.batch_default_aspect_ratio = batch_aspect_val if batch_aspect_val in valid_aspects else self.DEFAULT_BATCH_ASPECT_RATIO
                    
                    model_val = data.get("default_video_model", self.DEFAULT_VIDEO_MODEL)
                    valid_models = {m[0] for m in self.SUPPORTED_VIDEO_MODELS}
                    self.default_video_model = model_val if model_val in valid_models else self.DEFAULT_VIDEO_MODEL

                    raw_cols = data.get("import_columns")
                    valid_col_types = {c[0] for c in self.SUPPORTED_IMPORT_COLUMN_TYPES}
                    required_col_types = {c[0] for c in self.REQUIRED_IMPORT_COLUMN_TYPES}
                    if (
                        isinstance(raw_cols, list)
                        and len(raw_cols) >= 4
                        and all(c in valid_col_types for c in raw_cols)
                        and required_col_types.issubset(set(raw_cols))
                    ):
                        self.import_columns = list(raw_cols)
                    else:
                        self.import_columns = list(self.DEFAULT_IMPORT_COLUMNS)

                    raw_theme = str(data.get("theme_mode", self.DEFAULT_THEME_MODE)).lower()
                    self.theme_mode = "dark" if raw_theme == "dark" else "light"
            except Exception as e:
                print(f"Error loading config: {e}")

    def save(self):
        """Saves current configuration to .app_config.json without losing existing keys."""
        data = {}
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}

        # Do not persist keys back into .app_config.json if they are managed via .env
        gladia_to_save = [] if getattr(self, "_gladia_from_env", False) else self.gladia_api_keys
        eleven_to_save = [] if getattr(self, "_eleven_from_env", False) else self.elevenlabs_api_keys

        # Legacy single-key fields were merged into the key lists on load; drop them so a key
        # removed by the user in settings does not re-appear from the legacy field.
        if not getattr(self, "_gladia_from_env", False):
            data.pop("gladia_api_key", None)
        if not getattr(self, "_eleven_from_env", False):
            data.pop("elevenlabs_api_key", None)

        data.update({
            "base_path": self.base_path or data.get("base_path", ""),
            "max_batch_points": self.max_batch_points,
            "max_subtasks_per_batch": int(getattr(self, "max_subtasks_per_batch", self.DEFAULT_MAX_SUBTASKS_PER_BATCH)),
            "min_segment_chars": self.min_segment_chars,
            "edge_extra_duration": getattr(self, "edge_extra_duration", self.DEFAULT_EDGE_EXTRA_DURATION),
            "forced_split_marker": self.forced_split_marker,
            "char_duration_rules": self.char_duration_rules,
            "duration_points_rules": self.duration_points_rules,
            "gladia_api_keys": gladia_to_save,
            "elevenlabs_api_keys": eleven_to_save,
            "speech_language": self.speech_language,
            "breath_pad_before": round(float(getattr(self, "breath_pad_before", self.DEFAULT_BREATH_PAD_BEFORE)), 3),
            "breath_pad_after": round(float(getattr(self, "breath_pad_after", self.DEFAULT_BREATH_PAD_AFTER)), 3),
            "verify_parallel_tasks": int(getattr(self, "verify_parallel_tasks", self.DEFAULT_VERIFY_PARALLEL_TASKS)),
            "verify_parallel_segments": int(getattr(self, "verify_parallel_segments", self.DEFAULT_VERIFY_PARALLEL_SEGMENTS)),
            "splice_parallel_tasks": int(getattr(self, "splice_parallel_tasks", self.DEFAULT_SPLICE_PARALLEL_TASKS)),
            "enable_plugin_server": self.enable_plugin_server,
            "plugin_server_port": self.plugin_server_port,
            "enable_end_frame": self.enable_end_frame,
            "task_interval": self.task_interval,
            "default_generation_mode": self.default_generation_mode,
            "default_aspect_ratio": self.default_aspect_ratio,
            "batch_default_aspect_ratio": getattr(self, "batch_default_aspect_ratio", self.DEFAULT_BATCH_ASPECT_RATIO),
            "default_video_model": self.default_video_model,
            "import_columns": list(self.import_columns) if getattr(self, "import_columns", None) else list(self.DEFAULT_IMPORT_COLUMNS),
            "theme_mode": getattr(self, "theme_mode", self.DEFAULT_THEME_MODE),
        })
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False

    def reset_to_defaults(self):
        self.max_batch_points = self.DEFAULT_MAX_BATCH_POINTS
        self.max_subtasks_per_batch = self.DEFAULT_MAX_SUBTASKS_PER_BATCH
        self.min_segment_chars = self.DEFAULT_MIN_SEGMENT_CHARS
        self.edge_extra_duration = self.DEFAULT_EDGE_EXTRA_DURATION
        self.char_duration_rules = [dict(r) for r in self.DEFAULT_CHAR_DURATION_RULES]
        self.duration_points_rules = [dict(r) for r in self.DEFAULT_DURATION_POINTS_RULES]
        self.enable_end_frame = getattr(self, "DEFAULT_ENABLE_END_FRAME", False)
        self.task_interval = self.DEFAULT_TASK_INTERVAL
        self.default_generation_mode = self.DEFAULT_GENERATION_MODE
        self.default_aspect_ratio = self.DEFAULT_ASPECT_RATIO
        self.batch_default_aspect_ratio = self.DEFAULT_BATCH_ASPECT_RATIO
        self.default_video_model = self.DEFAULT_VIDEO_MODEL
        self.import_columns = list(self.DEFAULT_IMPORT_COLUMNS)
        self.breath_pad_before = self.DEFAULT_BREATH_PAD_BEFORE
        self.breath_pad_after = self.DEFAULT_BREATH_PAD_AFTER
        self.save()

    @staticmethod
    def _normalize_key_list(*sources) -> list:
        """Merges API keys from lists / comma- or newline-separated strings into a de-duplicated list
        (order preserved). Used for backward-compatible loading of single-key and multi-key configs."""
        keys = []
        seen = set()
        for src in sources:
            if not src:
                continue
            if isinstance(src, str):
                items = src.replace(",", "\n").splitlines()
            elif isinstance(src, (list, tuple)):
                items = []
                for it in src:
                    if isinstance(it, str):
                        items.extend(it.replace(",", "\n").splitlines())
            else:
                continue
            for k in items:
                k = str(k).strip().strip("'\"").strip()
                if k and k not in seen:
                    seen.add(k)
                    keys.append(k)
        return keys

    @staticmethod
    def _clamp_int(value, lo, hi, default):
        try:
            return max(lo, min(hi, int(value)))
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _clamp_float(value, lo, hi, default):
        try:
            return max(lo, min(hi, float(value)))
        except (ValueError, TypeError):
            return default

    def get_speech_keys(self, engine: str = "gladia") -> list:
        """Returns the configured API key list for the given speech engine ("gladia" / "elevenlabs")."""
        if engine == "elevenlabs":
            return list(self.elevenlabs_api_keys or [])
        return list(self.gladia_api_keys or [])

    def get_duration_for_length(self, length, is_edge=False):
        """Calculates duration in seconds for a given character length.
        When is_edge=True (first or last segment of a project), adds edge_extra_duration capped at 10s."""
        sorted_rules = sorted(self.char_duration_rules, key=lambda x: x["max_chars"])
        base_dur = 10
        matched = False
        for r in sorted_rules:
            if length <= r["max_chars"]:
                base_dur = r["duration"]
                matched = True
                break
        if not matched and sorted_rules:
            base_dur = sorted_rules[-1]["duration"]
        if is_edge:
            extra = max(0, int(getattr(self, "edge_extra_duration", 0) or 0))
            if extra > 0 and base_dur < 10:
                return min(10, base_dur + extra)
        return base_dur

    def get_duration_label(self, length, is_edge=False):
        """Calculates duration label (e.g. '4s', '6s', '超时 (>10s)') for a length."""
        sorted_rules = sorted(self.char_duration_rules, key=lambda x: x["max_chars"])
        for r in sorted_rules:
            if length <= r["max_chars"]:
                dur = self.get_duration_for_length(length, is_edge=is_edge)
                return f"{dur}s"
        if sorted_rules:
            max_dur = sorted_rules[-1]["duration"]
            return f"超时 (>{max_dur}s)"
        return "10s"

    def get_max_chars(self):
        """Returns the maximum character threshold defined in char_duration_rules."""
        if self.char_duration_rules:
            return max(r["max_chars"] for r in self.char_duration_rules)
        return 170

    def get_points_for_duration(self, duration):
        """Calculates points cost for a given duration in seconds."""
        for r in self.duration_points_rules:
            if r["duration"] == duration:
                return r["points"]
        sorted_pts = sorted(self.duration_points_rules, key=lambda x: x["duration"])
        for r in sorted_pts:
            if duration <= r["duration"]:
                return r["points"]
        if sorted_pts:
            return sorted_pts[-1]["points"]
        return 7

    def get_next_gladia_key(self):
        """Returns the next Gladia API key using round-robin rotation.
        Returns None if no keys are configured."""
        if not self.gladia_api_keys:
            return None
        key = self.gladia_api_keys[self._gladia_key_index % len(self.gladia_api_keys)]
        self._gladia_key_index += 1
        return key

    def get_next_elevenlabs_key(self):
        """Returns the next ElevenLabs API key using round-robin rotation.
        Returns None if no keys are configured."""
        if not self.elevenlabs_api_keys:
            return None
        key = self.elevenlabs_api_keys[self._elevenlabs_key_index % len(self.elevenlabs_api_keys)]
        self._elevenlabs_key_index += 1
        return key

    def reset_key_rotation(self):
        """Resets the round-robin key rotation indices to 0."""
        self._gladia_key_index = 0
        self._elevenlabs_key_index = 0
