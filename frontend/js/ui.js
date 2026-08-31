/* ui.js — v1.37.0
 * Globale UX-Utilities: Toast + Confirm-Dialog.
 *
 * Bisher hatte nur das Ausgaben-Modul einen eigenen Toast (.ausg-toast),
 * und Bestätigungen liefen über native window.confirm()/alert() -- das
 * bricht optisch den Apple-artigen Look der App komplett.
 *
 * Diese Datei stellt modul-übergreifend zur Verfügung:
 *   Toast.show(msg, {type, timeout, action})       -> Promise<void>
 *   Toast.success(msg) / Toast.error(msg) / Toast.info(msg)
 *   Confirm.ask({title, text, ok, cancel, danger}) -> Promise<boolean>
 *   Confirm.alert({title, text, ok})               -> Promise<void>
 *
 * Wird automatisch von nav-switcher.js nachgeladen; einzelne Seiten
 * müssen nichts extra einbinden. Idempotent.
 */
(function () {
    if (window.__vexbobUI) return;
    window.__vexbobUI = true;

    // -------------------------------------------------------------- Toast
    function ensureToastLayer() {
        let el = document.getElementById('uiToastLayer');
        if (el) return el;
        el = document.createElement('div');
        el.id = 'uiToastLayer';
        el.className = 'ui-toast-layer';
        el.setAttribute('aria-live', 'polite');
        el.setAttribute('aria-atomic', 'true');
        document.body.appendChild(el);
        return el;
    }

    function showToast(message, opts) {
        opts = opts || {};
        const type = opts.type || 'info';
        const timeout = opts.timeout == null ? 3200 : opts.timeout;
        const action = opts.action || null;
        const layer = ensureToastLayer();
        return new Promise((resolve) => {
            const t = document.createElement('div');
            t.className = 'ui-toast ui-toast-' + type;
            t.setAttribute('role', 'status');
            const msg = document.createElement('span');
            msg.className = 'ui-toast-msg';
            msg.textContent = message;
            t.appendChild(msg);
            let timer = null;
            const dismiss = () => {
                if (timer) clearTimeout(timer);
                t.classList.remove('show');
                setTimeout(() => { t.remove(); resolve(); }, 220);
            };
            if (action && typeof action.onClick === 'function') {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'ui-toast-action';
                btn.textContent = action.label || 'OK';
                btn.addEventListener('click', () => {
                    try { action.onClick(); } catch (e) {}
                    dismiss();
                });
                t.appendChild(btn);
            }
            layer.appendChild(t);
            requestAnimationFrame(() => t.classList.add('show'));
            if (timeout > 0) timer = setTimeout(dismiss, timeout);
        });
    }

    window.Toast = {
        show:    (msg, opts) => showToast(msg, opts),
        info:    (msg, opts) => showToast(msg, { ...(opts || {}), type: 'info' }),
        success: (msg, opts) => showToast(msg, { ...(opts || {}), type: 'success' }),
        error:   (msg, opts) => showToast(msg, { ...(opts || {}), type: 'error', timeout: (opts && opts.timeout) || 4500 }),
    };
    // ------------------------------------------------------------ Confirm
    function openConfirm(opts) {
        opts = opts || {};
        const title = opts.title || 'Bist du sicher?';
        const text = opts.text || '';
        const okLabel = opts.ok || 'Bestätigen';
        const cancelLabel = opts.cancel === null ? null : (opts.cancel || 'Abbrechen');
        const danger = !!opts.danger;

        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.className = 'modal-overlay ui-confirm-overlay';
            overlay.setAttribute('role', 'dialog');
            overlay.setAttribute('aria-modal', 'true');

            const box = document.createElement('div');
            box.className = 'modal-box ui-confirm-box';
            const cancelHtml = cancelLabel ? '<button type="button" class="ui-confirm-btn ui-confirm-cancel"></button>' : '';
            box.innerHTML =
                '<div class="ui-confirm-head">' +
                    '<h3 class="ui-confirm-title"></h3>' +
                    (text ? '<p class="ui-confirm-text"></p>' : '') +
                '</div>' +
                '<div class="ui-confirm-actions">' + cancelHtml +
                    '<button type="button" class="ui-confirm-btn ui-confirm-ok' + (danger ? ' danger' : '') + '"></button>' +
                '</div>';
            box.querySelector('.ui-confirm-title').textContent = title;
            if (text) box.querySelector('.ui-confirm-text').textContent = text;
            box.querySelector('.ui-confirm-ok').textContent = okLabel;
            if (cancelLabel) box.querySelector('.ui-confirm-cancel').textContent = cancelLabel;

            overlay.appendChild(box);
            document.body.appendChild(overlay);
            const prevOverflow = document.body.style.overflow;
            document.body.style.overflow = 'hidden';

            const close = (result) => {
                overlay.classList.remove('show');
                document.removeEventListener('keydown', onKey);
                setTimeout(() => {
                    overlay.remove();
                    document.body.style.overflow = prevOverflow;
                    resolve(result);
                }, 180);
            };
            const onKey = (e) => {
                if (e.key === 'Escape' && cancelLabel !== null) close(false);
                else if (e.key === 'Enter') close(true);
            };
            document.addEventListener('keydown', onKey);

            box.querySelector('.ui-confirm-ok').addEventListener('click', () => close(true));
            const cancelBtn = box.querySelector('.ui-confirm-cancel');
            if (cancelBtn) cancelBtn.addEventListener('click', () => close(false));
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay && cancelLabel !== null) close(false);
            });
            requestAnimationFrame(() => {
                overlay.classList.add('show');
                box.querySelector('.ui-confirm-ok').focus();
            });
        });
    }

    window.Confirm = {
        ask:   (opts) => openConfirm(opts || {}),
        alert: (opts) => openConfirm({ ...(opts || {}), cancel: null }),
    };
})();
