/* export-dialog.js — v1.67.0
 * Der Gesamt-Export als zusammenstellbarer Dialog.
 *
 * Bis v1.59.x gab es zwei Entscheidungen: Zeitraum und eine Aggregation für
 * die ganze Datei. Alles andere war fest — jeder Export enthielt jedes Modul,
 * und man sah erst nach dem Herunterladen, was drin gelandet war. Seit
 * v1.60.0 sind Sektionen einzeln wählbar und die Aggregation gilt je Modul.
 *
 * v1.67.0 nimmt die letzten beiden festen Listen heraus:
 *
 *   - **Die Aggregationsstufen kommen vom Server** (/api/export/sections).
 *     Sie standen hier ein zweites Mal, also war eine neue Stufe zwei
 *     Änderungen an zwei Orten. Neu dabei: Tag, Jahr und „Automatisch",
 *     das sich nach der Länge des Zeitraums richtet.
 *   - **Eine Höchstgröße stellt sich selbst ein** (v1.68.0): man sagt, wie
 *     groß die Datei höchstens werden darf, und der Server sucht die feinste
 *     Aggregation, die darunter bleibt. Gedreht wird dabei nur an der Zeit —
 *     Sektionen und Spalten bleiben, wie sie gewählt sind. Was entschieden
 *     wurde, landet sichtbar in den Auswahlfeldern, nicht in einer Blackbox.
 *   - **Die Spalten sind je Sektion wählbar.** Welche es gibt, sagt die
 *     Vorschau — sie baut den Export ohnehin und liest die Überschriften aus
 *     den fertigen Zeilen. Eine hier gepflegte Spaltenliste wäre spätestens
 *     bei der nächsten Änderung an einer Sektion falsch, und in der
 *     Aggregation hat dieselbe Sektion ohnehin andere Spalten.
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

    /* Höchstgrößen als Stufen, die man wirklich meint: eine Mail-Anlage, ein
       Tabellenblatt, ein Archiv. „Aus" steht bewusst zuerst — der Normalfall
       ist, dass die Größe egal ist. */
    const LIMITS = [
        { key: 0,        label: 'Aus' },
        { key: 1048576,  label: '1 MB' },
        { key: 5242880,  label: '5 MB' },
        { key: 10485760, label: '10 MB' },
        { key: 26214400, label: '25 MB' },
        { key: -1,       label: 'Eigene' },
    ];

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
    function newState(meta) {
        const sections = meta.sections || [];
        const groups = meta.groups || [];
        const aggregates = meta.aggregates ||
            [{ key: 'none', label: 'Einzeln', hint: '' }];
        const agg = {};
        groups.forEach(g => { agg[g.key] = 'none'; });
        return {
            preset: 'all',
            from: '',
            to: '',
            picked: new Set(sections.map(s => s.key)),
            agg: agg,
            sections: sections,
            groups: groups,
            aggregates: aggregates,
            // Was die Vorschau an Spalten gemeldet hat, und was davon gewählt
            // ist. `chosen[key] === undefined` heisst "alle" -- so bleibt die
            // Anfrage ohne cols_-Parameter, solange nichts abgewählt wurde.
            columns: {},
            chosen: {},
            openCols: new Set(),
            resolved: {},
            // Höchstgröße in Byte; 0 heißt „egal". `limitPick` ist nur der
            // gewählte Knopf, damit „Eigene" auch bei gleichem Wert aktiv bleibt.
            limit: 0,
            limitPick: 0,
            limitMb: '',
            fitNote: '',
            fitting: false,
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
        Object.keys(state.chosen).forEach(key => {
            const all = state.columns[key] || [];
            const pickedCols = state.chosen[key];
            if (!pickedCols || !pickedCols.size) return;
            if (pickedCols.size >= all.length) return;   // alles = kein Parameter
            p.set('cols_' + key, all.filter(c => pickedCols.has(c)).join(','));
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
            '        <div class="exp-label" style="margin-top:1.15rem">Höchstgröße</div>',
            '        <div class="exp-chip-row" id="expLimit">',
                     LIMITS.map(l => '<button type="button" data-limit="' + l.key + '">' +
                        l.label + '</button>').join(''),
            '        </div>',
            '        <div id="expLimitCustom" class="exp-custom">',
            '          <label>Megabyte<input type="number" id="expLimitMb" min="1" step="1" placeholder="z. B. 8"></label>',
            '          <button type="button" class="v-btn v-btn--sm" id="expLimitApply">Anpassen</button>',
            '        </div>',
            '        <p class="exp-hint" id="expLimitNote"></p>',
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

    /* Der Hinweis unter einer Gruppe. Bei „Automatisch" nennt er die Stufe,
       auf die es hinausläuft — sonst wäre die Einstellung eine Blackbox. */
    function aggHint(state, groupKey) {
        const key = state.agg[groupKey];
        const entry = state.aggregates.find(a => a.key === key);
        let text = entry ? entry.hint || '' : '';
        const real = state.resolved[groupKey];
        if (key === 'auto' && real && real !== 'auto') {
            const named = state.aggregates.find(a => a.key === real);
            text += ' Für diesen Zeitraum: ' + (named ? named.label.toLowerCase() : real) + '.';
        }
        return text;
    }

    function columnsHtml(state, section) {
        const all = state.columns[section.key];
        if (!all || !all.length || !state.picked.has(section.key)) return '';
        const chosen = state.chosen[section.key];
        const count = chosen ? chosen.size : all.length;
        const open = state.openCols.has(section.key);
        return '<div class="exp-colpick' + (open ? ' is-open' : '') + '">' +
            '<button type="button" class="exp-colpick-btn" data-cols-toggle="' + section.key + '"' +
                    ' aria-expanded="' + open + '">' +
                (count >= all.length ? 'Alle ' + all.length + ' Spalten'
                                     : count + ' von ' + all.length + ' Spalten') +
                '<span class="exp-colpick-caret" aria-hidden="true">' + (open ? '▴' : '▾') + '</span>' +
            '</button>' +
            (open ? '<div class="exp-colpick-list">' + all.map(name =>
                '<label class="exp-check exp-check-col">' +
                    '<input type="checkbox" data-col-section="' + esc(section.key) + '"' +
                        ' data-col="' + esc(name) + '"' +
                        (!chosen || chosen.has(name) ? ' checked' : '') + '>' +
                    '<span>' + esc(name) + '</span>' +
                '</label>').join('') + '</div>' : '') +
        '</div>';
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
                        state.aggregates.map(a => '<option value="' + a.key + '"' +
                            (state.agg[g.key] === a.key ? ' selected' : '') + '>' +
                            esc(a.label) + '</option>').join('') +
                    '</select>' +
                '</div>' +
                '<div class="exp-group-body">' +
                    items.map(s => '<div class="exp-item">' +
                        '<label class="exp-check">' +
                            '<input type="checkbox" data-section="' + s.key + '"' +
                                (state.picked.has(s.key) ? ' checked' : '') + '>' +
                            '<span>' + esc(s.label) + '</span>' +
                            (s.aggregatable ? '' : '<em class="exp-tag">Stammdaten</em>') +
                        '</label>' +
                        columnsHtml(state, s) +
                    '</div>').join('') +
                '</div>' +
                (canAgg ? '<p class="exp-hint">' + esc(aggHint(state, g.key)) + '</p>' : '') +
            '</div>';
        }).join('');
        // Teilweise gewaehlte Gruppen bekommen den Zwischenzustand -- als
        // Attribut geht das nicht, das kennt nur die Eigenschaft.
        box.querySelectorAll('input[data-partial]').forEach(el => { el.indeterminate = true; });
    }

    function renderPreview(overlay, data, state) {
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
        // Ist eine Grenze gesetzt, steht der Stand DARAN -- eine nackte
        // Zahl beantwortet die Frage "passt das noch?" nicht.
        var against = '';
        if (state && state.limit > 0) {
            var over = data.bytes > state.limit;
            against = ' <span class="' + (over ? 'exp-warn' : 'exp-ok') + '">' +
                (over ? 'über' : 'von') + ' ' + fmtBytes(state.limit) + '</span>';
        }
        sum.innerHTML = '<strong>' + data.total_rows.toLocaleString('de-DE') + '</strong> Datenzeilen · ' +
            '<strong>' + fmtBytes(data.bytes) + '</strong> als CSV' + against;
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

        /* Was die Vorschau über den Aufbau der Datei verrät, fließt zurück in
           die Auswahl links: die Spaltenlisten und die Stufe, auf die
           „Automatisch" hinausläuft. */
        function absorb(data) {
            let changed = false;
            (data.sections || []).forEach(s => {
                const before = (state.columns[s.key] || []).join(' ');
                const now = (s.columns || []).join(' ');
                if (before !== now) {
                    state.columns[s.key] = s.columns || [];
                    // Eine Auswahl, die es in der neuen Spaltenliste nicht mehr
                    // gibt (andere Aggregation), gilt nicht weiter.
                    if (state.chosen[s.key]) {
                        const kept = new Set(
                            (s.columns || []).filter(c => state.chosen[s.key].has(c)));
                        if (kept.size) state.chosen[s.key] = kept;
                        else delete state.chosen[s.key];
                    }
                    changed = true;
                }
            });
            const resolved = data.aggregate || {};
            Object.keys(resolved).forEach(g => {
                if (state.resolved[g] !== resolved[g]) {
                    state.resolved[g] = resolved[g];
                    if (state.agg[g] === 'auto') changed = true;
                }
            });
            if (changed) renderSections(sectionBox, state);
        }

        const limitNote = overlay.querySelector('#expLimitNote');
        const limitMbEl = overlay.querySelector('#expLimitMb');

        function paintLimit() {
            overlay.querySelectorAll('#expLimit button').forEach(b => {
                b.classList.toggle('active', Number(b.dataset.limit) === state.limitPick);
                b.disabled = state.fitting;
            });
            overlay.querySelector('#expLimitCustom').style.display =
                state.limitPick === -1 ? 'flex' : 'none';
            if (state.fitting) {
                // Laden heißt Skeleton, nicht „Lade …" als Fließtext.
                limitNote.innerHTML = '<span class="skel" style="display:inline-block;width:14rem;height:0.85rem"></span>';
            } else {
                limitNote.textContent = state.fitNote || '';
            }
        }

        /* Der Server sucht die feinste Aggregation, die unter die Grenze
           passt, und liefert die fertige Vorschau gleich mit. Was er
           entschieden hat, landet in den Auswahlfeldern links — sonst wäre
           die Einstellung eine Blackbox. */
        async function fitToLimit() {
            if (!state.limit || !state.picked.size) return;
            state.fitting = true;
            paintLimit();
            renderPreview(overlay, null, state);
            const seq = ++previewSeq;
            const p = queryOf(state);
            p.set('max_bytes', state.limit);
            try {
                const data = await apiCall('/api/export/fit?' + p.toString());
                if (seq !== previewSeq) return;
                Object.keys(data.aggregate || {}).forEach(g => {
                    if (g in state.agg) state.agg[g] = data.aggregate[g];
                });
                state.fitNote = (data.fits ? 'Passt: ' + fmtBytes(data.bytes) + '. ' : '')
                    + (data.note || '');
                if (!data.fits && data.largest_section) {
                    state.fitNote += ' Am schwersten wiegt „' + data.largest_section.label
                        + '" mit ' + fmtBytes(data.largest_section.bytes) + '.';
                }
                state.fitting = false;
                renderSections(sectionBox, state);
                if (data.preview) {
                    renderPreview(overlay, data.preview, state);
                    absorb(data.preview);
                } else {
                    refreshPreview();
                }
                paintLimit();
            } catch (e) {
                if (seq !== previewSeq) return;
                state.fitting = false;
                state.fitNote = 'Konnte nicht eingestellt werden: ' + (e.message || e);
                paintLimit();
                refreshPreview();
            }
        }

        function refreshPreview() {
            clearTimeout(previewTimer);
            // Ohne Sektion waere die Anfrage sinnlos: der Server versteht eine
            // leere Auswahl als "alles" und zeigte dann etwas anderes an, als
            // hier angehakt ist.
            if (!state.picked.size) {
                renderPreview(overlay, { sections: [], total_rows: 0, bytes: 0, sample: '' }, state);
                return;
            }
            renderPreview(overlay, null, state);
            // Die Vorschau baut serverseitig den echten Export -- deshalb erst
            // kurz warten, statt bei jedem Haken eine Anfrage zu schicken.
            previewTimer = setTimeout(async () => {
                const seq = ++previewSeq;
                const qs = queryOf(state).toString();
                try {
                    const data = await apiCall('/api/export/preview' + (qs ? '?' + qs : ''));
                    if (seq !== previewSeq) return;   // eine neuere Anfrage laeuft
                    renderPreview(overlay, data, state);
                    absorb(data);
                } catch (e) {
                    if (seq !== previewSeq) return;
                    renderPreview(overlay, { error: e.message || String(e) }, state);
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

        overlay.querySelector('#expLimit').addEventListener('click', (e) => {
            const b = e.target.closest('button');
            if (!b || state.fitting) return;
            const value = Number(b.dataset.limit);
            state.limitPick = value;
            if (value === -1) {
                // „Eigene" öffnet nur das Feld -- gerechnet wird erst auf
                // „Anpassen", sonst liefe die Suche bei jeder getippten Ziffer.
                paintLimit();
                limitMbEl.focus();
                return;
            }
            state.limit = value;
            state.fitNote = '';
            paintLimit();
            if (value > 0) fitToLimit(); else refreshPreview();
        });

        overlay.querySelector('#expLimitApply').addEventListener('click', () => {
            const mb = parseFloat(limitMbEl.value);
            if (!mb || mb <= 0) {
                if (window.Toast) Toast.error('Bitte eine Größe in Megabyte angeben');
                return;
            }
            state.limit = Math.round(mb * 1048576);
            state.fitNote = '';
            fitToLimit();
        });

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

        // Die Spaltenliste auf- und zuklappen aendert nichts an der Datei --
        // deshalb nur neu zeichnen, keine neue Vorschau.
        sectionBox.addEventListener('click', (e) => {
            const b = e.target.closest('[data-cols-toggle]');
            if (!b) return;
            const key = b.dataset.colsToggle;
            state.openCols.has(key) ? state.openCols.delete(key) : state.openCols.add(key);
            renderSections(sectionBox, state);
        });

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
                if (hint) hint.textContent = aggHint(state, el.dataset.aggGroup);
                refreshPreview();
                return;
            }
            if (el.dataset.colSection) {
                const key = el.dataset.colSection;
                const all = state.columns[key] || [];
                const set = state.chosen[key] || new Set(all);
                el.checked ? set.add(el.dataset.col) : set.delete(el.dataset.col);
                // Nichts mehr gewaehlt heisst hier "alles" -- eine Sektion
                // ohne Spalten waere eine kaputte Datei, und wer nichts von
                // ihr will, haekelt die Sektion selbst ab.
                if (!set.size || set.size >= all.length) delete state.chosen[key];
                else state.chosen[key] = set;
                renderSections(sectionBox, state);
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
        paintLimit();
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
        const state = newState(meta);
        renderSections(overlay.querySelector('#expSections'), state);
        wire(overlay, state).refreshPreview();
    };
})();
