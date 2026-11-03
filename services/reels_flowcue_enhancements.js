/**
 * reels_flowcue_enhancements.js
 * FlowCue 专享增强补丁（在批量Reels渲染进程加载后注入，不破坏 VideoKit 原始源码）：
 *
 * 1. 嵌入式窗口键盘焦点同步与剪贴板增强（解决嵌入 PyQt 后点击输入框有竖杠但无法打字/粘贴的问题）
 * 2. 所有参数滑块自动配备可编辑数字输入框 + 鼠标点击聚焦（出现竖杠 |）后滑动滚轮上下微调数值
 * 3. 导出「⏱️ 自动调速/视频时长不超过3分钟（≤2分58秒）」增强：
 *    - 未超过 2分58秒（178.0s）原速导出；
 *    - 超过 2分58秒（178.0s）自动加速至 ≤2分58秒（177.5s），且视频、音频、核对的 SRT 字幕与逐词卡拉OK时间轴 100% 同步跳动，绝不串行
 * 4. 批量表格（Batch Table）支持直接选择每个任务的「字幕预设」与「覆层预设」，并支持通过复制/粘贴预设名称（Ctrl+C / Ctrl+V / 📋粘贴列）一键批量设置
 * 5. 字幕预设与覆层预设实时双保险自动备份（永不因更新软件丢失）
 */
(function () {
    if (window.__FLOWCUE_ENHANCEMENTS_LOADED__) return;
    window.__FLOWCUE_ENHANCEMENTS_LOADED__ = true;

    const CTRL_PORT = window.__FLOWCUE_CTRL_PORT__ || 0;

    // ═══════════════════════════════════════════════════════════════════════
    // 1. 嵌入式窗口 Win32 键盘焦点激活 + 输入框复制/粘贴/快捷键/右键菜单增强
    // ═══════════════════════════════════════════════════════════════════════
    let _lastFocusReqTime = 0;
    function requestNativeHwndFocus(force = false) {
        const now = Date.now();
        if (!force && now - _lastFocusReqTime < 120) return;
        _lastFocusReqTime = now;
        if (CTRL_PORT > 0) {
            fetch(`http://127.0.0.1:${CTRL_PORT}/focus-hwnd`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: '{}',
            }).catch(() => {});
        }
    }

    function isEditableElement(el) {
        if (!el || el === document.body || el === document.documentElement) return false;
        const tag = (el.tagName || '').toUpperCase();
        if (tag === 'INPUT') {
            const type = (el.type || 'text').toLowerCase();
            return !['button', 'checkbox', 'radio', 'submit', 'reset', 'file', 'image', 'hidden'].includes(type);
        }
        if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
        if (el.isContentEditable) return true;
        return false;
    }

    // 注入全局样式：彻底取消数字输入框的左右拉拽光标 (ew-resize)，统一为文本输入光标 (text)；
    // 并让批量表格列头的 📋粘贴 / 清空 按钮常驻高亮可见
    function injectEnhancementStyles() {
        if (document.getElementById('flowcue-enhancements-style')) return;
        const style = document.createElement('style');
        style.id = 'flowcue-enhancements-style';
        style.textContent = `
            input[type="number"],
            input.rop-input[type="number"],
            input.rop-num-readout,
            input.num-input,
            input.rbt-num-input,
            #reels-cv-x-val,
            #reels-cv-y-val,
            #reels-cv-scale-val {
                cursor: text !important;
            }
            #rbt-table thead th .rbt-th-paste,
            #rbt-table thead th .rbt-th-clear,
            #rbt-table thead th .flowcue-col-preset-paste,
            #rbt-table thead th .flowcue-col-preset-clear {
                opacity: 1 !important;
                pointer-events: auto !important;
            }
            .flowcue-under3min-banner {
                display: inline-flex;
                align-items: center;
                gap: 6px;
                padding: 3px 10px;
                border-radius: 6px;
                background: linear-gradient(135deg, rgba(16, 185, 129, 0.22), rgba(59, 130, 246, 0.22));
                border: 1px solid rgba(16, 185, 129, 0.55);
                color: #ecfdf5;
                font-size: 12px;
                font-weight: 700;
                cursor: pointer;
                user-select: none;
                white-space: nowrap;
            }
            .flowcue-under3min-banner:hover {
                border-color: #34d399;
                background: linear-gradient(135deg, rgba(16, 185, 129, 0.32), rgba(59, 130, 246, 0.32));
            }
        `;
        (document.head || document.documentElement).appendChild(style);
    }
    injectEnhancementStyles();

    // 禁用原版字幕数字输入框的左右拖拽初始化函数
    window._initAllSubtitleNumberInputsDrag = function () {};

    // 当鼠标在 Reels 窗口按下或聚焦输入框时，立即通知主进程与 Win32 抢回键盘焦点；
    // 同时对于所有数字参数输入框，拦截原版的 pointerdown/mousedown 左右拉拽 (ew-resize) 处理器，
    // 改为单击直接聚焦（出现竖杠 |），之后直接滚动鼠标滚轮即可上下调节！
    window.addEventListener('pointerdown', (e) => {
        const target = e.target;
        const editable = isEditableElement(target) || !!(target && target.closest && target.closest('input, textarea, select, [contenteditable="true"], .rbt-table'));
        requestNativeHwndFocus(editable);

        if (target && isNumericParameterInput(target)) {
            target.style.cursor = 'text';
            if (document.body) document.body.style.cursor = '';
            // 阻止触发元素自身的 pointerdown 左右拖拽监听器（如 ReelsOverlayPanel 中的 scrub drag）
            e.stopPropagation();
            if (document.activeElement !== target) {
                try { target.focus(); } catch (_) {}
            }
            return;
        }

        if (editable && target && typeof target.focus === 'function') {
            setTimeout(() => {
                try { target.focus(); } catch (_) {}
            }, 0);
        }
    }, true);

    window.addEventListener('mousedown', (e) => {
        if (_ctxMenuEl && !_ctxMenuEl.contains(e.target)) {
            hideInputContextMenu();
        }
        const target = e.target;
        if (target && isNumericParameterInput(target)) {
            target.style.cursor = 'text';
            if (document.body) document.body.style.cursor = '';
            // 阻止触发元素自身的 mousedown 左右拖拽监听器（如 batch-reels.js 中的字幕/水印/内容视频 scrub drag）
            e.stopPropagation();
            if (document.activeElement !== target) {
                try { target.focus(); } catch (_) {}
            }
        }
    }, true);

    window.addEventListener('focusin', (e) => {
        if (isEditableElement(e.target)) {
            requestNativeHwndFocus(true);
            if (isNumericParameterInput(e.target)) {
                e.target.style.cursor = 'text';
            }
        }
    }, true);

    // 辅助函数：向 <input> 或 <textarea> 光标处插入/替换文本并触发 input/change 事件
    function insertTextIntoInput(el, text) {
        if (!el || el.readOnly || el.disabled) return false;
        const str = String(text ?? '');
        const tag = (el.tagName || '').toUpperCase();
        if (tag === 'INPUT' || tag === 'TEXTAREA') {
            const type = (el.type || 'text').toLowerCase();
            if (type === 'number') {
                const cleaned = str.trim().replace(/[^\d.\-+]/g, '');
                if (cleaned !== '') {
                    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype,
                        'value'
                    )?.set;
                    if (nativeInputValueSetter) nativeInputValueSetter.call(el, cleaned);
                    else el.value = cleaned;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    return true;
                }
                return false;
            }
            let start = 0;
            let end = (el.value || '').length;
            try {
                if (typeof el.selectionStart === 'number') start = el.selectionStart;
                if (typeof el.selectionEnd === 'number') end = el.selectionEnd;
            } catch (_) {}
            const val = el.value || '';
            const nextVal = val.slice(0, start) + str + val.slice(end);
            const proto = tag === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
            if (setter) setter.call(el, nextVal);
            else el.value = nextVal;
            try {
                const caret = start + str.length;
                el.setSelectionRange(caret, caret);
            } catch (_) {}
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
        } else if (el.isContentEditable) {
            document.execCommand('insertText', false, str);
            el.dispatchEvent(new Event('input', { bubbles: true }));
            return true;
        }
        return false;
    }

    function readClipboardTextSyncOrAsync() {
        try {
            if (window.require) {
                const { clipboard } = window.require('electron');
                if (clipboard && typeof clipboard.readText === 'function') {
                    return Promise.resolve(clipboard.readText() || '');
                }
            }
        } catch (_) {}
        if (navigator.clipboard && typeof navigator.clipboard.readText === 'function') {
            return navigator.clipboard.readText().catch(() => '');
        }
        return Promise.resolve('');
    }

    function writeClipboardTextSyncOrAsync(text) {
        const str = String(text ?? '');
        try {
            if (window.require) {
                const { clipboard } = window.require('electron');
                if (clipboard && typeof clipboard.writeText === 'function') {
                    clipboard.writeText(str);
                    return Promise.resolve(true);
                }
            }
        } catch (_) {}
        if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
            return navigator.clipboard.writeText(str).then(() => true).catch(() => false);
        }
        return Promise.resolve(false);
    }

    // 右键快捷菜单（支持在任何输入框或表格单元格上一键 粘贴 / 复制 / 剪切 / 全选）
    let _ctxMenuEl = null;
    function hideInputContextMenu() {
        if (_ctxMenuEl && _ctxMenuEl.parentNode) {
            _ctxMenuEl.parentNode.removeChild(_ctxMenuEl);
        }
        _ctxMenuEl = null;
    }

    window.addEventListener('contextmenu', (e) => {
        const target = e.target;
        if (!target) return;
        const inputEl = isEditableElement(target) ? target : (target.closest && target.closest('input, textarea, [contenteditable="true"]'));
        if (!inputEl) return;

        e.preventDefault();
        hideInputContextMenu();
        requestNativeHwndFocus(true);
        try { inputEl.focus(); } catch (_) {}

        const menu = document.createElement('div');
        menu.style.cssText = 'position:fixed;z-index:9999999;background:#1e1e2e;border:1px solid rgba(255,255,255,0.18);border-radius:6px;padding:4px 0;box-shadow:0 6px 20px rgba(0,0,0,0.55);min-width:130px;font-size:12px;color:#eee;user-select:none;';
        menu.style.left = Math.min(window.innerWidth - 150, e.clientX) + 'px';
        menu.style.top = Math.min(window.innerHeight - 140, e.clientY) + 'px';

        const items = [
            {
                label: '📋 粘贴 (Ctrl+V)',
                action: async () => {
                    const txt = await readClipboardTextSyncOrAsync();
                    if (txt !== '') {
                        if (inputEl.classList && inputEl.classList.contains('flowcue-tpl-name-input')) {
                            handleBatchPresetPasteOnInput(inputEl, txt);
                        } else {
                            insertTextIntoInput(inputEl, txt);
                        }
                    }
                }
            },
            {
                label: '📄 复制 (Ctrl+C)',
                action: async () => {
                    let sel = '';
                    try {
                        if (typeof inputEl.selectionStart === 'number' && inputEl.selectionStart !== inputEl.selectionEnd) {
                            sel = (inputEl.value || '').slice(inputEl.selectionStart, inputEl.selectionEnd);
                        }
                    } catch (_) {}
                    if (!sel) sel = inputEl.value || inputEl.textContent || '';
                    await writeClipboardTextSyncOrAsync(sel);
                }
            },
            {
                label: '✂️ 剪切 (Ctrl+X)',
                action: async () => {
                    let sel = '';
                    try {
                        if (typeof inputEl.selectionStart === 'number' && inputEl.selectionStart !== inputEl.selectionEnd) {
                            sel = (inputEl.value || '').slice(inputEl.selectionStart, inputEl.selectionEnd);
                            await writeClipboardTextSyncOrAsync(sel);
                            insertTextIntoInput(inputEl, '');
                            return;
                        }
                    } catch (_) {}
                    sel = inputEl.value || '';
                    await writeClipboardTextSyncOrAsync(sel);
                    inputEl.value = '';
                    inputEl.dispatchEvent(new Event('input', { bubbles: true }));
                    inputEl.dispatchEvent(new Event('change', { bubbles: true }));
                }
            },
            {
                label: '🔲 全选 (Ctrl+A)',
                action: () => {
                    try { inputEl.select(); } catch (_) {}
                }
            },
        ];

        items.forEach(item => {
            const row = document.createElement('div');
            row.textContent = item.label;
            row.style.cssText = 'padding:6px 12px;cursor:pointer;transition:background 0.12s;';
            row.addEventListener('mouseenter', () => { row.style.background = 'rgba(99,102,241,0.35)'; });
            row.addEventListener('mouseleave', () => { row.style.background = 'transparent'; });
            row.addEventListener('mousedown', (ev) => {
                ev.preventDefault();
                ev.stopPropagation();
                hideInputContextMenu();
                item.action();
            });
            menu.appendChild(row);
        });

        document.body.appendChild(menu);
        _ctxMenuEl = menu;
    }, true);

    // ═══════════════════════════════════════════════════════════════════════
    // 2. 所有参数均提供可输入数字框 + 点击聚焦显示竖杠(|)后滑动鼠标滚轮上下微调
    //    （进度条 input[type="range"] 本身禁用滚轮，只能鼠标拉拽；数字框点击后可滚轮调整）
    // ═══════════════════════════════════════════════════════════════════════
    function findPairedRangeForNumberInput(numInput) {
        if (!numInput) return null;
        if (numInput._pairedRange && numInput._pairedRange.isConnected) return numInput._pairedRange;
        const id = numInput.id || '';
        const dataLink = numInput.getAttribute('data-link');
        if (dataLink) {
            const linked = document.getElementById(dataLink);
            if (linked && linked.type === 'range') return linked;
        }
        if (id) {
            // 情况 A: <input type="range" data-link="xxx">
            const byDataLink = document.querySelector(`input[type="range"][data-link="${CSS.escape(id)}"]`);
            if (byDataLink) return byDataLink;
            // 情况 B: xxx-num <-> xxx-range
            if (id.endsWith('-num')) {
                const rangeId = id.slice(0, -4) + '-range';
                const byRangeId = document.getElementById(rangeId);
                if (byRangeId && byRangeId.type === 'range') return byRangeId;
            }
            // 情况 B2: xxx-val <-> xxx (如覆层面板 #rop-opacity-val <-> #rop-opacity, #rop-scale-val <-> #rop-scale)
            if (id.endsWith('-val')) {
                const baseId = id.slice(0, -4);
                const byBaseId = document.getElementById(baseId);
                if (byBaseId && byBaseId.type === 'range') return byBaseId;
            }
            if (id.endsWith('-val-num')) {
                const baseId = id.slice(0, -8);
                const byBaseId = document.getElementById(baseId);
                if (byBaseId && byBaseId.type === 'range') return byBaseId;
            }
        }
        // 情况 C: 同级容器内的 input[type="range"]
        const parent = numInput.parentElement;
        if (parent) {
            const sibRange = parent.querySelector('input[type="range"]');
            if (sibRange) return sibRange;
        }
        return null;
    }

    function ensureAllRangeSlidersHaveNumberInput(root = document) {
        if (!root || !root.querySelectorAll) return;
        const ranges = root.querySelectorAll('input[type="range"]');
        ranges.forEach((range) => {
            if (range.dataset.flowcuePaired === '1') return;
            const id = range.id || '';
            const dataLink = range.getAttribute('data-link');
            if (dataLink && document.getElementById(dataLink)) {
                range.dataset.flowcuePaired = '1';
                return;
            }
            if (id.endsWith('-range')) {
                const numId = id.slice(0, -6) + '-num';
                if (document.getElementById(numId)) {
                    range.dataset.flowcuePaired = '1';
                    return;
                }
            }
            if (id) {
                const existingValInput = document.getElementById(id + '-val');
                if (existingValInput && existingValInput.tagName === 'INPUT') {
                    existingValInput._pairedRange = range;
                    range._pairedNum = existingValInput;
                    range.dataset.flowcuePaired = '1';
                    return;
                }
            }
            const parent = range.parentElement;
            if (!parent) return;
            const existingNum = parent.querySelector('input[type="number"]');
            if (existingNum) {
                existingNum._pairedRange = range;
                range._pairedNum = existingNum;
                range.dataset.flowcuePaired = '1';
                return;
            }

            // 查找是否带有只读 <span id="...-val"> 或 .rbt-voicevol-label
            let valSpan = null;
            if (id) {
                valSpan = document.getElementById(id + '-val') || parent.querySelector(`#${CSS.escape(id)}-val`);
            }
            if (!valSpan) {
                valSpan = parent.querySelector('.rbt-voicevol-label, span[id$="-val"]');
            }

            const numInput = document.createElement('input');
            numInput.type = 'number';
            numInput.className = 'num-input flowcue-auto-num-input';
            if (id) numInput.id = id + '-val-num';
            if (range.min !== '') numInput.min = range.min;
            if (range.max !== '') numInput.max = range.max;
            numInput.step = range.step && range.step !== 'any' ? range.step : '1';
            numInput.value = range.value;
            numInput.title = '鼠标单击确认聚焦后，直接滚动鼠标滚轮即可上下调节数值（也可直接输入数字）';
            numInput.style.cssText = 'width:54px;height:22px;padding:1px 4px;font-size:11px;background:rgba(0,0,0,0.35);color:#fff;border:1px solid rgba(255,255,255,0.18);border-radius:4px;text-align:center;box-sizing:border-box;cursor:text !important;';

            numInput._pairedRange = range;
            range._pairedNum = numInput;
            range.dataset.flowcuePaired = '1';

            if (valSpan) {
                valSpan.style.display = 'none';
                valSpan.insertAdjacentElement('afterend', numInput);
            } else {
                range.insertAdjacentElement('afterend', numInput);
            }

            // 双向同步
            range.addEventListener('input', () => {
                if (document.activeElement !== numInput) {
                    numInput.value = range.value;
                }
            });
            range.addEventListener('change', () => {
                if (document.activeElement !== numInput) {
                    numInput.value = range.value;
                }
            });

            const syncFromNum = (evtType) => {
                let v = parseFloat(numInput.value);
                if (Number.isNaN(v)) return;
                const minV = parseFloat(range.min);
                const maxV = parseFloat(range.max);
                if (!Number.isNaN(minV) && v < minV) v = minV;
                if (!Number.isNaN(maxV) && v > maxV) {
                    // 允许滑块扩展上限，避免手动输入超范围被强行截断
                    range.max = String(v);
                }
                range.value = String(v);
                if (valSpan) valSpan.textContent = String(v);
                range.dispatchEvent(new Event(evtType, { bubbles: true }));
            };
            numInput.addEventListener('input', () => syncFromNum('input'));
            numInput.addEventListener('change', () => syncFromNum('change'));
        });

        // 为所有数字输入框设置 text 光标和提示，移除原版 ew-resize 左右拉拽光标
        const numInputs = root.querySelectorAll('input[type="number"], input.rop-num-readout, #reels-cv-x-val, #reels-cv-y-val, #reels-cv-scale-val');
        numInputs.forEach((inp) => {
            inp.style.cursor = 'text';
            inp.title = '鼠标单击确认聚焦后，直接滚动鼠标滚轮即可上下调节数值（也可直接输入数字）';
        });
    }

    function isNumericParameterInput(el) {
        if (!el || (el.tagName || '').toUpperCase() !== 'INPUT') return false;
        if (el.readOnly || el.disabled) return false;
        const type = (el.type || 'text').toLowerCase();
        if (type === 'number') return true;
        if (el.classList.contains('rop-num-readout')) return true;
        if (el.id === 'reels-cv-x-val' || el.id === 'reels-cv-y-val' || el.id === 'reels-cv-scale-val') return true;
        if (type === 'text') {
            if (el.classList.contains('num-input') || el.classList.contains('rbt-num-input')) return true;
            if (findPairedRangeForNumberInput(el)) return true;
            const v = (el.value || '').trim();
            if (v !== '' && /^-?\d+(\.\d+)?$/.test(v) && (el.id.includes('trim') || el.id.includes('scale') || el.id.includes('dur') || el.id.includes('pos') || el.id.includes('crop') || el.id.includes('size'))) {
                return true;
            }
        }
        return false;
    }

    // 核心功能：
    // 1. 进度条 (input[type="range"]) 禁用鼠标滚轮调整（只能通过鼠标拉拽进度条）；
    // 2. 数字框（含进度条后面的数字框、字幕/覆层/内容视频数字框）在鼠标单击确认聚焦后，滚动鼠标滚轮直接上下调整数值！
    window.addEventListener('wheel', (e) => {
        const target = e.target;
        // 规则 1：如果鼠标在进度条 (input[type="range"]) 上滚动，或者当前焦点在进度条上，严禁滚轮改变进度条数值
        if (target && ((target.tagName === 'INPUT' && target.type === 'range') || (target.closest && target.closest('input[type="range"]')))) {
            if (document.activeElement && document.activeElement.type === 'range') {
                try { document.activeElement.blur(); } catch (_) {}
            }
            e.preventDefault();
            e.stopPropagation();
            return;
        }
        const active = document.activeElement;
        if (active && active.tagName === 'INPUT' && active.type === 'range') {
            try { active.blur(); } catch (_) {}
            return;
        }

        // 规则 2：当数字输入框处于点击确认聚焦状态时，滚轮直接上下调节数字
        if (!active || !isNumericParameterInput(active)) return;
        e.preventDefault();
        e.stopPropagation();

        const pairedRange = findPairedRangeForNumberInput(active);
        let rawStep = parseFloat(active.step);
        if (Number.isNaN(rawStep) || rawStep <= 0) {
            rawStep = pairedRange ? parseFloat(pairedRange.step) : NaN;
        }
        if (Number.isNaN(rawStep) || rawStep <= 0) {
            if (active.id === 'reels-cv-x-val' || active.id === 'reels-cv-y-val') {
                const stepSel = document.getElementById('reels-cv-step');
                rawStep = parseFloat(stepSel?.value || '10') || 10;
            } else {
                const curStr = String(active.value || '');
                rawStep = curStr.includes('.') ? 0.1 : 1;
            }
        }

        // Shift 键 10 倍速调节，Alt 键 0.1 倍精细调节
        let step = rawStep;
        if (e.shiftKey) step = rawStep * 10;
        else if (e.altKey) step = rawStep * 0.1;

        const dir = e.deltaY < 0 ? 1 : -1;
        const rawStr = String(active.value || '').trim();
        const currentVal = (rawStr === 'center' || rawStr === '') ? 0 : parseFloat(rawStr);
        const baseVal = Number.isFinite(currentVal) ? currentVal : (parseFloat(active.min) || 0);
        let nextVal = baseVal + dir * step;

        let minVal = parseFloat(active.min);
        if (Number.isNaN(minVal) && pairedRange) minVal = parseFloat(pairedRange.min);
        let maxVal = parseFloat(active.max);
        if (Number.isNaN(maxVal) && pairedRange) maxVal = parseFloat(pairedRange.max);

        if (Number.isFinite(minVal) && nextVal < minVal) nextVal = minVal;
        if (Number.isFinite(maxVal) && nextVal > maxVal) nextVal = maxVal;

        // 保留合理小数位，消除浮点尾数误差
        const stepStr = String(step);
        const decimals = stepStr.includes('.') ? Math.min(4, stepStr.split('.')[1].length) : 0;
        const formatted = decimals > 0 ? Number(nextVal.toFixed(decimals)) : Math.round(nextVal);

        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
        if (setter) setter.call(active, String(formatted));
        else active.value = String(formatted);

        if (pairedRange) {
            pairedRange.value = String(formatted);
            pairedRange.dispatchEvent(new Event('input', { bubbles: true }));
            pairedRange.dispatchEvent(new Event('change', { bubbles: true }));
        }
        active.dispatchEvent(new Event('input', { bubbles: true }));
        active.dispatchEvent(new Event('change', { bubbles: true }));
    }, { passive: false, capture: true });

    // ═══════════════════════════════════════════════════════════════════════
    // 3. 导出「自动调速/视频时长不超过3分钟（≤2分58秒）」且核对的 SRT 字幕 100% 同步跳动
    //    并在「🚀 导出设置」标题栏、批量表格底部栏等显眼位置放置同步开关！
    // ═══════════════════════════════════════════════════════════════════════
    const FLOWCUE_TRIGGER_SECONDS = 178.0; // 2分58秒：不超过 2分58秒 则原始速度导出；超过 2分58秒 自动加速
    const FLOWCUE_TARGET_SECONDS  = 177.5; // 保证加速后视频时长低于且接近 2分58秒（177.5s <= 178.0s）

    function syncAllUnder3MinCheckboxes(checkedVal) {
        const mainCb = document.getElementById('reels-limit-under-3min');
        if (mainCb && mainCb.checked !== checkedVal) {
            mainCb.checked = checkedVal;
            mainCb.dispatchEvent(new Event('change', { bubbles: true }));
        }
        document.querySelectorAll('.flowcue-under3min-sync-cb').forEach((el) => {
            if (el.checked !== checkedVal) el.checked = checkedVal;
        });
        try {
            localStorage.setItem('flowcue_limit_under_3min', checkedVal ? '1' : '0');
        } catch (_) {}
    }

    window.flowcueSetLimitUnder3Min = function (checked) {
        syncAllUnder3MinCheckboxes(!!checked);
        return !!document.getElementById('reels-limit-under-3min')?.checked;
    };

    window.flowcueGetLimitUnder3Min = function () {
        return !!document.getElementById('reels-limit-under-3min')?.checked;
    };

    function updateUnder3MinCheckboxUI() {
        const cb = document.getElementById('reels-limit-under-3min');
        if (!cb) return;

        // 恢复上次持久化的勾选状态
        if (!cb.dataset.flowcueInitLoaded) {
            cb.dataset.flowcueInitLoaded = '1';
            const saved = localStorage.getItem('flowcue_limit_under_3min');
            if (saved === '1') cb.checked = true;
            cb.addEventListener('change', () => {
                syncAllUnder3MinCheckboxes(cb.checked);
            });
        }

        // 1. 默认展开底部「🚀 导出设置」折叠栏，让导出按钮与自动调速开关一目了然
        const exportDetails = cb.closest('details.nle-export-bar');
        if (exportDetails && !exportDetails.dataset.flowcueAutoOpened) {
            exportDetails.dataset.flowcueAutoOpened = '1';
            exportDetails.open = true;
        }

        // 2. 在「🚀 导出设置」的 <summary> 标题栏右侧直接放置一个常驻显眼的【⏱️ 自动调速 ≤2分58秒】开关
        if (exportDetails) {
            const summary = exportDetails.querySelector('summary');
            if (summary && !summary.querySelector('#flowcue-summary-under3min')) {
                const badge = document.createElement('label');
                badge.id = 'flowcue-summary-under3min';
                badge.className = 'flowcue-under3min-banner';
                badge.style.marginLeft = '12px';
                badge.title = '勾选后：导出时若视频 ≤ 2分58秒则原速导出；若超过 2分58秒，自动加速至 ≤ 2分58秒，且核对的 SRT 字幕同步跳动不串行';
                badge.innerHTML = `
                    <input type="checkbox" class="flowcue-under3min-sync-cb" ${cb.checked ? 'checked' : ''} style="margin:0;cursor:pointer;accent-color:#10b981;">
                    <span>⏱️ 自动调速/视频时长不超过3分钟 (≤2分58秒，SRT字幕同步)</span>
                `;
                badge.addEventListener('click', (e) => {
                    // 阻止点击开关时收起/展开 <details>
                    e.stopPropagation();
                });
                const syncInput = badge.querySelector('input');
                syncInput.addEventListener('change', () => {
                    syncAllUnder3MinCheckboxes(syncInput.checked);
                });
                summary.appendChild(badge);
            }
        }

        // 3. 在批量表格底部栏 (.rbt-footer) 也放置一个显眼的同步开关
        const rbtFooter = document.querySelector('#reels-batch-table-container .rbt-footer');
        if (rbtFooter && !rbtFooter.querySelector('#flowcue-rbt-under3min')) {
            const rbtBadge = document.createElement('label');
            rbtBadge.id = 'flowcue-rbt-under3min';
            rbtBadge.className = 'flowcue-under3min-banner';
            rbtBadge.style.marginRight = '10px';
            rbtBadge.title = '勾选后：导出时若视频 ≤ 2分58秒则原速导出；若超过 2分58秒，自动加速至 ≤ 2分58秒，且核对的 SRT 字幕同步跳动不串行';
            rbtBadge.innerHTML = `
                <input type="checkbox" class="flowcue-under3min-sync-cb" ${cb.checked ? 'checked' : ''} style="margin:0;cursor:pointer;accent-color:#10b981;">
                <span>⏱️ 自动调速/时长≤3分钟 (≤2分58秒，SRT同步)</span>
            `;
            const applyBtn = rbtFooter.querySelector('#rbt-apply-btn');
            if (applyBtn) {
                rbtFooter.insertBefore(rbtBadge, applyBtn);
            } else {
                rbtFooter.appendChild(rbtBadge);
            }
            const syncInput = rbtBadge.querySelector('input');
            syncInput.addEventListener('change', () => {
                syncAllUnder3MinCheckboxes(syncInput.checked);
            });
        }

        // 4. 高亮原版导出栏内部的复选框标签
        const label = cb.closest('label');
        if (label && !label.dataset.flowcueUpdated) {
            label.dataset.flowcueUpdated = '1';
            label.className = 'flowcue-under3min-banner';
            label.title = '勾选后：若视频时长 ≤ 2分58秒则按原始速度导出；若超过 2分58秒（178秒），自动调整播放速度使成片低于且接近 2分58秒，且核对的 SRT 字幕与逐词动画同步加速跳动，绝不串行。';
            const spans = label.querySelectorAll('span');
            if (spans.length > 0) {
                spans[spans.length - 1].textContent = '(>2分58秒自动加速至≤2分58秒，SRT字幕同步跳动)';
                spans[spans.length - 1].style.color = '#a7f3d0';
            }
            Array.from(label.childNodes).forEach((node) => {
                if (node.nodeType === Node.TEXT_NODE && node.textContent.includes('不超过三分钟')) {
                    node.textContent = ' ⏱️ 自动调速/视频时长不超过3分钟 ';
                }
            });
        }
    }

    function formatSrtTimeMs(ms) {
        const clamped = Math.max(0, Math.round(ms));
        const h = Math.floor(clamped / 3600000);
        const m = Math.floor((clamped % 3600000) / 60000);
        const s = Math.floor((clamped % 60000) / 1000);
        const milli = clamped % 1000;
        return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')},${String(milli).padStart(3, '0')}`;
    }

    function installUnder3MinSpeedScalingOverride() {
        if (typeof window._getOrProbeReelsMediaDuration !== 'function') return false;

        const flowcueApplyUnder3Min = async function ({
            task,
            workMode,
            bgPath,
            voiceSource,
            globalCustomDuration = 0,
            introPath = '',
            doMp4 = true,
            onLog = null,
        }) {
            if (!task) return { applied: false };

            // 1. 计算前置封面 + Hook 时长
            let coverDur = 0;
            if (doMp4 && task.cover && task.cover.enabled !== false) {
                const cDur = parseFloat(task.cover.duration || 0);
                if (Number.isFinite(cDur) && cDur > 0) coverDur = cDur;
            }

            let hookDur = 0;
            if (doMp4 && typeof _resolveTaskHookPath === 'function') {
                const finalHookPath = _resolveTaskHookPath(task, introPath);
                if (finalHookPath) {
                    const rawHookDur = await _getOrProbeReelsMediaDuration(finalHookPath);
                    if (rawHookDur > 0) {
                        let effectiveHookRaw = rawHookDur;
                        const hTrimS = task.hookTrimStart != null ? parseFloat(task.hookTrimStart) : 0;
                        const hTrimE = task.hookTrimEnd != null ? parseFloat(task.hookTrimEnd) : 0;
                        if (Number.isFinite(hTrimE) && Number.isFinite(hTrimS) && hTrimE > hTrimS && hTrimS >= 0) {
                            effectiveHookRaw = hTrimE - hTrimS;
                        } else if (Number.isFinite(hTrimS) && hTrimS > 0) {
                            effectiveHookRaw = Math.max(0, rawHookDur - hTrimS);
                        }
                        const hookSpeed = Math.max(0.1, parseFloat(task.hookSpeed) || 1.0);
                        const transOverlap = (task.hookTransition && task.hookTransition !== 'none')
                            ? Math.max(0, parseFloat(task.hookTransDuration) || 0.5)
                            : 0;
                        hookDur = Math.max(0, (effectiveHookRaw / hookSpeed) - transOverlap);
                    }
                }
            }
            const prefixDur = Math.max(0, coverDur + hookDur);

            // 2. 计算当前正片预计时长
            const baseBgDurScale = Number(task.bgDurScale) || 100;
            const baseAudioDurScale = (!task.audioPath)
                ? (Number(task.bgDurScale) || Number(task.audioDurScale) || 100)
                : (Number(task.audioDurScale) || 100);
            const _bgDurFactor = baseBgDurScale / 100;
            const _audioDurFactor = baseAudioDurScale / 100;
            const _subDurFactor = voiceSource
                ? _audioDurFactor
                : (_audioDurFactor !== 1.0 ? _audioDurFactor : _bgDurFactor);

            const rawSubDuration = Array.isArray(task.segments) && task.segments.length > 0
                ? Math.max(0, ...task.segments.map(seg => parseFloat(seg?.end) || 0))
                : 0;
            const effectiveSubDuration = rawSubDuration * _subDurFactor;

            let maxFlipperDuration = 0;
            if (Array.isArray(task.overlays)) {
                for (const ov of task.overlays) {
                    if (ov && !ov.disabled && ov.flipper_enabled) {
                        const text = (ov.type === 'textcard') ? (ov.body_text || '') : (ov.content || '');
                        const lines = String(text).split('\n').map(l => l.trim()).filter(l => l.length > 0);
                        const flipperLines = parseInt(ov.flipper_lines, 10) || 2;
                        const flipperDurPerChunk = parseFloat(ov.flipper_duration) || 2.0;
                        const totalChunks = Math.ceil(lines.length / flipperLines);
                        const flipperDur = (parseFloat(ov.start) || 0) + (totalChunks * flipperDurPerChunk);
                        if (flipperDur > maxFlipperDuration) maxFlipperDuration = flipperDur;
                    }
                }
            }

            const resolvedCustomDur = typeof resolveReelsCustomDuration === 'function'
                ? resolveReelsCustomDuration(task, globalCustomDuration)
                : 0;
            let expectedMainDur = 0;

            if (maxFlipperDuration > 0) {
                expectedMainDur = maxFlipperDuration;
            } else if (resolvedCustomDur > 0) {
                expectedMainDur = resolvedCustomDur;
            } else {
                if (voiceSource) {
                    const rawAudioDur = await _getOrProbeReelsMediaDuration(voiceSource);
                    if (rawAudioDur > 0) {
                        expectedMainDur = Math.max(rawAudioDur * _audioDurFactor, effectiveSubDuration);
                    }
                }
                if ((!expectedMainDur || expectedMainDur <= 0) && task.contentVideoPath) {
                    const rawCvDur = await _getOrProbeReelsMediaDuration(task.contentVideoPath);
                    if (rawCvDur > 0) {
                        const trimS = parseFloat(task.contentVideoTrimStart) || 0;
                        const trimE = parseFloat(task.contentVideoTrimEnd) || 0;
                        const cvDur = (trimE > trimS && trimS >= 0) ? (trimE - trimS) : Math.max(0, rawCvDur - trimS);
                        if (cvDur > 0) {
                            expectedMainDur = Math.max(cvDur * _bgDurFactor, effectiveSubDuration);
                        }
                    }
                }
                if ((!expectedMainDur || expectedMainDur <= 0) && bgPath) {
                    const rawBgDur = await _getOrProbeReelsMediaDuration(bgPath);
                    if (rawBgDur > 0) {
                        expectedMainDur = Math.max(rawBgDur * _bgDurFactor, effectiveSubDuration);
                    }
                }
                if (!expectedMainDur || expectedMainDur <= 0) {
                    expectedMainDur = Math.max(effectiveSubDuration, Number(task.duration) || 5);
                }
            }

            const expectedTotalDur = prefixDur + expectedMainDur;
            // 未超过 2分58秒（178.0秒）：保持 1.0x 原始速度导出
            if (expectedTotalDur <= FLOWCUE_TRIGGER_SECONDS) {
                if (typeof onLog === 'function') {
                    onLog(`⏱️ [自动调速检查] 当前时长 ${expectedTotalDur.toFixed(2)}s ≤ 2分58秒(178s)，保持 1.00x 原始速度导出`);
                }
                return {
                    applied: false,
                    expectedTotalDur,
                    targetTotalDur: expectedTotalDur,
                    speedDurFactor: 1.0,
                };
            }

            // 超过 2分58秒（178.0秒）：自动加速，使最终视频时长低于且接近 2分58秒（目标 177.5s）
            const targetMainDur = Math.max(1.0, FLOWCUE_TARGET_SECONDS - prefixDur);
            const speedDurFactor = targetMainDur / expectedMainDur;
            const playbackSpeed = 1 / speedDurFactor;

            // 关键：同时设置 bgDurScale 与 audioDurScale 为完全相同的精确缩放百分比，
            // 确保背景视频、前景口播视频、人声音轨、核对的 SRT 字幕（含逐词时间戳 words）100% 同步缩放！
            const nextBgScale = Number((baseBgDurScale * speedDurFactor).toFixed(4));
            const nextAudioScale = Number((baseAudioDurScale * speedDurFactor).toFixed(4));
            task.bgDurScale = nextBgScale;
            task.audioDurScale = nextAudioScale;

            // 若 contentVideoPath 与人声源是同一视频文件，避免 FFmpeg 重复混音
            if (task.contentVideoPath && voiceSource && task.contentVideoPath === voiceSource) {
                task.contentVideoVolume = 0;
            }

            if (resolvedCustomDur > 0) {
                task.customDuration = Number((resolvedCustomDur * speedDurFactor).toFixed(3));
            }

            // 同步缩放覆层时间轴与翻转器
            if (Array.isArray(task.overlays)) {
                task.overlays.forEach(ov => {
                    if (!ov || typeof ov !== 'object') return;
                    const startVal = parseFloat(ov.start);
                    if (Number.isFinite(startVal) && startVal > 0) {
                        ov.start = Number((startVal * speedDurFactor).toFixed(3));
                    }
                    const endVal = parseFloat(ov.end);
                    if (Number.isFinite(endVal) && endVal > 0 && endVal < 9000) {
                        ov.end = Number((endVal * speedDurFactor).toFixed(3));
                    }
                    if (ov.flipper_enabled) {
                        const fDur = parseFloat(ov.flipper_duration);
                        if (Number.isFinite(fDur) && fDur > 0) {
                            ov.flipper_duration = Number((fDur * speedDurFactor).toFixed(4));
                        }
                    }
                    if (Array.isArray(ov.subtitle_time_slices)) {
                        ov.subtitle_time_slices.forEach(slice => {
                            if (!slice || typeof slice !== 'object') return;
                            if (Number.isFinite(Number(slice.startSec))) {
                                slice.startSec = Number((Number(slice.startSec) * speedDurFactor).toFixed(3));
                            }
                            if (slice.endSec != null && Number.isFinite(Number(slice.endSec))) {
                                slice.endSec = Number((Number(slice.endSec) * speedDurFactor).toFixed(3));
                            }
                        });
                    }
                });
            }

            if (Array.isArray(task.subtitleTimeSlices)) {
                task.subtitleTimeSlices.forEach(slice => {
                    if (!slice || typeof slice !== 'object') return;
                    if (Number.isFinite(Number(slice.startSec))) {
                        slice.startSec = Number((Number(slice.startSec) * speedDurFactor).toFixed(3));
                    }
                    if (slice.endSec != null && Number.isFinite(Number(slice.endSec))) {
                        slice.endSec = Number((Number(slice.endSec) * speedDurFactor).toFixed(3));
                    }
                });
            }

            // 同步缩放插入素材片段（insertClips 与 insertAudio）
            if (Array.isArray(task.insertClips)) {
                task.insertClips.forEach(item => {
                    if (!item || typeof item !== 'object') return;
                    if (Number.isFinite(Number(item.timelineStart))) {
                        item.timelineStart = Number((Number(item.timelineStart) * speedDurFactor).toFixed(3));
                    }
                    if (Number.isFinite(Number(item.duration))) {
                        item.duration = Number((Number(item.duration) * speedDurFactor).toFixed(3));
                    }
                });
            }
            if (Array.isArray(task.insertAudio)) {
                task.insertAudio.forEach(item => {
                    if (!item || typeof item !== 'object') return;
                    if (Number.isFinite(Number(item.timelineStart))) {
                        item.timelineStart = Number((Number(item.timelineStart) * speedDurFactor).toFixed(3));
                    }
                    if (Number.isFinite(Number(item.duration))) {
                        item.duration = Number((Number(item.duration) * speedDurFactor).toFixed(3));
                    }
                });
            }

            const finalTargetTotal = prefixDur + targetMainDur;
            if (typeof onLog === 'function') {
                onLog(
                    `⏱️ [自动调速 ≤2分58秒] 原时长 ${expectedTotalDur.toFixed(2)}s 已超过 2分58秒(178s)，` +
                    `已自动加速 ${playbackSpeed.toFixed(3)}x（时长缩放 ${(speedDurFactor * 100).toFixed(2)}%），` +
                    `目标成片 ${finalTargetTotal.toFixed(2)}s (≤2分58秒)，视频、音频与核对的 SRT 字幕已 100% 同步加速！`
                );
            }

            return {
                applied: true,
                expectedTotalDur,
                targetTotalDur: finalTargetTotal,
                speedDurFactor,
                playbackSpeed,
                bgDurScale: task.bgDurScale,
                audioDurScale: task.audioDurScale,
            };
        };

        window._applyUnder3MinSpeedScalingToTask = flowcueApplyUnder3Min;
        try {
            _applyUnder3MinSpeedScalingToTask = flowcueApplyUnder3Min;
        } catch (_) {}

        // 当用户手动调节背景视频速度（#reels-bg-dur-scale-num）且任务无独立音频轨时，同步 audioDurScale 以保证预览与导出字幕不串行
        if (typeof window.reelsSaveBgConfigUI === 'function' && !window.reelsSaveBgConfigUI._flowcueWrapped) {
            const origSaveBg = window.reelsSaveBgConfigUI;
            const wrappedSaveBg = function (...args) {
                const res = origSaveBg.apply(this, args);
                try {
                    const t = typeof _getSelectedTask === 'function' ? _getSelectedTask() : null;
                    if (t && !t.audioPath && t.bgDurScale) {
                        t.audioDurScale = t.bgDurScale;
                    }
                } catch (_) {}
                return res;
            };
            wrappedSaveBg._flowcueWrapped = true;
            window.reelsSaveBgConfigUI = wrappedSaveBg;
        }

        // 在导出 isolatedWysiwygExport / reelsWysiwygExport 时，如果视频被变速，同步在导出视频旁输出变速后的同名 .srt 字幕文件
        if (window.electronAPI && typeof window.electronAPI.isolatedWysiwygExport === 'function' && !window.electronAPI.isolatedWysiwygExport._flowcueWrapped) {
            const origIsolated = window.electronAPI.isolatedWysiwygExport.bind(window.electronAPI);
            const wrappedIsolated = async function (opts = {}) {
                const res = await origIsolated(opts);
                try {
                    const p = opts.params || {};
                    const outMp4 = p.outputPath || '';
                    const segs = Array.isArray(p.segments) ? p.segments : [];
                    const aFactor = (Number(p.audioDurScale) || 100) / 100;
                    const bFactor = (Number(p.bgDurScale) || 100) / 100;
                    const factor = p.voicePath ? aFactor : (aFactor !== 1.0 ? aFactor : bFactor);
                    if (outMp4 && segs.length > 0 && Math.abs(factor - 1.0) > 0.0001 && window.require) {
                        const fs = window.require('fs');
                        const outSrt = outMp4.replace(/\.[^.]+$/, '.srt');
                        const lines = segs.map((seg, i) => {
                            const sMs = (Number(seg.start) || 0) * factor * 1000;
                            const eMs = (Number(seg.end) || 0) * factor * 1000;
                            const txt = String(seg.edited_text || seg.text || '').trim();
                            return `${i + 1}\n${formatSrtTimeMs(sMs)} --> ${formatSrtTimeMs(eMs)}\n${txt}\n`;
                        });
                        fs.writeFileSync(outSrt, lines.join('\n'), 'utf-8');
                    }
                } catch (err) {
                    console.warn('[FlowCue] 导出同步变速 SRT 副本失败:', err);
                }
                return res;
            };
            wrappedIsolated._flowcueWrapped = true;
            window.electronAPI.isolatedWysiwygExport = wrappedIsolated;
        }

        return true;
    }

    // ═══════════════════════════════════════════════════════════════════════
    // 4. 批量表格（Batch Table）直接选择 & 复制/粘贴预设名称批量设置字幕预设和覆层预设
    // ═══════════════════════════════════════════════════════════════════════
    function getAllSubtitlePresetNames() {
        const names = new Set();
        try {
            if (window.REELS_BUILTIN_PRESETS) {
                Object.keys(window.REELS_BUILTIN_PRESETS).forEach(k => names.add(k));
            }
            const custom = JSON.parse(localStorage.getItem('reels_style_presets') || '{}');
            Object.keys(custom).forEach(k => names.add(k));
        } catch (_) {}
        return Array.from(names);
    }

    function getAllOverlayPresetNames() {
        const names = new Set();
        try {
            if (window.REELS_BUILTIN_OVERLAY_GROUP_PRESETS) {
                Object.keys(window.REELS_BUILTIN_OVERLAY_GROUP_PRESETS).forEach(k => names.add(k));
            }
            const custom = JSON.parse(localStorage.getItem('reels_overlay_group_presets') || '{}');
            Object.keys(custom).forEach(k => names.add(k));
        } catch (_) {}
        return Array.from(names);
    }

    function matchPresetNameFuzzy(rawInput, candidates) {
        const clean = String(rawInput || '').trim();
        if (!clean || clean === '默认' || clean === '无' || clean === '无覆层' || clean === '无预设') return '';
        if (candidates.includes(clean)) return clean;
        const lower = clean.toLowerCase();
        const exactCaseInsensitive = candidates.find(c => c.toLowerCase() === lower);
        if (exactCaseInsensitive) return exactCaseInsensitive;
        const partial = candidates.find(c => c.toLowerCase().includes(lower) || lower.includes(c.toLowerCase()));
        return partial || clean;
    }

    function applySubtitlePresetToTaskRow(idx, presetNameRaw) {
        const tasks = window._reelsState?.tasks || [];
        const task = tasks[idx];
        if (!task) return false;
        const candidates = getAllSubtitlePresetNames();
        const matched = matchPresetNameFuzzy(presetNameRaw, candidates);
        task._subtitlePreset = matched;
        return true;
    }

    function applyOverlayPresetToTaskRow(idx, presetNameRaw) {
        const tasks = window._reelsState?.tasks || [];
        const task = tasks[idx];
        if (!task) return false;
        const candidates = getAllOverlayPresetNames();
        const matched = matchPresetNameFuzzy(presetNameRaw, candidates);
        // 同步更新当前 DOM 中的 .rbt-card-tpl-select，防止 _renderBatchTable 内部的 _applyBatchTableChanges 用旧空值覆盖
        const domSelect = document.querySelector(`.rbt-card-tpl-select[data-idx="${idx}"]`);
        if (!matched) {
            task._overlayPresetName = '';
            task.overlays = [];
            if (domSelect) domSelect.value = '';
            return true;
        }
        task._overlayPresetName = matched;
        if (domSelect) {
            if (!Array.from(domSelect.options).some(opt => opt.value === matched)) {
                const opt = document.createElement('option');
                opt.value = matched;
                opt.textContent = matched;
                domSelect.appendChild(opt);
            }
            domSelect.value = matched;
        }
        if (typeof _applyAndVerifyOverlayGroupPresetToTask === 'function') {
            _applyAndVerifyOverlayGroupPresetToTask(task, matched, { addScroll: false, clearText: false });
        } else if (typeof _applyOverlayGroupPresetToTask === 'function') {
            _applyOverlayGroupPresetToTask(task, matched, { addScroll: false, clearText: false });
        }
        if (typeof _syncSelectedTaskOverlayMgrIfNeeded === 'function') {
            _syncSelectedTaskOverlayMgrIfNeeded(idx);
        }
        return true;
    }

    function getTargetRowIndicesForBatchPaste(anchorIdx) {
        let selected = [];
        try {
            if (typeof _getSelectedIndices === 'function') {
                selected = _getSelectedIndices();
            } else if (window._batchTableState?.selectedRows) {
                selected = Array.from(window._batchTableState.selectedRows);
            }
        } catch (_) {}
        if (selected.length > 1 && (anchorIdx == null || selected.includes(anchorIdx))) {
            return selected.slice().sort((a, b) => a - b);
        }
        if (anchorIdx != null && anchorIdx >= 0) {
            return [anchorIdx];
        }
        const total = window._reelsState?.tasks?.length || 0;
        if (selected.length === 1) return selected;
        return Array.from({ length: total }, (_, i) => i);
    }

    function handleBatchPresetPaste(kind, rawText, anchorIdx = null) {
        const lines = String(rawText ?? '')
            .split(/\r?\n/)
            .map(s => s.trim())
            .filter(Boolean);
        if (lines.length === 0) return;

        const tasks = window._reelsState?.tasks || [];
        if (tasks.length === 0) return;

        let appliedCount = 0;
        if (lines.length === 1) {
            // 单行预设名称：
            // - 若点击的是列标题 📋粘贴按钮 (anchorIdx == null)，且未勾选特定行，则一键填充整列所有任务！
            // - 若勾选了多行，则一键填充所有勾选行！
            const indices = getTargetRowIndicesForBatchPaste(anchorIdx);
            const presetName = lines[0];
            indices.forEach(idx => {
                if (kind === 'subtitle') {
                    if (applySubtitlePresetToTaskRow(idx, presetName)) appliedCount++;
                } else {
                    if (applyOverlayPresetToTaskRow(idx, presetName)) appliedCount++;
                }
            });
        } else {
            // 多行预设名称（如从 Excel / Google Sheets 整列复制多行预设名）：
            // 从 anchorIdx（或第 0 行 / 勾选行）开始按行依次填入整列！
            const selected = (typeof _getSelectedIndices === 'function') ? _getSelectedIndices() : [];
            if (anchorIdx == null && selected.length === lines.length) {
                selected.forEach((rowIdx, i) => {
                    if (kind === 'subtitle') {
                        if (applySubtitlePresetToTaskRow(rowIdx, lines[i])) appliedCount++;
                    } else {
                        if (applyOverlayPresetToTaskRow(rowIdx, lines[i])) appliedCount++;
                    }
                });
            } else {
                const startRow = anchorIdx != null && anchorIdx >= 0 ? anchorIdx : (selected.length > 0 && selected.length < tasks.length ? selected[0] : 0);
                for (let i = 0; i < lines.length; i++) {
                    const rowIdx = startRow + i;
                    if (rowIdx >= tasks.length) break;
                    if (kind === 'subtitle') {
                        if (applySubtitlePresetToTaskRow(rowIdx, lines[i])) appliedCount++;
                    } else {
                        if (applyOverlayPresetToTaskRow(rowIdx, lines[i])) appliedCount++;
                    }
                }
            }
        }

        if (typeof _renderBatchTable === 'function') _renderBatchTable();
        if (typeof reelsUpdatePreview === 'function') reelsUpdatePreview();
        if (typeof window.reelsSaveHistory === 'function') window.reelsSaveHistory();
        if (typeof showToast === 'function') {
            const label = kind === 'subtitle' ? '动态字幕模版' : '覆层预设';
            showToast(`✅ 已按预设名称批量设置 ${appliedCount} 行的【${label}】`, 'success', 2800);
        }
    }

    function handleBatchPresetPasteOnInput(inputEl, pastedText) {
        if (!inputEl) return;
        const kind = inputEl.dataset.presetKind || 'subtitle';
        const idx = parseInt(inputEl.dataset.idx, 10);
        handleBatchPresetPaste(kind, pastedText, Number.isFinite(idx) ? idx : null);
    }

    function ensurePresetDatalists() {
        let subList = document.getElementById('flowcue-sub-presets-datalist');
        if (!subList) {
            subList = document.createElement('datalist');
            subList.id = 'flowcue-sub-presets-datalist';
            document.body.appendChild(subList);
        }
        const nextSubHtml = getAllSubtitlePresetNames()
            .map(n => `<option value="${String(n).replace(/"/g, '&quot;')}"></option>`)
            .join('');
        if (subList.dataset.lastHtml !== nextSubHtml) {
            subList.dataset.lastHtml = nextSubHtml;
            subList.innerHTML = nextSubHtml;
        }

        let ovList = document.getElementById('flowcue-ov-presets-datalist');
        if (!ovList) {
            ovList = document.createElement('datalist');
            ovList.id = 'flowcue-ov-presets-datalist';
            document.body.appendChild(ovList);
        }
        const nextOvHtml = getAllOverlayPresetNames()
            .map(n => `<option value="${String(n).replace(/"/g, '&quot;')}"></option>`)
            .join('');
        if (ovList.dataset.lastHtml !== nextOvHtml) {
            ovList.dataset.lastHtml = nextOvHtml;
            ovList.innerHTML = nextOvHtml;
        }
    }

    function getBatchTableContainerEl() {
        return (
            document.getElementById('reels-batch-table-container') ||
            document.getElementById('reels-batch-table-overlay') ||
            (document.getElementById('rbt-table') ? document.getElementById('rbt-table').closest('div') : null)
        );
    }

    function enhanceBatchTablePresetColumns() {
        const container = getBatchTableContainerEl();
        if (!container) return;

        ensurePresetDatalists();
        updateUnder3MinCheckboxUI();

        // 1. 增强表头「动态字幕模版」和「覆层预设」：使用与其他列完全一致的 .rbt-th-wrap 布局，加入「📋」整列粘贴和「清」按钮
        const ths = container.querySelectorAll('thead th.rbt-col-tpl');
        ths.forEach((th, colIdx) => {
            if (th.dataset.flowcueEnhanced === '1') return;
            const text = (th.textContent || '').trim();
            const isSub = text.includes('字幕') || colIdx === 0;
            const kind = isSub ? 'subtitle' : 'overlay';
            const titleLabel = isSub ? '动态字幕模版' : '覆层预设';
            th.dataset.flowcueEnhanced = '1';
            th.style.minWidth = isSub ? '168px' : '168px';
            th.innerHTML = `
                <div class="rbt-th-wrap">
                    <span>${titleLabel}</span>
                    <button type="button" class="rbt-th-paste flowcue-col-preset-paste" data-kind="${kind}" title="从剪贴板粘贴整列【${titleLabel}】名称（支持从Excel粘贴多行或单个预设名填充整列）" style="opacity:1 !important;pointer-events:auto !important;">📋</button>
                    <button type="button" class="rbt-th-clear flowcue-col-preset-clear" data-kind="${kind}" title="清空该列【${titleLabel}】" style="opacity:1 !important;pointer-events:auto !important;">清</button>
                </div>
            `;
            const pasteBtn = th.querySelector('.flowcue-col-preset-paste');
            const clearBtn = th.querySelector('.flowcue-col-preset-clear');
            pasteBtn?.addEventListener('click', async (e) => {
                e.preventDefault();
                e.stopPropagation();
                e.stopImmediatePropagation();
                const clipText = await readClipboardTextSyncOrAsync();
                if (!clipText || !clipText.trim()) {
                    if (typeof showToast === 'function') {
                        showToast(`剪贴板为空！请先复制${titleLabel}名称再点击 📋 粘贴整列`, 'warning', 2500);
                    }
                    return;
                }
                handleBatchPresetPaste(kind, clipText, null);
            }, true);
            clearBtn?.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                e.stopImmediatePropagation();
                const indices = getTargetRowIndicesForBatchPaste(null);
                indices.forEach(idx => {
                    if (kind === 'subtitle') applySubtitlePresetToTaskRow(idx, '');
                    else applyOverlayPresetToTaskRow(idx, '');
                });
                if (typeof _renderBatchTable === 'function') _renderBatchTable();
                if (typeof reelsUpdatePreview === 'function') reelsUpdatePreview();
                if (typeof showToast === 'function') {
                    showToast(`✅ 已清空 ${indices.length} 行的【${titleLabel}】`, 'success', 2200);
                }
            }, true);
        });

        // 2. 增强每一行的「动态字幕模版」与「覆层预设」单元格：
        //    同时提供可粘贴整列/单行预设名称的输入框 + 原有下拉选择器 + 📋复制按钮
        const rows = container.querySelectorAll('tbody tr.rbt-row');
        rows.forEach((tr) => {
            const idx = parseInt(tr.dataset.idx, 10);
            if (Number.isNaN(idx)) return;
            const task = window._reelsState?.tasks?.[idx];
            if (!task) return;

            // (A) 动态字幕模版单元格
            const subTrigger = tr.querySelector('.rbt-sub-tpl-trigger');
            if (subTrigger) {
                const td = subTrigger.closest('td');
                if (td && !subTrigger.dataset.flowcueSubEnhanced && !td.dataset.flowcueSubCell && !td.querySelector('.flowcue-tpl-name-input')) {
                    subTrigger.dataset.flowcueSubEnhanced = '1';
                    td.dataset.flowcueSubCell = '1';
                    td.style.minWidth = '168px';
                    const curSub = task._subtitlePreset || '';

                    const wrapper = document.createElement('div');
                    wrapper.className = 'flowcue-sub-cell-wrap';
                    wrapper.style.cssText = 'display:flex;align-items:center;gap:3px;width:100%;';

                    subTrigger.style.cssText = 'cursor:pointer;font-size:10px;padding:0 5px;height:22px;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;background:rgba(99,102,241,0.22);border:1px solid rgba(99,102,241,0.45);border-radius:3px;color:#c7d2fe;';
                    subTrigger.innerHTML = '<span>▼</span>';
                    subTrigger.title = '点击打开字幕模版下拉选择器';

                    const nameInput = document.createElement('input');
                    nameInput.type = 'text';
                    nameInput.className = 'flowcue-tpl-name-input';
                    nameInput.setAttribute('list', 'flowcue-sub-presets-datalist');
                    nameInput.dataset.idx = String(idx);
                    nameInput.dataset.presetKind = 'subtitle';
                    nameInput.value = curSub;
                    nameInput.placeholder = '默认 (可粘贴整列)';
                    nameInput.title = '可直接输入或按 Ctrl+V 粘贴字幕预设名称（支持直接粘贴多行整列，或配合表头 📋 按钮粘贴整列）';
                    nameInput.style.cssText = 'flex:1;min-width:72px;height:22px;font-size:11px;padding:0 5px;background:rgba(0,0,0,0.38);color:#fff;border:1px solid rgba(255,255,255,0.16);border-radius:3px;box-sizing:border-box;';

                    const copyBtn = document.createElement('button');
                    copyBtn.type = 'button';
                    copyBtn.className = 'rbt-btn-tiny';
                    copyBtn.textContent = '📋';
                    copyBtn.title = '复制此行的字幕模版名称';
                    copyBtn.style.cssText = 'padding:0 4px;height:22px;font-size:10px;flex-shrink:0;cursor:pointer;';

                    copyBtn.addEventListener('click', async (ev) => {
                        ev.stopPropagation();
                        const valToCopy = nameInput.value || task._subtitlePreset || '';
                        if (!valToCopy) {
                            if (typeof showToast === 'function') showToast('当前行使用的是默认字幕模版', 'warning', 1800);
                            return;
                        }
                        await writeClipboardTextSyncOrAsync(valToCopy);
                        if (typeof showToast === 'function') showToast(`📋 已复制字幕模版名: ${valToCopy}`, 'info', 2000);
                    });

                    nameInput.addEventListener('paste', (ev) => {
                        ev.preventDefault();
                        ev.stopPropagation();
                        ev.stopImmediatePropagation();
                        const txt = (ev.clipboardData || window.clipboardData)?.getData('text') || '';
                        if (txt) handleBatchPresetPaste('subtitle', txt, idx);
                    }, true);

                    nameInput.addEventListener('keydown', (ev) => {
                        if (ev.key === 'Enter') {
                            ev.preventDefault();
                            handleBatchPresetPaste('subtitle', nameInput.value, idx);
                        }
                    });

                    nameInput.addEventListener('change', () => {
                        applySubtitlePresetToTaskRow(idx, nameInput.value);
                        if (typeof _renderBatchTable === 'function') _renderBatchTable();
                        if (typeof reelsUpdatePreview === 'function') reelsUpdatePreview();
                    });

                    td.insertBefore(wrapper, subTrigger);
                    wrapper.appendChild(nameInput);
                    wrapper.appendChild(subTrigger);
                    wrapper.appendChild(copyBtn);
                } else if (td) {
                    const existingInput = td.querySelector('.flowcue-tpl-name-input');
                    if (existingInput && document.activeElement !== existingInput) {
                        const targetVal = task._subtitlePreset || '';
                        if (existingInput.value !== targetVal) {
                            existingInput.value = targetVal;
                        }
                    }
                }
            }

            // (B) 覆层预设单元格
            const cardSelect = tr.querySelector('.rbt-card-tpl-select');
            if (cardSelect) {
                const td = cardSelect.closest('td');
                if (td && !cardSelect.dataset.flowcueOvEnhanced && !td.dataset.flowcueOvCell && !td.querySelector('.flowcue-tpl-name-input')) {
                    cardSelect.dataset.flowcueOvEnhanced = '1';
                    td.dataset.flowcueOvCell = '1';
                    td.style.minWidth = '168px';
                    const curOv = task._overlayPresetName || '';

                    const wrapper = document.createElement('div');
                    wrapper.className = 'flowcue-ov-cell-wrap';
                    wrapper.style.cssText = 'display:flex;align-items:center;gap:3px;width:100%;';

                    cardSelect.style.cssText = 'width:52px;height:22px;font-size:10px;padding:0 2px;flex-shrink:0;';
                    cardSelect.title = '下拉选择覆层预设';

                    const nameInput = document.createElement('input');
                    nameInput.type = 'text';
                    nameInput.className = 'flowcue-tpl-name-input';
                    nameInput.setAttribute('list', 'flowcue-ov-presets-datalist');
                    nameInput.dataset.idx = String(idx);
                    nameInput.dataset.presetKind = 'overlay';
                    nameInput.value = curOv;
                    nameInput.placeholder = '无预设 (可粘贴整列)';
                    nameInput.title = '可直接输入或按 Ctrl+V 粘贴覆层预设名称（支持直接粘贴多行整列，或配合表头 📋 按钮粘贴整列）';
                    nameInput.style.cssText = 'flex:1;min-width:72px;height:22px;font-size:11px;padding:0 5px;background:rgba(0,0,0,0.38);color:#fff;border:1px solid rgba(255,255,255,0.16);border-radius:3px;box-sizing:border-box;';

                    const copyBtn = document.createElement('button');
                    copyBtn.type = 'button';
                    copyBtn.className = 'rbt-btn-tiny';
                    copyBtn.textContent = '📋';
                    copyBtn.title = '复制此行的覆层预设名称';
                    copyBtn.style.cssText = 'padding:0 4px;height:22px;font-size:10px;flex-shrink:0;cursor:pointer;';

                    copyBtn.addEventListener('click', async (ev) => {
                        ev.stopPropagation();
                        const valToCopy = nameInput.value || task._overlayPresetName || '';
                        if (!valToCopy) {
                            if (typeof showToast === 'function') showToast('当前行未设置覆层预设名称', 'warning', 1800);
                            return;
                        }
                        await writeClipboardTextSyncOrAsync(valToCopy);
                        if (typeof showToast === 'function') showToast(`📋 已复制覆层预设名: ${valToCopy}`, 'info', 2000);
                    });

                    nameInput.addEventListener('paste', (ev) => {
                        ev.preventDefault();
                        ev.stopPropagation();
                        ev.stopImmediatePropagation();
                        const txt = (ev.clipboardData || window.clipboardData)?.getData('text') || '';
                        if (txt) handleBatchPresetPaste('overlay', txt, idx);
                    }, true);

                    nameInput.addEventListener('keydown', (ev) => {
                        if (ev.key === 'Enter') {
                            ev.preventDefault();
                            handleBatchPresetPaste('overlay', nameInput.value, idx);
                        }
                    });

                    nameInput.addEventListener('change', () => {
                        applyOverlayPresetToTaskRow(idx, nameInput.value);
                        if (typeof _renderBatchTable === 'function') _renderBatchTable();
                        if (typeof reelsUpdatePreview === 'function') reelsUpdatePreview();
                    });

                    cardSelect.addEventListener('change', () => {
                        setTimeout(() => {
                            if (document.activeElement !== nameInput) {
                                nameInput.value = cardSelect.value || task._overlayPresetName || '';
                            }
                        }, 30);
                    });

                    td.insertBefore(wrapper, cardSelect);
                    wrapper.appendChild(nameInput);
                    wrapper.appendChild(cardSelect);
                    wrapper.appendChild(copyBtn);
                } else if (td) {
                    const existingInput = td.querySelector('.flowcue-tpl-name-input');
                    if (existingInput && document.activeElement !== existingInput) {
                        const targetVal = task._overlayPresetName || cardSelect.value || '';
                        if (existingInput.value !== targetVal) {
                            existingInput.value = targetVal;
                        }
                    }
                }
            }
        });
    }

    function hookBatchTableRender() {
        if (typeof window._renderBatchTable === 'function' && !window._renderBatchTable._flowcueWrapped) {
            const origRender = window._renderBatchTable;
            const wrappedRender = function (...args) {
                const res = origRender.apply(this, args);
                try {
                    enhanceBatchTablePresetColumns();
                    ensureAllRangeSlidersHaveNumberInput(getBatchTableContainerEl() || document);
                } catch (e) {
                    console.warn('[FlowCue] enhanceBatchTablePresetColumns error:', e);
                }
                return res;
            };
            wrappedRender._flowcueWrapped = true;
            window._renderBatchTable = wrappedRender;
            try { _renderBatchTable = wrappedRender; } catch (_) {}
            return true;
        }
        return false;
    }

    // ═══════════════════════════════════════════════════════════════════════
    // 5. 字幕预设与覆层预设实时双保险自动备份（防止更新或端口变化丢失）
    // ═══════════════════════════════════════════════════════════════════════
    const PRESET_STORAGE_KEYS = [
        'reels_style_presets',
        'reels_overlay_presets',
        'reels_overlay_group_presets',
        'reels_multi_export_presets',
        'reels_export_presets',
        'reels_batch_custom_presets',
        'reels_custom_fonts',
    ];

    let _backupTimer = null;
    function schedulePresetBackupToDisk() {
        if (_backupTimer) clearTimeout(_backupTimer);
        _backupTimer = setTimeout(() => {
            try {
                const snapshot = {};
                PRESET_STORAGE_KEYS.forEach((k) => {
                    const v = localStorage.getItem(k);
                    if (typeof v === 'string' && v.length > 2) {
                        snapshot[k] = v;
                    }
                });
                if (Object.keys(snapshot).length === 0) return;
                if (window.electronAPI?.savePresetsBackup) {
                    window.electronAPI.savePresetsBackup(snapshot).catch(() => {});
                }
                if (CTRL_PORT > 0) {
                    fetch(`http://127.0.0.1:${CTRL_PORT}/backup-presets`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ entries: snapshot }),
                    }).catch(() => {});
                }
            } catch (_) {}
        }, 400);
    }

    const origSetItem = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
        origSetItem.call(this, key, value);
        if (PRESET_STORAGE_KEYS.includes(String(key))) {
            schedulePresetBackupToDisk();
        }
    };

    // ═══════════════════════════════════════════════════════════════════════
    // 初始化与 DOM 动态监听
    // ═══════════════════════════════════════════════════════════════════════
    let _isRunningEnhancements = false;
    function initAllEnhancements() {
        if (_isRunningEnhancements) return;
        _isRunningEnhancements = true;
        try {
            ensureAllRangeSlidersHaveNumberInput(document);
            updateUnder3MinCheckboxUI();
            installUnder3MinSpeedScalingOverride();
            hookBatchTableRender();
            enhanceBatchTablePresetColumns();
            schedulePresetBackupToDisk();
        } catch (err) {
            console.warn('[FlowCue] initAllEnhancements error:', err);
        } finally {
            _isRunningEnhancements = false;
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAllEnhancements);
    } else {
        initAllEnhancements();
    }

    // 持续监听动态面板（如覆层面板 ReelsOverlayPanel、批量表格弹窗、保存预设弹窗），防抖避免递归
    let _observerTimer = null;
    const observer = new MutationObserver((mutations) => {
        if (_isRunningEnhancements) return;
        let shouldScan = false;
        for (const m of mutations) {
            if (m.target && (m.target.tagName === 'DATALIST' || String(m.target.id || '').startsWith('flowcue-'))) {
                continue;
            }
            if (m.addedNodes && m.addedNodes.length > 0) {
                shouldScan = true;
                break;
            }
        }
        if (shouldScan) {
            if (_observerTimer) clearTimeout(_observerTimer);
            _observerTimer = setTimeout(() => {
                _observerTimer = null;
                initAllEnhancements();
            }, 140);
        }
    });
    if (document.body) {
        observer.observe(document.body, { childList: true, subtree: true });
    } else {
        window.addEventListener('DOMContentLoaded', () => {
            observer.observe(document.body, { childList: true, subtree: true });
        });
    }

    setInterval(initAllEnhancements, 2000);
    console.log('[FlowCue] 批量Reels 增强补丁已激活 (键盘焦点修复 / 全参数滚轮微调 / 2分58秒自动变速同步字幕 / 批量表格预设复制粘贴 / 预设双备份)');
})();
