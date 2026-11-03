/**
 * reels_electron_bootstrap.js
 * FlowCue 批量Reels 宿主引导层（零侵入加载 D:\Antigravity\videokit）
 *
 * 作用：
 * 1. 固定 userData 到 %APPDATA%\videokit 并启动双保险预设同步备份（%APPDATA%\FlowCue\reels-presets-backup），保证更新软件绝不丢失字幕/覆层预设
 * 2. 启动本地静态资源服务（映射 VideoKit/src 目录），固定默认端口确保 localStorage Origin 永不改变
 * 3. 在主窗口加载完成后自动切入「🎬 批量Reels」工作台并注入 reels_flowcue_enhancements.js 增强补丁
 * 4. 提供本地控制端口 (FLOWCUE_CTRL_PORT) 及毫秒级 UDP 焦点通知，供 FlowCue (PyQt6) 激活 Win32 键盘输入焦点、
 *    单条/批量推送已合并成片+SRT+逐词时间戳、以及同步 API Keys。
 */

const { app } = require('electron');
const http = require('http');
const dgram = require('dgram');
const fs = require('fs');
const path = require('path');

const VIDEOKIT_ROOT = process.env.VIDEOKIT_ROOT || 'D:\\Antigravity\\videokit';
const VIDEOKIT_SRC = path.join(VIDEOKIT_ROOT, 'src');
const VITE_PORT = Number(process.env.VITE_PORT) || 5179;
const CTRL_PORT = Number(process.env.FLOWCUE_CTRL_PORT) || 5180;
const PY_FOCUS_UDP_PORT = Number(process.env.FLOWCUE_FOCUS_UDP_PORT) || 0;
const WORKBENCH_MODE = (process.env.FLOWCUE_WORKBENCH_MODE || 'batch-reels').trim();
const ENHANCEMENTS_JS_PATH = path.join(__dirname, 'reels_flowcue_enhancements.js');
// FlowCue 后台预热/嵌入前隐藏：主窗口创建后（显示前）立即移到屏幕外并隐藏任务栏按钮，嵌入 PyQt 后才真正可见，杜绝窗口外露浮动
const HIDE_UNTIL_EMBED = process.env.FLOWCUE_HIDE_UNTIL_EMBED === '1';
const OFFSCREEN_POS = -32000;
const BOOT_T0 = Date.now();
function bootElapsed() { return `${Date.now() - BOOT_T0}ms`; }

process.env.VITE_PORT = String(VITE_PORT);
// 禁用 main.js 开发态 fs.watch 自动重启
global._isWatching = true;

// ═══════════════════════════════════════════════════════════════════════════
// 0. 强制固定 userData 路径到 %APPDATA%\videokit + 字幕/覆层预设多路合并与永久备份
// ═══════════════════════════════════════════════════════════════════════════
const appDataDir = app.getPath('appData');
const videokitUserData = WORKBENCH_MODE === 'visual-review'
    ? path.join(appDataDir, 'videokit-visual-review')
    : path.join(appDataDir, 'videokit');
const electronLegacyUserData = path.join(appDataDir, 'Electron');
const flowcueBackupDir = path.join(appDataDir, 'FlowCue', 'reels-presets-backup');

try {
    app.setName(WORKBENCH_MODE === 'visual-review' ? 'videokit-visual-review' : 'videokit');
    app.setPath('userData', videokitUserData);
} catch (e) {
    console.warn('[FlowCue-Reels] setPath userData warning:', e.message);
}

const PRESET_FILE_PRIMARY = path.join(videokitUserData, 'videokit-presets', 'local-storage-presets.json');
const PRESET_FILE_LEGACY  = path.join(electronLegacyUserData, 'videokit-presets', 'local-storage-presets.json');
const PRESET_FILE_BACKUP  = path.join(flowcueBackupDir, 'local-storage-presets.json');

const PRESET_KEYS = [
    'reels_style_presets',
    'reels_overlay_presets',
    'reels_overlay_group_presets',
    'reels_multi_export_presets',
    'reels_export_presets',
    'reels_batch_custom_presets',
    'reels_custom_fonts',
];

function readPresetSnapshotFile(filePath) {
    try {
        if (!fs.existsSync(filePath)) return {};
        const parsed = JSON.parse(fs.readFileSync(filePath, 'utf8'));
        if (parsed && typeof parsed.entries === 'object' && parsed.entries) {
            return parsed.entries;
        }
        return {};
    } catch (_) {
        return {};
    }
}

function mergePresetEntries(entriesList) {
    const mergedEntries = {};
    for (const key of PRESET_KEYS) {
        let combinedObj = {};
        let hasAny = false;
        for (const entries of entriesList) {
            const rawStr = entries?.[key];
            if (typeof rawStr !== 'string' || !rawStr.trim()) continue;
            try {
                const parsed = JSON.parse(rawStr);
                if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
                    combinedObj = { ...combinedObj, ...parsed };
                    hasAny = true;
                } else if (Array.isArray(parsed) && parsed.length > 0) {
                    combinedObj = parsed;
                    hasAny = true;
                }
            } catch (_) {}
        }
        if (hasAny) {
            mergedEntries[key] = JSON.stringify(combinedObj);
        }
    }
    return mergedEntries;
}

function syncAndBackupPresetFiles(extraEntries = null) {
    try {
        const eLegacy  = readPresetSnapshotFile(PRESET_FILE_LEGACY);
        const eBackup  = readPresetSnapshotFile(PRESET_FILE_BACKUP);
        const ePrimary = readPresetSnapshotFile(PRESET_FILE_PRIMARY);
        const list = [eLegacy, eBackup, ePrimary];
        if (extraEntries && typeof extraEntries === 'object') {
            list.push(extraEntries);
        }
        const merged = mergePresetEntries(list);
        if (Object.keys(merged).length === 0) return merged;

        const payload = JSON.stringify({
            version: 1,
            updatedAt: new Date().toISOString(),
            entries: merged,
        }, null, 2);

        for (const targetFile of [PRESET_FILE_PRIMARY, PRESET_FILE_BACKUP]) {
            const dir = path.dirname(targetFile);
            if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
            fs.writeFileSync(targetFile, payload, 'utf8');
        }
        return merged;
    } catch (e) {
        console.warn('[FlowCue-Reels] syncAndBackupPresetFiles warning:', e.message);
        return {};
    }
}

// 启动时立即合并同步一次预设文件（结果缓存供首次页面激活直接复用，避免重复读写磁盘）
let _startupMergedPresets = syncAndBackupPresetFiles();

let capturedMainWindow = null;
// rendererReady: 已拿到主窗口 HWND，可供 PyQt 嵌入；pageActivated: 页面脚本加载完成且已切入工作台，可安全注入任务
let rendererReady = false;
let pageActivated = false;
let activationPromise = null;
let activationLoadSeq = -1;
let pageLoadSeq = 0;
const pendingTasks = [];
const udpClient = dgram.createSocket('udp4');

// 增强补丁脚本缓存：仅在文件 mtime 变化时重新读取（避免每次激活都读 80KB 文件）
let _enhancementsCache = { mtimeMs: -1, code: '' };
function getEnhancementsCode() {
    try {
        const st = fs.statSync(ENHANCEMENTS_JS_PATH);
        if (st.mtimeMs !== _enhancementsCache.mtimeMs) {
            _enhancementsCache = { mtimeMs: st.mtimeMs, code: fs.readFileSync(ENHANCEMENTS_JS_PATH, 'utf8') };
        }
    } catch (e) {
        console.warn('[FlowCue-Reels] Failed to read enhancements JS:', e.message);
    }
    return _enhancementsCache.code;
}

function notifyPythonFocusHwnd() {
    if (capturedMainWindow && !capturedMainWindow.isDestroyed()) {
        try {
            capturedMainWindow.focus();
            capturedMainWindow.webContents.focus();
        } catch (_) {}
    }
    if (PY_FOCUS_UDP_PORT > 0) {
        const msg = Buffer.from('FOCUS');
        udpClient.send(msg, 0, msg.length, PY_FOCUS_UDP_PORT, '127.0.0.1', () => {});
    }
}

const MIME_MAP = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.mjs': 'application/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.webp': 'image/webp',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.ttf': 'font/ttf',
    '.otf': 'font/otf',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
    '.mp4': 'video/mp4',
    '.webm': 'video/webm',
    '.mp3': 'audio/mpeg',
    '.wav': 'audio/wav',
};

// 1. 启动静态 HTTP 服务供 Electron 主窗口加载 VideoKit/src
const staticServer = http.createServer((req, res) => {
    try {
        const parsedUrl = new URL(req.url || '/', `http://localhost:${VITE_PORT}`);
        let pathname = decodeURIComponent(parsedUrl.pathname || '/');
        if (pathname === '/' || pathname === '') {
            pathname = '/index.html';
        }
        const safeRel = path.normalize(pathname).replace(/^(\.\.(\/|\\|$))+/, '');
        let filePath = path.join(VIDEOKIT_SRC, safeRel);
        if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
            const altPath = path.join(VIDEOKIT_ROOT, safeRel);
            if (fs.existsSync(altPath) && fs.statSync(altPath).isFile()) {
                filePath = altPath;
            } else {
                res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
                res.end('Not Found');
                return;
            }
        }

        const ext = path.extname(filePath).toLowerCase();
        const contentType = MIME_MAP[ext] || 'application/octet-stream';
        const stat = fs.statSync(filePath);
        const range = req.headers.range;

        if (range) {
            const parts = range.replace(/bytes=/, '').split('-');
            const start = parseInt(parts[0], 10) || 0;
            const end = parts[1] ? parseInt(parts[1], 10) : stat.size - 1;
            const chunkSize = Math.max(0, end - start + 1);
            res.writeHead(206, {
                'Content-Range': `bytes ${start}-${end}/${stat.size}`,
                'Accept-Ranges': 'bytes',
                'Content-Length': chunkSize,
                'Content-Type': contentType,
                'Access-Control-Allow-Origin': '*',
            });
            fs.createReadStream(filePath, { start, end }).pipe(res);
        } else {
            res.writeHead(200, {
                'Content-Length': stat.size,
                'Content-Type': contentType,
                'Access-Control-Allow-Origin': '*',
                'Cache-Control': 'no-cache',
            });
            fs.createReadStream(filePath).pipe(res);
        }
    } catch (err) {
        res.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' });
        res.end(String(err.message || err));
    }
});

staticServer.on('error', (err) => {
    console.warn('[FlowCue-Reels] Static server port warning:', err.message);
});

staticServer.listen(VITE_PORT, '127.0.0.1', () => {
    console.log(`[FlowCue-Reels] Static server listening on http://127.0.0.1:${VITE_PORT}`);
});

function getWindowHwndNumber(win) {
    if (!win || win.isDestroyed()) return 0;
    try {
        const buf = win.getNativeWindowHandle();
        if (!buf || !buf.length) return 0;
        if (buf.length >= 8) {
            return Number(buf.readBigUInt64LE(0));
        }
        return buf.readUInt32LE(0);
    } catch (e) {
        return 0;
    }
}

async function activateBatchReelsInRenderer(win) {
    if (!win || win.isDestroyed()) return;
    // 首次激活直接复用启动时已合并好的预设；之后（页面重载/手动重新激活）再重新合并磁盘最新快照
    const mergedPresets = _startupMergedPresets || syncAndBackupPresetFiles();
    _startupMergedPresets = null;
    const presetsJson = JSON.stringify(mergedPresets);
    const enhancementsCode = getEnhancementsCode();
    const script = `
    (function() {
        try {
            window.__FLOWCUE_CTRL_PORT__ = ${CTRL_PORT};
            // 恢复/合并所有持久化的字幕预设和覆层预设到 localStorage
            const diskPresets = ${presetsJson};
            if (diskPresets && typeof diskPresets === 'object') {
                for (const [k, diskValStr] of Object.entries(diskPresets)) {
                    if (typeof diskValStr !== 'string' || !diskValStr) continue;
                    const curStr = localStorage.getItem(k);
                    if (!curStr || curStr === '{}' || curStr === '[]') {
                        localStorage.setItem(k, diskValStr);
                    } else {
                        try {
                            const diskObj = JSON.parse(diskValStr);
                            const curObj = JSON.parse(curStr);
                            if (diskObj && curObj && typeof diskObj === 'object' && typeof curObj === 'object' && !Array.isArray(diskObj)) {
                                localStorage.setItem(k, JSON.stringify({ ...diskObj, ...curObj }));
                            }
                        } catch (_) {}
                    }
                }
            }

            if (!document.getElementById('flowcue-embedded-style')) {
                const style = document.createElement('style');
                style.id = 'flowcue-embedded-style';
                style.textContent = \`
                    body.flowcue-embedded header.titlebar {
                        display: none !important;
                    }
                    body.flowcue-embedded #path-warning-banner {
                        display: none !important;
                    }
                    body.flowcue-embedded .app {
                        height: 100vh !important;
                        display: flex !important;
                        flex-direction: column !important;
                    }
                    body.flowcue-embedded main.content {
                        flex: 1 !important;
                        height: 100vh !important;
                        max-height: 100vh !important;
                        padding: 6px 10px !important;
                        overflow: auto !important;
                    }
                \`;
                document.head.appendChild(style);
            }
            document.body.classList.add('flowcue-embedded');
            localStorage.setItem('pathWarningDismissed', '1');
            const reelsTabBtn = document.querySelector('button.tab[data-tab="batch-reels"]');
            if (reelsTabBtn) {
                reelsTabBtn.click();
            }
            if (typeof _loadSavedPresets === 'function') {
                try { _loadSavedPresets(); } catch (_) {}
            }
            setTimeout(() => {
                if (typeof reelsPreviewZoom === 'function') {
                    reelsPreviewZoom('fit');
                }
            }, 250);
            return true;
        } catch (err) {
            console.error('[FlowCue-Reels] activate error:', err);
            return false;
        }
    })();
    `;
    try {
        await win.webContents.executeJavaScript(script, true);
        if (enhancementsCode) {
            await win.webContents.executeJavaScript(enhancementsCode, true);
        }
    } catch (e) {
        console.warn('[FlowCue-Reels] activateBatchReelsInRenderer failed:', e.message);
    }
}

async function activateVisualReviewInRenderer(win) {
    if (!win || win.isDestroyed()) return;
    const enhancementsCode = getEnhancementsCode();

    const script = `
    (function() {
        try {
            window.__FLOWCUE_CTRL_PORT__ = ${CTRL_PORT};
            if (!document.getElementById('flowcue-embedded-style')) {
                const style = document.createElement('style');
                style.id = 'flowcue-embedded-style';
                style.textContent = \`
                    body.flowcue-embedded header.titlebar {
                        display: none !important;
                    }
                    body.flowcue-embedded #path-warning-banner {
                        display: none !important;
                    }
                    body.flowcue-embedded aside.media-sidebar {
                        display: none !important;
                    }
                    body.flowcue-embedded .app {
                        height: 100vh !important;
                        display: flex !important;
                        flex-direction: column !important;
                    }
                    body.flowcue-embedded main.content {
                        flex: 1 !important;
                        height: 100vh !important;
                        max-height: 100vh !important;
                        padding: 6px 10px !important;
                        overflow: auto !important;
                    }
                \`;
                document.head.appendChild(style);
            }
            document.body.classList.add('flowcue-embedded');
            localStorage.setItem('pathWarningDismissed', '1');
            const mediaTabBtn = document.querySelector('button.tab[data-tab="media"]');
            if (mediaTabBtn) {
                mediaTabBtn.click();
            }
            const vrSubBtn = document.querySelector('button.sidebar-item[data-subtab="media-visualreview"]');
            if (vrSubBtn) {
                vrSubBtn.click();
            }
            return true;
        } catch (err) {
            console.error('[FlowCue-VisualReview] activate error:', err);
            return false;
        }
    })();
    `;
    try {
        await win.webContents.executeJavaScript(script, true);
        if (enhancementsCode) {
            await win.webContents.executeJavaScript(enhancementsCode, true);
        }
    } catch (e) {
        console.warn('[FlowCue-VisualReview] activateVisualReviewInRenderer failed:', e.message);
    }
}

async function injectVisualReviewFolderIntoRenderer(win, folderPath) {
    if (!win || win.isDestroyed() || !folderPath) return { ok: false, error: '窗口或文件夹路径无效' };
    const serializedPath = JSON.stringify(String(folderPath));
    const js = `
    (async function() {
        const folderPath = ${serializedPath};
        const mediaTabBtn = document.querySelector('button.tab[data-tab="media"]');
        if (mediaTabBtn && !mediaTabBtn.classList.contains('active')) {
            mediaTabBtn.click();
        }
        const vrSubBtn = document.querySelector('button.sidebar-item[data-subtab="media-visualreview"]');
        if (vrSubBtn && !vrSubBtn.classList.contains('active')) {
            vrSubBtn.click();
        }
        if (typeof window.visualReviewLoadDroppedFolder === 'function') {
            await window.visualReviewLoadDroppedFolder(folderPath, { silent: false });
            return { ok: true, folderPath };
        }
        throw new Error('visualReviewLoadDroppedFolder 尚未就绪');
    })();
    `;
    return await win.webContents.executeJavaScript(js, true);
}

function enrichPayloadFromManifest(payload) {
    const data = { ...(payload || {}) };
    const manifestPath = data.manifest_path || data.project_path || '';
    if (manifestPath && fs.existsSync(manifestPath)) {
        try {
            const m = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
            if (!data.duration && (m.total_duration || m.output_duration)) {
                data.duration = Number(m.total_duration || m.output_duration || 0);
            }
            if ((!Array.isArray(data.words) || data.words.length === 0) && Array.isArray(m.merged_words)) {
                data.words = m.merged_words;
            }
            if ((!Array.isArray(data.segments) || data.segments.length === 0) && Array.isArray(m.clips)) {
                data.segments = m.clips;
            }
        } catch (_) {}
    }
    return data;
}

async function injectFlowCueTaskIntoRenderer(win, rawPayload) {
    if (!win || win.isDestroyed()) {
        throw new Error('Reels 窗口尚未就绪');
    }
    const payload = enrichPayloadFromManifest(rawPayload);
    const serialized = JSON.stringify(payload || {});
    const js = `
    (async function() {
        const data = ${serialized};
        const reelsTabBtn = document.querySelector('button.tab[data-tab="batch-reels"]');
        if (reelsTabBtn && !reelsTabBtn.classList.contains('active')) {
            reelsTabBtn.click();
        }
        if (typeof window.reelsCreateTaskFromAutoEditResult !== 'function') {
            throw new Error('reelsCreateTaskFromAutoEditResult 尚未加载完成');
        }
        const autoEditResult = {
            output_path: data.video_path || data.output_path || '',
            srt_path: data.srt_path || '',
            output_duration: Number(data.duration || data.output_duration || 0),
            project_path: data.manifest_path || data.project_path || '',
            output_dir: data.output_dir || '',
            review_segments: Array.isArray(data.segments) ? data.segments : [],
        };
        const task = await window.reelsCreateTaskFromAutoEditResult(autoEditResult, {
            baseName: data.project_name || undefined,
            skipRecoveryCollection: true,
        });

        // 优先使用 FlowCue Gladia 核对对齐后的全片绝对时间轴逐词数组 (data.words / merged_words)
        // 精确绑定到每个 SRT 句段，确保视频原速或加速导出时，逐词卡拉OK动画与人声 100% 严丝合缝！
        if (task && Array.isArray(task.segments) && task.segments.length > 0) {
            const globalWords = Array.isArray(data.words) ? data.words : [];
            if (globalWords.length > 0) {
                for (const seg of task.segments) {
                    const sStart = Number(seg.start || 0);
                    const sEnd = Number(seg.end || 0);
                    const matched = globalWords.filter(w => {
                        const ws = Number(w.start ?? 0);
                        const we = Number(w.end ?? ws);
                        const mid = (ws + we) * 0.5;
                        return mid >= (sStart - 0.12) && mid <= (sEnd + 0.12);
                    }).map(w => ({
                        word: String(w.word || '').trim(),
                        start: Number(w.start || 0),
                        end: Number(w.end || 0),
                    })).filter(w => w.word);
                    if (matched.length > 0) {
                        seg.words = matched;
                    }
                }
            }
            // 同步更新批量表格归档快照
            if (typeof window.reelsArchiveTaskToActiveBatchTab === 'function') {
                try { window.reelsArchiveTaskToActiveBatchTab(task); } catch (_) {}
            }
        }

        if (typeof _renderBatchTable === 'function') {
            try { _renderBatchTable(); } catch (_) {}
        }
        if (typeof reelsPreviewZoom === 'function') {
            setTimeout(() => reelsPreviewZoom('fit'), 150);
        }
        if (typeof reelsUpdatePreview === 'function') {
            reelsUpdatePreview(true);
        }
        if (!data._silentToast && typeof showToast === 'function') {
            showToast('🎬 已从 FlowCue 导入成片与精确字幕时间轴: ' + (task?.fileName || ''), 'success', 4500);
        }
        return {
            ok: true,
            taskId: task?.id || '',
            fileName: task?.fileName || '',
            segmentCount: Array.isArray(task?.segments) ? task.segments.length : 0,
            totalTasks: window._reelsState?.tasks?.length || 0,
        };
    })();
    `;
    return await win.webContents.executeJavaScript(js, true);
}

function execJsWithTimeout(win, jsCode, timeoutMs = 1500) {
    if (!win || win.isDestroyed()) return Promise.resolve(null);
    return Promise.race([
        win.webContents.executeJavaScript(jsCode, true).catch(() => null),
        new Promise((resolve) => setTimeout(() => resolve(null), timeoutMs)),
    ]);
}

function isMainRendererUrl(url) {
    return !!url && url.includes(`:${VITE_PORT}`) && !url.includes('template=');
}

// 每次页面加载只执行一次完整激活（dom-ready 时），did-finish-load 时仅做轻量确认 + 排空待注入队列
function runFullActivation(win) {
    if (activationPromise && activationLoadSeq === pageLoadSeq) return activationPromise;
    activationLoadSeq = pageLoadSeq;
    const t0 = Date.now();
    const runner = WORKBENCH_MODE === 'visual-review' ? activateVisualReviewInRenderer : activateBatchReelsInRenderer;
    activationPromise = Promise.resolve()
        .then(() => runner(win))
        .catch((e) => console.warn('[FlowCue-Reels] activation failed:', e && e.message))
        .then(() => console.log(`[FlowCue-Reels] 工作台激活完成 (${WORKBENCH_MODE}, 耗时 ${Date.now() - t0}ms, 启动后 ${bootElapsed()})`));
    return activationPromise;
}

async function ensureWorkbenchAfterLoad(win) {
    if (!win || win.isDestroyed()) return;
    const js = WORKBENCH_MODE === 'visual-review'
        ? `(function() {
            try {
                document.body.classList.add('flowcue-embedded');
                const mediaTabBtn = document.querySelector('button.tab[data-tab="media"]');
                if (mediaTabBtn && !mediaTabBtn.classList.contains('active')) mediaTabBtn.click();
                const vrSubBtn = document.querySelector('button.sidebar-item[data-subtab="media-visualreview"]');
                if (vrSubBtn && !vrSubBtn.classList.contains('active')) vrSubBtn.click();
                return true;
            } catch (_) { return false; }
        })();`
        : `(function() {
            try {
                document.body.classList.add('flowcue-embedded');
                const reelsTabBtn = document.querySelector('button.tab[data-tab="batch-reels"]');
                if (reelsTabBtn && !reelsTabBtn.classList.contains('active')) reelsTabBtn.click();
                if (typeof _loadSavedPresets === 'function') {
                    try { _loadSavedPresets(); } catch (_) {}
                }
                setTimeout(() => {
                    if (typeof reelsPreviewZoom === 'function') reelsPreviewZoom('fit');
                }, 250);
                return true;
            } catch (_) { return false; }
        })();`;
    try {
        await win.webContents.executeJavaScript(js, true);
    } catch (e) {
        console.warn('[FlowCue-Reels] ensureWorkbenchAfterLoad failed:', e.message);
    }
}

let _drainingPending = false;
async function drainPendingTasks(win) {
    if (_drainingPending) return;
    _drainingPending = true;
    try {
        while (pendingTasks.length > 0 && pageActivated && win && !win.isDestroyed()) {
            const nextPayload = pendingTasks.shift();
            try {
                if (nextPayload && nextPayload._batchItems) {
                    await injectTaskBatchIntoRenderer(win, nextPayload._batchItems);
                } else if (WORKBENCH_MODE === 'visual-review' && nextPayload?.folder_path) {
                    await injectVisualReviewFolderIntoRenderer(win, nextPayload.folder_path);
                } else {
                    await injectFlowCueTaskIntoRenderer(win, nextPayload);
                }
            } catch (e) {
                console.error('[FlowCue-Reels] Pending task inject failed:', e);
            }
        }
    } finally {
        _drainingPending = false;
    }
}

// 2. 拦截主窗口创建，禁掉自动 DevTools 并在加载后自动进入批量Reels/素材快速审核
app.on('browser-window-created', (_event, win) => {
    const origOpenDevTools = win.webContents.openDevTools.bind(win.webContents);
    let allowManualDevTools = false;
    win.webContents.openDevTools = function (...args) {
        if (allowManualDevTools) {
            return origOpenDevTools(...args);
        }
        return undefined;
    };
    win._openDevToolsManual = () => {
        allowManualDevTools = true;
        origOpenDevTools({ mode: 'detach' });
    };

    try {
        win.setMenuBarVisibility(false);
        win.setAutoHideMenuBar(true);
    } catch (_) {}

    // 如果创建的是主窗口（非隐藏的存储迁移小窗口 / 非模板窗口），立即记录句柄供 PyQt6 嵌入；
    // browser-window-created 在窗口真正 show 之前触发，此时移到屏幕外 + 隐藏任务栏按钮，嵌入前绝不外露浮动
    try {
        const bounds = win.getBounds ? win.getBounds() : { width: 0 };
        const title = String(win.getTitle ? win.getTitle() : '');
        const looksLikeMain = !capturedMainWindow && bounds.width >= 900 && !title.startsWith('模板');
        if (looksLikeMain) {
            capturedMainWindow = win;
            rendererReady = true;
            if (HIDE_UNTIL_EMBED) {
                win._flowcueHiddenUntilEmbed = true;
                try { win.setPosition(OFFSCREEN_POS, OFFSCREEN_POS); } catch (_) {}
                try { win.setSkipTaskbar(true); } catch (_) {}
                win.once('show', () => {
                    if (!win.isDestroyed() && win._flowcueHiddenUntilEmbed) {
                        try { win.setSkipTaskbar(true); } catch (_) {}
                    }
                });
            }
            console.log(`[FlowCue-Reels] 主窗口已创建 hwnd=${getWindowHwndNumber(win)} (启动后 ${bootElapsed()})`);
        }
    } catch (_) {}

    win.webContents.on('did-start-navigation', (_ev, url, isInPlace, isMainFrame) => {
        if (isMainFrame === false || isInPlace) return;
        if (isMainRendererUrl(url)) {
            capturedMainWindow = win;
            rendererReady = true;
            // 新的主框架导航（首次加载 / 重载）：重置激活状态，期间的注入请求进入待注入队列
            pageLoadSeq += 1;
            pageActivated = false;
        }
    });

    win.webContents.on('dom-ready', () => {
        const url = win.webContents.getURL() || '';
        if (isMainRendererUrl(url)) {
            capturedMainWindow = win;
            rendererReady = true;
            runFullActivation(win);
        }
    });

    win.webContents.on('did-finish-load', async () => {
        const url = win.webContents.getURL() || '';
        if (isMainRendererUrl(url)) {
            capturedMainWindow = win;
            rendererReady = true;
            const seqAtLoad = pageLoadSeq;
            await runFullActivation(win);
            await ensureWorkbenchAfterLoad(win);
            if (seqAtLoad !== pageLoadSeq) return;
            pageActivated = true;
            console.log(`[FlowCue-Reels] 页面加载完成，可接收任务 (启动后 ${bootElapsed()})`);
            await drainPendingTasks(win);
        }
    });
});

// 3. 启动控制 HTTP 服务，供 FlowCue (PyQt6) 通信
function readJsonBody(req) {
    return new Promise((resolve) => {
        let body = '';
        req.on('data', (chunk) => { body += chunk; });
        req.on('end', () => {
            if (!body) return resolve({});
            try {
                resolve(JSON.parse(body));
            } catch {
                resolve({});
            }
        });
    });
}

function sendJson(res, status, obj) {
    const payload = JSON.stringify(obj);
    res.writeHead(status, {
        'Content-Type': 'application/json; charset=utf-8',
        'Content-Length': Buffer.byteLength(payload),
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    });
    res.end(payload);
}

const ctrlServer = http.createServer(async (req, res) => {
    try {
        if (req.method === 'OPTIONS') {
            return sendJson(res, 200, { ok: true });
        }

        const parsed = new URL(req.url || '/', `http://127.0.0.1:${CTRL_PORT}`);
        const pathname = parsed.pathname;

        if (req.method === 'GET' && pathname === '/status') {
            const hwnd = getWindowHwndNumber(capturedMainWindow);
            let stateInfo = {};
            if (rendererReady && capturedMainWindow && !capturedMainWindow.isDestroyed()) {
                try {
                    const resState = await execJsWithTimeout(
                        capturedMainWindow,
                        `({
                            taskCount: window._reelsState?.tasks?.length || 0,
                            selectedIdx: window._reelsState?.selectedIdx ?? -1,
                            isExporting: !!window._reelsState?.isExporting,
                            limitUnder3Min: !!(typeof window.flowcueGetLimitUnder3Min === 'function' ? window.flowcueGetLimitUnder3Min() : (localStorage.getItem('flowcue_reels_limit_under_3min') !== '0'))
                        })`,
                        400
                    );
                    if (resState && typeof resState === 'object') {
                        stateInfo = resState;
                    }
                } catch (_) {}
            }
            return sendJson(res, 200, {
                ok: true,
                ready: rendererReady && hwnd > 0,
                hwnd,
                vitePort: VITE_PORT,
                ctrlPort: CTRL_PORT,
                workbenchMode: WORKBENCH_MODE,
                presetPrimaryPath: PRESET_FILE_PRIMARY,
                presetBackupPath: PRESET_FILE_BACKUP,
                ...stateInfo,
            });
        }

        if (req.method === 'POST' && pathname === '/set-limit-under-3min') {
            const body = await readJsonBody(req);
            const checked = !!body?.checked;
            if (capturedMainWindow && !capturedMainWindow.isDestroyed()) {
                await capturedMainWindow.webContents.executeJavaScript(
                    `(() => {
                        if (typeof window.flowcueSetLimitUnder3Min === 'function') {
                            return window.flowcueSetLimitUnder3Min(${checked ? 'true' : 'false'});
                        }
                        localStorage.setItem('flowcue_reels_limit_under_3min', ${checked ? "'1'" : "'0'"});
                        return ${checked ? 'true' : 'false'};
                    })()`,
                    true
                );
            }
            return sendJson(res, 200, { ok: true, limitUnder3Min: checked });
        }

        if (req.method === 'POST' && pathname === '/load-visual-review-folder') {
            const body = await readJsonBody(req);
            const folderPath = body?.folder_path || body?.folderPath || '';
            if (!folderPath) {
                return sendJson(res, 400, { ok: false, error: '缺少 folder_path' });
            }
            if (!rendererReady || !capturedMainWindow || capturedMainWindow.isDestroyed()) {
                pendingTasks.push({ folder_path: folderPath });
                return sendJson(res, 200, { ok: true, queued: true, folderPath });
            }
            const result = await injectVisualReviewFolderIntoRenderer(capturedMainWindow, folderPath);
            return sendJson(res, 200, result);
        }

        if (req.method === 'POST' && pathname === '/visual-review-delete-file') {
            const body = await readJsonBody(req);
            const rawPath = String(body?.filePath || body?.file_path || '').trim();
            if (!rawPath) {
                return sendJson(res, 400, { ok: false, error: '缺少文件路径 filePath' });
            }
            const targetPath = path.resolve(rawPath);
            if (!fs.existsSync(targetPath)) {
                return sendJson(res, 200, { ok: true, alreadyGone: true, deletedPath: targetPath });
            }
            let lastErr = null;
            let deleted = false;
            for (let attempt = 0; attempt < 5; attempt++) {
                try {
                    fs.unlinkSync(targetPath);
                    deleted = true;
                    break;
                } catch (err) {
                    lastErr = err;
                    await new Promise((r) => setTimeout(r, 120));
                }
            }
            if (!deleted && electron.shell && typeof electron.shell.trashItem === 'function') {
                try {
                    await electron.shell.trashItem(targetPath);
                    deleted = true;
                } catch (err) {
                    lastErr = err;
                }
            }
            if (!deleted) {
                return sendJson(res, 500, {
                    ok: false,
                    error: `删除文件失败: ${lastErr ? (lastErr.message || String(lastErr)) : '未知错误'}`,
                });
            }
            return sendJson(res, 200, { ok: true, deletedPath: targetPath });
        }

        if (req.method === 'POST' && pathname === '/visual-review-defer-file') {
            const body = await readJsonBody(req);
            const rawPath = String(body?.filePath || body?.file_path || '').trim();
            if (!rawPath) {
                return sendJson(res, 400, { ok: false, error: '缺少文件路径 filePath' });
            }
            const targetPath = path.resolve(rawPath);
            if (!fs.existsSync(targetPath)) {
                return sendJson(res, 404, { ok: false, error: `文件不存在: ${targetPath}` });
            }
            const parentDir = path.dirname(targetPath);
            const deferDir = path.join(parentDir, '暂缓');
            fs.mkdirSync(deferDir, { recursive: true });

            const ext = path.extname(targetPath);
            const baseStem = path.basename(targetPath, ext);
            let destPath = path.join(deferDir, path.basename(targetPath));
            let suffix = 1;
            while (fs.existsSync(destPath) && path.resolve(destPath) !== targetPath) {
                destPath = path.join(deferDir, `${baseStem}_${suffix}${ext}`);
                suffix += 1;
            }

            let moved = false;
            let lastErr = null;
            for (let attempt = 0; attempt < 5; attempt++) {
                try {
                    fs.renameSync(targetPath, destPath);
                    moved = true;
                    break;
                } catch (err) {
                    lastErr = err;
                    await new Promise((r) => setTimeout(r, 120));
                }
            }
            if (!moved) {
                try {
                    fs.copyFileSync(targetPath, destPath);
                    fs.unlinkSync(targetPath);
                    moved = true;
                } catch (err) {
                    lastErr = err;
                }
            }
            if (!moved) {
                return sendJson(res, 500, {
                    ok: false,
                    error: `移动到暂缓文件夹失败: ${lastErr ? (lastErr.message || String(lastErr)) : '未知错误'}`,
                });
            }
            return sendJson(res, 200, { ok: true, srcPath: targetPath, destPath, deferDir });
        }

        if (req.method === 'POST' && pathname === '/save-export-titles-presets') {
            const body = await readJsonBody(req);
            const content = String(body?.content ?? '');
            const defaultName = String(body?.defaultName || '批量Reels_标题与覆层预设导出.tsv');
            if (!electron.dialog || typeof electron.dialog.showSaveDialog !== 'function') {
                return sendJson(res, 500, { ok: false, error: '当前环境不支持保存对话框' });
            }
            const dialogOpts = {
                title: '导出批量Reels标题与覆层预设名称',
                defaultPath: defaultName,
                filters: [
                    { name: '制表符分隔表格 (*.tsv)', extensions: ['tsv'] },
                    { name: '文本文件 (*.txt)', extensions: ['txt'] },
                    { name: 'CSV 表格 (*.csv)', extensions: ['csv'] },
                ],
            };
            const saveRes = (capturedMainWindow && !capturedMainWindow.isDestroyed())
                ? await electron.dialog.showSaveDialog(capturedMainWindow, dialogOpts)
                : await electron.dialog.showSaveDialog(dialogOpts);
            if (saveRes.canceled || !saveRes.filePath) {
                return sendJson(res, 200, { ok: false, canceled: true });
            }
            let outText = content;
            if (saveRes.filePath.toLowerCase().endsWith('.csv') && !outText.startsWith('\uFEFF')) {
                outText = '\uFEFF' + outText;
            }
            fs.writeFileSync(saveRes.filePath, outText, 'utf8');
            return sendJson(res, 200, { ok: true, filePath: saveRes.filePath });
        }

        if (req.method === 'POST' && pathname === '/focus-hwnd') {
            notifyPythonFocusHwnd();
            return sendJson(res, 200, { ok: true });
        }

        if (req.method === 'POST' && pathname === '/backup-presets') {
            const body = await readJsonBody(req);
            const entries = body && typeof body.entries === 'object' ? body.entries : {};
            syncAndBackupPresetFiles(entries);
            return sendJson(res, 200, { ok: true, primary: PRESET_FILE_PRIMARY, backup: PRESET_FILE_BACKUP });
        }

        if (req.method === 'POST' && pathname === '/focus-reels') {
            if (capturedMainWindow && !capturedMainWindow.isDestroyed()) {
                await activateBatchReelsInRenderer(capturedMainWindow);
                notifyPythonFocusHwnd();
            }
            return sendJson(res, 200, { ok: true });
        }

        if (req.method === 'POST' && pathname === '/toggle-header') {
            if (capturedMainWindow && !capturedMainWindow.isDestroyed()) {
                const embedded = await capturedMainWindow.webContents.executeJavaScript(
                    `(() => {
                        document.body.classList.toggle('flowcue-embedded');
                        if (typeof reelsPreviewZoom === 'function') setTimeout(() => reelsPreviewZoom('fit'), 100);
                        return document.body.classList.contains('flowcue-embedded');
                    })()`,
                    true
                );
                return sendJson(res, 200, { ok: true, embedded });
            }
            return sendJson(res, 200, { ok: false });
        }

        if (req.method === 'POST' && pathname === '/fit-preview') {
            if (capturedMainWindow && !capturedMainWindow.isDestroyed()) {
                await capturedMainWindow.webContents.executeJavaScript(
                    `(() => { if (typeof reelsPreviewZoom === 'function') reelsPreviewZoom('fit'); return true; })()`,
                    true
                );
            }
            return sendJson(res, 200, { ok: true });
        }

        if (req.method === 'POST' && pathname === '/open-export-titles-presets') {
            if (capturedMainWindow && !capturedMainWindow.isDestroyed()) {
                await capturedMainWindow.webContents.executeJavaScript(
                    `(() => {
                        if (typeof window.flowcueOpenExportTitlesAndPresetsModal === 'function') {
                            window.flowcueOpenExportTitlesAndPresetsModal();
                            return true;
                        }
                        return false;
                    })()`,
                    true
                );
            }
            return sendJson(res, 200, { ok: true });
        }

        if (req.method === 'POST' && pathname === '/devtools') {
            if (capturedMainWindow && !capturedMainWindow.isDestroyed() && capturedMainWindow._openDevToolsManual) {
                capturedMainWindow._openDevToolsManual();
            }
            return sendJson(res, 200, { ok: true });
        }

        if (req.method === 'POST' && pathname === '/sync-keys') {
            const body = await readJsonBody(req);
            if (capturedMainWindow && !capturedMainWindow.isDestroyed()) {
                const payloadStr = JSON.stringify(body || {});
                await capturedMainWindow.webContents.executeJavaScript(
                    `(async () => {
                        const keys = ${payloadStr};
                        if (window.electronAPI && window.electronAPI.apiCall) {
                            await window.electronAPI.apiCall('settings/save', keys);
                        }
                        return true;
                    })()`,
                    true
                );
            }
            return sendJson(res, 200, { ok: true });
        }

        if (req.method === 'POST' && pathname === '/load-task') {
            const body = await readJsonBody(req);
            if (!rendererReady || !capturedMainWindow || capturedMainWindow.isDestroyed()) {
                pendingTasks.push(body);
                return sendJson(res, 200, { ok: true, queued: true });
            }
            const result = await injectFlowCueTaskIntoRenderer(capturedMainWindow, body);
            return sendJson(res, 200, result);
        }

        if (req.method === 'POST' && pathname === '/load-tasks-batch') {
            const body = await readJsonBody(req);
            const items = Array.isArray(body?.tasks) ? body.tasks : [];
            if (!rendererReady || !capturedMainWindow || capturedMainWindow.isDestroyed()) {
                items.forEach(item => pendingTasks.push(item));
                return sendJson(res, 200, { ok: true, queued: true, count: items.length });
            }
            const results = [];
            for (let i = 0; i < items.length; i++) {
                const itemPayload = { ...items[i], _silentToast: i < items.length - 1 };
                const r = await injectFlowCueTaskIntoRenderer(capturedMainWindow, itemPayload);
                results.push(r);
            }
            if (items.length > 1) {
                await capturedMainWindow.webContents.executeJavaScript(
                    `(() => {
                        if (typeof showToast === 'function') {
                            showToast('🎉 已批量将 ' + ${items.length} + ' 个合并成片送入 批量Reels！', 'success', 5000);
                        }
                    })()`,
                    true
                );
            }
            return sendJson(res, 200, {
                ok: true,
                count: results.length,
                totalTasks: results.length > 0 ? results[results.length - 1].totalTasks : 0,
                results,
            });
        }

        return sendJson(res, 404, { ok: false, error: 'Unknown endpoint' });
    } catch (err) {
        return sendJson(res, 500, { ok: false, error: String(err.message || err) });
    }
});

ctrlServer.listen(CTRL_PORT, '127.0.0.1', () => {
    console.log(`[FlowCue-Reels] Control server listening on http://127.0.0.1:${CTRL_PORT}`);
});

// 4. 加载 VideoKit 原生 Electron 主进程（包含全部 80+ IPC 与 FFmpeg/WebCodecs 管线）
require(path.join(VIDEOKIT_ROOT, 'electron', 'main.js'));
