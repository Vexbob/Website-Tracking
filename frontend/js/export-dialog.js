/* export-dialog.js — v1.37.1
 * Export-Dialog fuer /api/export/all mit Zeitraum-Presets und
 * Wochen-/Monats-Aggregation. Setzt window.exportAll().
 */
(function () {
    function isoDaysAgo(days) {
        const d = new Date(); d.setDate(d.getDate() - days);
        return d.toISOString().slice(0, 10);
    }
    function isoToday() { return new Date().toISOString().slice(0, 10); }
    function isoYearStart() { return new Date().getFullYear() + '-01-01'; }

    function buildOverlay() {
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.innerHTML = [
            '<div class="modal-box exp-dialog">',
            '  <div class="modal-head">',
            '    <h3>Gesamt-Export</h3>',
            '    <button class="modal-close" id="expClose" type="button" aria-label="Schliessen">✕</button>',
            '  </div>',
            '  <div class="modal-body exp-body">',
            '    <div>',
            '      <div class="exp-label">Zeitraum</div>',
            '      <div class="exp-chip-row" id="expRange">',
            '        <button type="button" data-preset="all" class="active">Alles</button>',
            '        <button type="button" data-preset="30">Letzte 30 Tage</button>',
            '        <button type="button" data-preset="90">Letzte 3 Monate</button>',
            '        <button type="button" data-preset="365">Letzte 12 Monate</button>',
            '        <button type="button" data-preset="ytd">Dieses Jahr</button>',
            '        <button type="button" data-preset="custom">Benutzerdefiniert</button>',
            '      </div>',
            '      <div id="expCustom" class="exp-custom">',
            '        <label>Von<input type="date" id="expFrom"></label>',
            '        <label>Bis<input type="date" id="expTo"></label>',
            '      </div>',
            '    </div>',
            '    <div>',
            '      <div class="exp-label">Aggregation</div>',
            '      <div class="exp-chip-row" id="expAgg">',
            '        <button type="button" data-agg="none" class="active">Alle Einzel-Eintraege</button>',
            '        <button type="button" data-agg="week">Wochenweise</button>',
            '        <button type="button" data-agg="month">Monatsweise</button>',
            '      </div>',
            '      <div class="exp-hint" id="expHint">Ausgaben und Vitalwerte werden nicht zusammengefasst.</div>',
            '    </div>',
            '  </div>',
            '  <div class="ui-confirm-actions">',
            '    <button type="button" class="ui-confirm-btn" id="expCancel">Abbrechen</button>',
            '    <button type="button" class="ui-confirm-btn ui-confirm-ok" id="expGo">Exportieren</button>',
            '  </div>',
            '</div>'
        ].join('');
        return overlay;
    }
    async function doExport(from, to, agg) {
        const params = new URLSearchParams();
        if (from) params.set('from', from);
        if (to) params.set('to', to);
        if (agg !== 'none') params.set('aggregate', agg);
        const qs = params.toString() ? ('?' + params.toString()) : '';
        const toastApi = window.Toast;
        if (toastApi) toastApi.info('Export wird erstellt…', { timeout: 2000 });
        try {
            const res = await apiCall('/api/export/all' + qs, { raw: true });
            if (!res || !res.ok) throw new Error('HTTP ' + (res && res.status));
            const blob = await res.blob();
            let filename = 'vexbob-gesamt-export.csv';
            const cd = res.headers.get('content-disposition') || '';
            const m = cd.match(/filename="?([^";]+)"?/i);
            if (m) filename = m[1];
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = filename;
            document.body.appendChild(a); a.click(); a.remove();
            URL.revokeObjectURL(url);
            if (toastApi) toastApi.success('Export heruntergeladen: ' + filename);
        } catch (e) {
            const msg = 'Export fehlgeschlagen: ' + (e && e.message ? e.message : e);
            if (window.Toast) window.Toast.error(msg); else alert(msg);
        }
    }

    function wireDialog(overlay) {
        const state = { preset: 'all', agg: 'none' };
        const setActive = (rowId, key, attr) => {
            overlay.querySelectorAll('#' + rowId + ' button').forEach(b => {
                b.classList.toggle('active', b.dataset[attr] === key);
            });
        };
        const updateHint = () => {
            const el = overlay.querySelector('#expHint');
            if (state.agg === 'week') el.textContent = 'Ausgaben werden pro Woche summiert (Anzahl Bons, Summe, Durchschnitt). Vitalwerte als Wochendurchschnitt inkl. min/max.';
            else if (state.agg === 'month') el.textContent = 'Ausgaben werden pro Monat summiert. Vitalwerte als Monatsdurchschnitt inkl. min/max. Ideal fuer lange Zeitraeume.';
            else el.textContent = 'Ausgaben und Vitalwerte werden nicht zusammengefasst.';
        };
        overlay.querySelector('#expRange').addEventListener('click', (e) => {
            const b = e.target.closest('button'); if (!b) return;
            state.preset = b.dataset.preset;
            setActive('expRange', state.preset, 'preset');
            overlay.querySelector('#expCustom').style.display = state.preset === 'custom' ? 'flex' : 'none';
        });
        overlay.querySelector('#expAgg').addEventListener('click', (e) => {
            const b = e.target.closest('button'); if (!b) return;
            state.agg = b.dataset.agg;
            setActive('expAgg', state.agg, 'agg');
            updateHint();
        });

        const close = () => {
            overlay.classList.remove('show');
            setTimeout(() => overlay.remove(), 180);
        };
        overlay.querySelector('#expClose').onclick = close;
        overlay.querySelector('#expCancel').onclick = close;
        overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });

        overlay.querySelector('#expGo').onclick = async () => {
            let from = '', to = '';
            if (state.preset === '30') from = isoDaysAgo(30);
            else if (state.preset === '90') from = isoDaysAgo(90);
            else if (state.preset === '365') from = isoDaysAgo(365);
            else if (state.preset === 'ytd') from = isoYearStart();
            else if (state.preset === 'custom') {
                from = overlay.querySelector('#expFrom').value || '';
                to = overlay.querySelector('#expTo').value || '';
                if (from && to && from > to) {
                    if (window.Toast) window.Toast.error('"Von" liegt nach "Bis"');
                    else alert('"Von" liegt nach "Bis"');
                    return;
                }
            }
            if (state.preset !== 'all' && state.preset !== 'custom') to = isoToday();
            close();
            await doExport(from, to, state.agg);
        };
    }

    window.exportAll = function exportAll() {
        const overlay = buildOverlay();
        document.body.appendChild(overlay);
        requestAnimationFrame(() => overlay.classList.add('show'));
        wireDialog(overlay);
    };
})();
