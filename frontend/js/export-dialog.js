/* export-dialog.js — v1.60.0
 * Der Gesamt-Export als zusammenstellbarer Dialog.
 *
 * Bis v1.59.x gab es zwei Entscheidungen: Zeitraum und eine Aggregation für
 * die ganze Datei. Alles andere war fest — jeder Export enthielt jedes Modul,
 * und man sah erst nach dem Herunterladen, was drin gelandet war. Jetzt:
 *
 *   - Sektionen einzeln an- und abwählbar, gruppiert nach Modul.
 *   - Aggregation je Modul (Ausgaben monatsweise, Gesundheit einzeln).
 *   - Eine Vorschau, die den Export wirklich baut: Zeilen je Sektion, Größe
 *     der Datei und die ersten Zeilen im Original.
 *
 * Die Sektionsliste kommt vom Server (/api/export/sections) — sie hier ein
 * zweites Mal zu führen hieße, sie irgendwann falsch zu führen.
 */
(function () {
    const PRESETS = [
        { key: 'all', label: 'Alles' },
        { key: '30',  label: '30 Tage' },
        { key: '90',  label: '3 Monate' },
        { key: '365', label: '12 Monate' },
        { key: 'ytd', label: 'Dieses Jahr' },
        { key: 'custom', label: 'Eigener Zeitraum' },
    ];
    const AGGS = [
        { key: 'none',  label: 'Einzeln' },
        { key: 'week',  label: 'Pro Woche' },
        { key: 'month', label: 'Pro Monat' },
    ];
    const AGG_HINT = {
        none:  'Jeder Eintrag steht einzeln in der Datei.',
        week:  'Je Woche eine Summenzeile; Einkäufe bleiben einzeln, aber ohne Positionen.',
        month: 'Je Monat eine Summenzeile. Für lange Zeiträume die kompakteste Form.',
    };

    const iso = (d) => {
        const p = (n) => String(n).padStart(2, '0');
        return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
    };
    const isoToday = () => iso(new Date());
    const isoDaysAgo = (n) => iso(new Date(Date.now() - n * 86400000));
    const isoYearStart = () => new Date().getFullYear() + '-01-01';
    const esc = (v) => String(v == null ? '' : v)
        .replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

    function fmtBytes(n) {
        const v = Number(n) || 0;
        if (v < 1024) return v + ' B';
        if (v < 1024 * 1024) return (v / 1024).toFixed(1).replace('.', ',') + ' kB';
        return (v / 1048576).toFixed(1).replace('.', ',') + ' MB';
    }

    /* ------------------------------------------------------------- Zustand */
    function newState(sections) {
        return {
            preset: 'all',
            from: '',
            to: '',
            picked: new Set(sections.map(s => s.key)),
            agg: { sparziel: 'none', ausgaben: 'none', health: 'none' },
            sections: sections,
            groups: [],
        };
    }

    function rangeOf(state) {
        if (state.preset === 'all') return { from: '', to: '' };
        if (state.preset === 'custom') return { from: state.from || '', to: state.to || '' };
        if (state.preset === 'ytd') return { from: isoYearStart(), to: isoToday() };
        return { from: isoDaysAgo(parseInt(state.preset, 10)), to: isoToday() };
    }

    function queryOf(state) {
        const p = new URLSearchParams();
        const r = rangeOf(state);
        if (r.from) p.set('from', r.from);
        if (r.to) p.set('to', r.to);
        // Nur mitschicken, was nicht ohnehin alles ist -- ein Export ohne
        // sections-Parameter ist der alte Aufruf und heisst "alles".
        if (state.picked.size < state.sections.length) {
            p.set('sections', state.sections.filter(s => state.picked.has(s.key))
                .map(s => s.key).join(','));
        }
        Object.keys(state.agg).forEach(g => {
            if (state.agg[g] !== 'none') p.set('agg_' + g, state.agg[g]);
        });
        return p;
    }

    /* -------------------------------------------------------------- Aufbau */
    function dialogHtml() {
        return [
            '<div class="modal-box exp-dialog">',
            '  <div class="modal-head">',
            '    <h3>Gesamt-Export</h3>',
            '    <button class="modal-close" data-act="close" type="button" aria-label="Schließen">✕</button>',
            '  </div>',
            '  <div class="modal-body exp-body">',
            '    <div class="exp-cols">',
            '      <div class="exp-col">',
            '        <div class="exp-label">Zeitraum</div>',
            '        <div class="exp-chip-row" id="expRange">',
                     PRESETS.map(p => '<button type="button" data-preset="' + p.key + '">' +
                        p.label + '</button>').join(''),
            '        </div>',
            '        <div id="expCustom" class="exp-custom">',
            '          <label>Von<input type="date" id="expFrom"></label>',
            '          <label>Bis<input type="date" id="expTo"></label>',
            '        </div>',
            '        <div class="exp-label" style="margin-top:1.15rem">Was soll hinein?</div>',
            '        <div id="expSections" class="exp-sections"><span class="skel skel-block"></span></div>',
            '      </div>',
            '      <div class="exp-col exp-col-preview">',
            '        <div class="exp-label">Vorschau</div>',
            '        <div id="expSummary" class="exp-summary"></div>',
            '        <div id="expTable" class="exp-preview-table"></div>',
            '        <div class="exp-label" style="margin-top:1rem">Erste Zeilen</div>',
            '        <pre id="expSample" class="exp-sample"></pre>',
            '      </div>',
            '    </div>',
            '  </div>',
            '  <div class="ui-confirm-actions">',
            '    <button type="button" class="ui-confirm-btn" data-act="close">Abbrechen</button>',
            '    <button type="button" class="ui-confirm-btn ui-confirm-ok" id="expGo">Exportieren</button>',
            '  </div>',
            '</div>',
        ].join('');
    }

    function renderSections(box, state) {
        const byGroup = new Map();
        state.sections.forEach(s => {
            if (!byGroup.has(s.group)) byGroup.set(s.group, []);
            byGroup.get(s.group).push(s);
        });
        box.innerHTML = state.groups.map(g => {
            const items = byGroup.get(g.key) || [];
            if (!items.length) return '';
            const allOn = items.every(s => state.picked.has(s.key));
            const someOn = items.some(s => state.picked.has(s.key));
            // Die Aggregation gehoert zur Gruppe, nicht zur Sektion: sie
            // betrifft immer alle Zeitreihen eines Moduls gemeinsam.
            const canAgg = items.some(s => s.aggregatable && state.picked.has(s.key));
            return '<div class="exp-group' + (someOn ? '' : ' is-off') + '">' +
                '<div class="exp-group-head">' +
                    '<label class="exp-check exp-check-all">' +
                        '<input type="checkbox" data-group="' + g.key + '"' +
                            (allOn ? ' checked' : '') + (someOn && !allOn ? ' data-partial="1"' : '') + '>' +
                        '<span>' + esc(g.label) + '</span>' +
                    '</label>' +
                    '<select class="exp-agg" data-agg-group="' + g.key + '"' + (canAgg ? '' : ' disabled') + '>' +
                        AGGS.map(a => '<option value="' + a.key + '"' +
                            (state.agg[g.key] === a.key ? ' selected' : '') + '>' + a.label + '</option>').join('') +
                    '</select>' +
                '</div>' +
                '<div class="exp-group-body">' +
                    items.map(s => '<label class="exp-check">' +
                        '<input type="checkbox" data-section="' + s.key + '"' +
                            (state.picked.has(s.key) ? ' checked' : '') + '>' +
                        '<span>' + esc(s.label) + '</span>' +
                        (s.aggregatable ? '' : '<em class="exp-tag">Stammdaten</em>') +
                    '</label>').join('') +
                '</div>' +
                (canAgg ? '<p class="exp-hint">' + esc(AGG_HINT[state.agg[g.key]]) + '</p>' : '') +
            '</div>';
        }).join('');
        // Teilweise gewaehlte Gruppen bekommen den Zwischenzustand -- als
        // Attribut geht das nicht, das kennt nur die Eigenschaft.
        box.querySelectorAll('input[data-partial]').forEach(el => { el.indeterminate = true; });
    }

    function renderPreview(overlay, data) {
        const sum = overlay.querySelector('#expSummary');
        const table = overlay.querySelector('#expTable');
        const sample = overlay.querySelector('#expSample');
        if (!data) {
            sum.innerHTML = '<span class="skel" style="display:block;width:8rem;height:1.25rem"></span>';
            table.innerHTML = '';
            sample.textContent = '';
            return;
        }
        if (data.error) {
            sum.innerHTML = '<span class="exp-warn">Vorschau nicht möglich: ' + esc(data.error) + '</span>';
            table.innerHTML = '';
            sample.textContent = '';
            return;
        }
        sum.innerHTML = '<strong>' + data.total_rows.toLocaleString('de-DE') + '</strong> Datenzeilen · ' +
            '<strong>' + fmtBytes(data.bytes) + '</strong> als CSV';
        const max = Math.max(1, ...data.sections.map(s => s.rows));
        table.innerHTML = data.sections.map(s =>
            '<div class="exp-prow' + (s.rows ? '' : ' is-empty') + '">' +
                '<span class="exp-pname">' + esc(s.label) + '</span>' +
                '<span class="exp-pbar"><i style="width:' +
                    Math.round(s.rows / max * 100) + '%"></i></span>' +
                '<span class="exp-pnum">' + s.rows.toLocaleString('de-DE') + '</span>' +
            '</div>').join('') || '<div class="exp-hint">Keine Sektion gewählt.</div>';
        sample.textContent = data.sample + (data.truncated ? '\n…' : '');
    }

    async function doExport(state) {
        const qs = queryOf(state).toString();
        if (window.Toast) Toast.info('Export wird erstellt…', { timeout: 2000 });
        try {
            const res = await apiCall('/api/export/all' + (qs ? '?' + qs : ''), { raw: true });
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
            if (window.Toast) Toast.success('Export heruntergeladen: ' + filename);
        } catch (e) {
            const msg = 'Export fehlgeschlagen: ' + (e && e.message ? e.message : e);
            if (window.Toast) Toast.error(msg); else alert(msg);
        }
    }

    function wire(overlay, state) {
        const sectionBox = overlay.querySelector('#expSections');
        const fromEl = overlay.querySelector('#expFrom');
        const toEl = overlay.querySelector('#expTo');
        let previewTimer = null;
        let previewSeq = 0;

        function refreshPreview() {
            clearTimeout(previewTimer);
            // Ohne Sektion waere die Anfrage sinnlos: der Server versteht eine
            // leere Auswahl als "alles" und zeigte dann etwas anderes an, als
            // hier angehakt ist.
            if (!state.picked.size) {
                renderPreview(overlay, { sections: [], total_rows: 0, bytes: 0, sample: '' });
                return;
            }
            renderPreview(overlay, null);
            // Die Vorschau baut serverseitig den echten Export -- deshalb erst
            // kurz warten, statt bei jedem Haken eine Anfrage zu schicken.
            previewTimer = setTimeout(async () => {
                const seq = ++previewSeq;
                const qs = queryOf(state).toString();
                try {
                    const data = await apiCall('/api/export/preview' + (qs ? '?' + qs : ''));
                    if (seq !== previewSeq) return;   // eine neuere Anfrage laeuft
                    renderPreview(overlay, data);
                } catch (e) {
                    if (seq !== previewSeq) return;
                    renderPreview(overlay, { error: e.message || String(e) });
                }
            }, 400);
        }

        function paintRange() {
            overlay.querySelectorAll('#expRange button').forEach(b => {
                b.classList.toggle('active', b.dataset.preset === state.preset);
            });
            overlay.querySelector('#expCustom').style.display =
                state.preset === 'custom' ? 'flex' : 'none';
        }

        overlay.querySelector('#expRange').addEventListener('click', (e) => {
            const b = e.target.closest('button');
            if (!b) return;
            state.preset = b.dataset.preset;
            paintRange();
            if (state.preset !== 'custom' || (state.from || state.to)) refreshPreview();
        });
        [fromEl, toEl].forEach(el => el.addEventListener('change', () => {
            state.from = fromEl.value;
            state.to = toEl.value;
            if (state.from && state.to && state.from > state.to) {
                if (window.Toast) Toast.error('„Von" liegt nach „Bis"');
                return;
            }
            refreshPreview();
        }));

        sectionBox.addEventListener('change', (e) => {
            const el = e.target;
            // Das Auswahlfeld zuerst: es trug frueher dasselbe data-group wie
            // die Gruppen-Checkbox, landete in deren Zweig und hakte mit
            // el.checked === undefined die ganze Gruppe ab.
            if (el.dataset.aggGroup) {
                state.agg[el.dataset.aggGroup] = el.value;
                // Nur der Hinweistext darunter aendert sich. Die ganze Liste
                // neu zu zeichnen naehme dem Auswahlfeld mitten im Bedienen
                // den Fokus.
                const group = el.closest('.exp-group');
                const hint = group ? group.querySelector('.exp-hint') : null;
                if (hint) hint.textContent = AGG_HINT[el.value] || '';
                refreshPreview();
                return;
            }
            if (el.dataset.section) {
                el.checked ? state.picked.add(el.dataset.section)
                           : state.picked.delete(el.dataset.section);
            } else if (el.dataset.group) {
                const keys = state.sections.filter(s => s.group === el.dataset.group).map(s => s.key);
                keys.forEach(k => el.checked ? state.picked.add(k) : state.picked.delete(k));
            } else return;
            renderSections(sectionBox, state);
            refreshPreview();
        });

        const close = () => {
            clearTimeout(previewTimer);
            previewSeq++;
            overlay.classList.remove('show');
            document.removeEventListener('keydown', onKey);
            setTimeout(() => overlay.remove(), 180);
        };
        const onKey = (e) => { if (e.key === 'Escape') close(); };
        document.addEventListener('keydown', onKey);
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) return close();
            const act = e.target.closest('[data-act="close"]');
            if (act) close();
        });

        overlay.querySelector('#expGo').onclick = async () => {
            if (!state.picked.size) {
                if (window.Toast) Toast.error('Ohne Sektion gäbe es nichts zu exportieren');
                return;
            }
            const r = rangeOf(state);
            if (r.from && r.to && r.from > r.to) {
                if (window.Toast) Toast.error('„Von" liegt nach „Bis"');
                return;
            }
            close();
            await doExport(state);
        };

        paintRange();
        return { refreshPreview };
    }

    window.exportAll = async function exportAll() {
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.innerHTML = dialogHtml();
        document.body.appendChild(overlay);
        requestAnimationFrame(() => overlay.classList.add('show'));

        let meta;
        try {
            meta = await apiCall('/api/export/sections');
        } catch (e) {
            overlay.querySelector('#expSections').innerHTML =
                '<div class="empty is-error"><span class="empty-mark">⚠️</span>' +
                '<p class="empty-text">Die Sektionsliste konnte nicht geladen werden. ' +
                'Ohne sie lässt sich nichts zusammenstellen.</p></div>';
            return;
        }
        const state = newState(meta.sections || []);
        state.groups = meta.groups || [];
        renderSections(overlay.querySelector('#expSections'), state);
        wire(overlay, state).refreshPreview();
    };
})();
