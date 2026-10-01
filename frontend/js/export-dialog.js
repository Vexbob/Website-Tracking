/* export-dialog.js — v2.31.0
 * Der Gesamt-Export als zusammenstellbarer Dialog.
 *
 * Bis v1.59.x gab es zwei Entscheidungen: Zeitraum und eine Aggregation für
 * die ganze Datei. Seit v1.60.0 sind Sektionen einzeln wählbar und die
 * Aggregation gilt je Modul. v1.67.0 hat die letzten festen Listen
 * herausgenommen:
 *
 *   - **Die Aggregationsstufen kommen vom Server** (/api/export/sections).
 *   - **Eine Höchstgröße stellt sich selbst ein** (v1.68.0): der Server sucht
 *     die feinste Aggregation, die unter die Grenze passt. Gedreht wird nur an
 *     der Zeit; was entschieden wurde, landet sichtbar in den Auswahlfeldern.
 *   - **Die Spalten sind je Sektion wählbar.** Welche es gibt, sagt die
 *     Vorschau -- sie baut den Export ohnehin.
 *
 * v2.31.0 baut die Oberfläche neu, ohne etwas wegzuklappen (die Lehre aus
 * v2.10.1: Zeitraum, Module und Verdichtung will man sehen und stellen):
 *
 *   - Ein Modul ist eine Zeile mit Schalter. Darunter stehen seine Tabellen
 *     mit der Zeilenzahl aus der Vorschau -- die eigene Vorschautabelle unter
 *     der Maske nannte dieselben Namen ein zweites Mal.
 *   - Die Spaltenwahl liegt einen Griff tiefer im eigenen Dialog. Unter jeder
 *     Tabelle stand „Alle 3 Spalten“: zwanzig Zeilen für eine Frage, die sich
 *     selten stellt (DESIGN 6d).
 *   - Größe und Zeilenzahl stehen im Fuß neben „Exportieren“ und bleiben
 *     beim Scrollen stehen. Vorher kam das Ergebnis erst am Ende einer fast
 *     vier Bildschirme langen Liste.
 */
(function () {
    const PRESETS = [
        { key: 'all', label: 'Alles' },
        { key: '30',  label: '30 Tage' },
        { key: '90',  label: '3 Monate' },
        { key: '365', label: '12 Monate' },
        { key: 'ytd', label: 'Dieses Jahr' },
        { key: 'custom', label: 'Eigener' },
    ];

    /* Höchstgrößen als Stufen, die man wirklich meint: eine Mail-Anlage, ein
       Tabellenblatt, ein Archiv. „Aus“ steht bewusst zuerst — der Normalfall
       ist, dass die Größe egal ist. */
    const LIMITS = [
        { key: 0,        label: 'Aus' },
        { key: 1048576,  label: '1 MB' },
        { key: 5242880,  label: '5 MB' },
        { key: 10485760, label: '10 MB' },
        { key: 26214400, label: '25 MB' },
        { key: -1,       label: 'Eigene' },
    ];

    /* Die eine Datei ist zum Lesen und Auswerten da — mit dem Vorspann davor,
       der sagt, was drin ist. Das Archiv ist für ein Tabellenprogramm: 20
       Tabellen mit verschiedener Spaltenzahl in EINEM Blatt kann keines
       öffnen. */
    const FORMATE = [
        { key: 'csv', label: 'Eine Datei', hint: 'Alle Tabellen untereinander, zum Auswerten' },
        { key: 'zip', label: 'Archiv (ZIP)', hint: 'Eine Datei je Tabelle, für Excel und Numbers' },
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
    const zahl = (n) => (Number(n) || 0).toLocaleString('de-DE');
    const tabellen = (n) => n + (n === 1 ? ' Tabelle' : ' Tabellen');

    function fmtBytes(n) {
        const v = Number(n) || 0;
        if (v < 1024) return v + ' B';
        if (v < 1024 * 1024) return (v / 1024).toFixed(1).replace('.', ',') + ' kB';
        return (v / 1048576).toFixed(1).replace('.', ',') + ' MB';
    }

    /* „Vitalwerte (ein Tag je Zeile)“ wird Name und Erläuterung: der Name
       trägt die Zeile, die Klammer steht leiser darunter. */
    function teile(label) {
        const m = /^(.*?)\s*\((.*)\)\s*$/.exec(label || '');
        return m ? { name: m[1], mehr: m[2] } : { name: label || '', mehr: '' };
    }

    /* ------------------------------------------------------------- Zustand */
    function newState(meta) {
        const sections = meta.sections || [];
        const groups = meta.groups || [];
        const aggregates = meta.aggregates ||
            [{ key: 'none', label: 'Einzeln', hint: '' }];
        // Die Voreinstellung aus /einstellungen. Der Dialog machte bis
        // v2.8.0 jedes Mal mit „Einzeln“ auf, obwohl die Antwort auf „wie
        // haettest du es gern“ dieselbe bleibt.
        const vorgabe = (window.VexPrefs && VexPrefs.get('ui_export', null)) || {};
        const vorAgg = vorgabe.aggregate || {};
        const agg = {};
        groups.forEach(g => { agg[g.key] = vorAgg[g.key] || 'none'; });
        // Abgeschaltete Module (v2.11.0). Gespeichert ist, was AUS ist --
        // ein neues Modul ist damit von selbst dabei. Abgewählt heißt nicht
        // versteckt: die Zeile steht weiter in der Liste und lässt sich hier
        // für diesen einen Export wieder anschalten.
        const aus = new Set(vorgabe.off || []);
        const dabei = sections.filter(x => !aus.has(x.group)).map(x => x.key);
        return {
            format: 'csv',
            // Vor diesem Tag steht alles monatsweise in der Datei. Leer
            // heisst: keine Grenze.
            compactBefore: vorgabe.compact_before || '',
            preset: 'all',
            from: '',
            to: '',
            picked: new Set(dabei.length ? dabei : sections.map(x => x.key)),
            agg: agg,
            sections: sections,
            groups: groups,
            aggregates: aggregates,
            // Was die Vorschau an Spalten gemeldet hat, und was davon gewählt
            // ist. `chosen[key] === undefined` heisst "alle" -- so bleibt die
            // Anfrage ohne cols_-Parameter, solange nichts abgewählt wurde.
            columns: {},
            chosen: {},
            resolved: {},
            // Zeilen je Sektion aus der letzten Vorschau; fehlt ein Schlüssel,
            // steht noch keine Zahl da.
            zeilen: {},
            // Höchstgröße in Byte; 0 heißt „egal“. `limitPick` ist nur der
            // gewählte Knopf, damit „Eigene“ auch bei gleichem Wert aktiv bleibt.
            limit: 0,
            limitPick: 0,
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
        // Immer mitschicken, auch leer: ein fehlender Parameter hiesse „nimm
        // die Voreinstellung“, und dann zeigte die Vorschau etwas anderes an,
        // als hier eingestellt ist.
        p.set('compact_before', state.compactBefore || '');
        if (state.format === 'zip') p.set('format', 'zip');
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
    const chips = (liste, attr) => liste.map(x =>
        '<button type="button" class="v-chip" ' + attr + '="' + x.key + '" aria-pressed="false">' +
            esc(x.label) + '</button>').join('');

    function dialogHtml() {
        return '<div class="exp">' +
            '<div class="exp-einst">' +
                '<section class="exp-block">' +
                    '<h4 class="exp-label">Form</h4>' +
                    '<div class="exp-formen" id="expFormat">' + FORMATE.map(f =>
                        '<button type="button" class="exp-form" data-format="' + f.key + '" aria-pressed="false">' +
                            '<span class="exp-form-name">' + esc(f.label) + '</span>' +
                            '<span class="exp-form-hint">' + esc(f.hint) + '</span>' +
                        '</button>').join('') +
                    '</div>' +
                '</section>' +
                '<section class="exp-block">' +
                    '<h4 class="exp-label">Zeitraum</h4>' +
                    '<div class="exp-chips" id="expRange">' + chips(PRESETS, 'data-preset') + '</div>' +
                    '<div class="exp-felder" id="expCustom" hidden>' +
                        '<label class="exp-feld">Von<input type="date" id="expFrom"></label>' +
                        '<label class="exp-feld">Bis<input type="date" id="expTo"></label>' +
                    '</div>' +
                '</section>' +
                '<section class="exp-block">' +
                    '<h4 class="exp-label">Höchstgröße</h4>' +
                    '<div class="exp-chips" id="expLimit">' + chips(LIMITS, 'data-limit') + '</div>' +
                    '<div class="exp-felder" id="expLimitCustom" hidden>' +
                        '<label class="exp-feld">Megabyte<input type="number" id="expLimitMb" min="1" step="1" inputmode="decimal" placeholder="z. B. 8"></label>' +
                        '<button type="button" class="v-btn" id="expLimitApply">Anpassen</button>' +
                    '</div>' +
                    '<p class="exp-hint" id="expLimitNote" hidden></p>' +
                '</section>' +
                '<section class="exp-block">' +
                    '<h4 class="exp-label">Verdichten</h4>' +
                    '<div class="exp-felder">' +
                        '<label class="exp-feld">Vor diesem Tag alles monatlich<input type="date" id="expCompact"></label>' +
                    '</div>' +
                    '<p class="exp-hint">Leer heißt: keine Grenze.</p>' +
                '</section>' +
            '</div>' +
            '<section class="exp-block exp-module">' +
                '<div class="exp-label-zeile"><h4 class="exp-label">Module</h4>' +
                    '<span class="exp-label-wert" id="expModAnzahl"></span></div>' +
                '<div id="expSections" class="v-schalt-liste exp-mods">' +
                    '<span class="skel exp-skel"></span><span class="skel exp-skel"></span><span class="skel exp-skel"></span>' +
                '</div>' +
                '<details class="exp-sample-box">' +
                    '<summary>Erste Zeilen ansehen</summary>' +
                    '<pre id="expSample" class="exp-sample"></pre>' +
                '</details>' +
            '</section>' +
        '</div>' +
        '<div class="modal-fuss exp-fuss">' +
            '<div class="exp-ergebnis" id="expSummary" aria-live="polite"></div>' +
            '<button type="button" class="v-btn v-btn--primary" id="expGo">Exportieren</button>' +
        '</div>';
    }

    /* Der Hinweis unter der Stufe. Bei „Automatisch“ nennt er die Stufe,
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

    function itemsOf(state, groupKey) {
        return state.sections.filter(s => s.group === groupKey);
    }

    /* Die Unterzeile eines Moduls: wie viel davon drin ist, und -- sobald die
       Vorschau steht -- wie viele Zeilen das sind. */
    function modulMeta(state, items) {
        const an = items.filter(s => state.picked.has(s.key));
        if (!an.length) return 'Nicht im Export';
        let text = an.length === items.length ? tabellen(items.length)
                                              : an.length + ' von ' + tabellen(items.length);
        const bekannt = an.filter(s => s.key in state.zeilen);
        if (bekannt.length) {
            text += ' · ' + zahl(bekannt.reduce((n, s) => n + state.zeilen[s.key], 0)) + ' Zeilen';
        }
        return text;
    }

    function sekMeta(state, s) {
        const teil = teile(s.label).mehr;
        const all = state.columns[s.key];
        const gew = state.chosen[s.key];
        return [
            teil,
            s.aggregatable ? '' : 'Stammdaten',
            gew && all ? gew.size + ' von ' + all.length + ' Spalten' : '',
        ].filter(Boolean).join(' · ');
    }

    function sekZahl(state, s) {
        if (!state.picked.has(s.key) || !(s.key in state.zeilen)) return '';
        return state.zeilen[s.key] ? zahl(state.zeilen[s.key]) : 'leer';
    }

    function sekHtml(state, s, allein) {
        const an = state.picked.has(s.key);
        const meta = sekMeta(state, s);
        const inhalt =
            '<span class="exp-sek-main">' +
                '<span class="exp-sek-name">' + esc(teile(s.label).name) + '</span>' +
                '<span class="exp-sek-meta" data-sek-meta="' + s.key + '">' + esc(meta) + '</span>' +
            '</span>' +
            '<span class="exp-sek-zahl" data-sek-zahl="' + s.key + '">' + sekZahl(state, s) + '</span>';
        // Ein Modul mit einer einzigen Tabelle braucht kein zweites Kästchen
        // neben seinem Schalter -- beide sagten dasselbe.
        if (allein) return '<div class="exp-sek exp-sek--allein">' + inhalt + '</div>';
        return '<label class="exp-sek' + (an ? '' : ' is-aus') + '">' +
            '<input type="checkbox" data-section="' + s.key + '"' + (an ? ' checked' : '') + '>' +
            inhalt + '</label>';
    }

    function modulHtml(state, g) {
        const items = itemsOf(state, g.key);
        if (!items.length) return '';
        const an = items.some(s => state.picked.has(s.key));
        // Die Aggregation gehoert zum Modul, nicht zur Sektion: sie betrifft
        // immer alle Zeitreihen eines Moduls gemeinsam.
        const canAgg = items.some(s => s.aggregatable && state.picked.has(s.key));
        const mitSpalten = items.some(s => state.picked.has(s.key) && (state.columns[s.key] || []).length > 1);
        const kopf =
            '<button type="button" class="v-schalt-zeile exp-mod-kopf" role="switch" aria-checked="' + an + '" data-group="' + g.key + '">' +
                '<span class="v-schalt-text">' +
                    '<span class="v-schalt-name">' + esc(g.label) + '</span>' +
                    '<span class="v-schalt-sub" data-mod-meta="' + g.key + '">' + esc(modulMeta(state, items)) + '</span>' +
                '</span>' +
                '<span class="v-schalter" aria-hidden="true"></span>' +
            '</button>';
        if (!an) return '<div class="exp-mod is-aus">' + kopf + '</div>';
        return '<div class="exp-mod">' + kopf +
            '<div class="exp-mod-body">' +
                items.map(s => sekHtml(state, s, items.length === 1)).join('') +
                (canAgg || mitSpalten ? '<div class="exp-mod-fuss">' +
                    (canAgg ? '<label class="exp-stufe"><span>Stufe</span>' +
                        '<select class="v-select" data-agg-group="' + g.key + '">' +
                            state.aggregates.map(a => '<option value="' + a.key + '"' +
                                (state.agg[g.key] === a.key ? ' selected' : '') + '>' +
                                esc(a.label) + '</option>').join('') +
                        '</select></label>' : '') +
                    (mitSpalten ? '<button type="button" class="v-btn v-btn--ghost v-btn--sm exp-spalten-btn" data-spalten="' + g.key + '">Spalten</button>' : '') +
                '</div>' : '') +
                (canAgg ? '<p class="exp-hint" data-agg-hint="' + g.key + '"' + (state.agg[g.key] === 'none' ? ' hidden' : '') + '>' +
                    esc(aggHint(state, g.key)) + '</p>' : '') +
            '</div>' +
        '</div>';
    }

    function renderSections(box, state) {
        // Wer gerade ein Bedienelement in der Liste hatte, behält es: die
        // Liste wird bei jedem Schalter neu gezeichnet.
        const fokus = document.activeElement && box.contains(document.activeElement)
            ? document.activeElement : null;
        const merk = fokus && (fokus.dataset.group ? '[data-group="' + fokus.dataset.group + '"]'
            : fokus.dataset.section ? '[data-section="' + fokus.dataset.section + '"]' : null);
        box.innerHTML = state.groups.map(g => modulHtml(state, g)).join('');
        if (merk) { const el = box.querySelector(merk); if (el) el.focus({ preventScroll: true }); }
        const anzahl = box.closest('.exp').querySelector('#expModAnzahl');
        const sichtbar = state.groups.filter(g => itemsOf(state, g.key).length);
        const an = sichtbar.filter(g => itemsOf(state, g.key).some(s => state.picked.has(s.key)));
        anzahl.textContent = an.length === sichtbar.length ? 'alle ' + sichtbar.length
                                                           : an.length + ' von ' + sichtbar.length;
    }

    /* Die Zahlen aus der Vorschau, ohne die Liste neu zu zeichnen: ein
       Auswahlfeld, das gerade bedient wird, verlöre sonst den Fokus. */
    function paintZahlen(box, state) {
        box.querySelectorAll('[data-sek-zahl]').forEach(el => {
            const s = state.sections.find(x => x.key === el.dataset.sekZahl);
            if (s) el.textContent = sekZahl(state, s);
        });
        box.querySelectorAll('[data-sek-meta]').forEach(el => {
            const s = state.sections.find(x => x.key === el.dataset.sekMeta);
            if (s) el.textContent = sekMeta(state, s);
        });
        box.querySelectorAll('[data-mod-meta]').forEach(el => {
            el.textContent = modulMeta(state, itemsOf(state, el.dataset.modMeta));
        });
    }

    function renderSumme(root, data, state) {
        const sum = root.querySelector('#expSummary');
        const sample = root.querySelector('#expSample');
        if (!data) {
            sum.innerHTML = '<span class="skel exp-skel-zahl"></span><span class="skel exp-skel-text"></span>';
            return;
        }
        if (data.error) {
            sum.innerHTML = '<span class="exp-warn">Vorschau nicht möglich: ' + esc(data.error) + '</span>';
            sample.textContent = '';
            return;
        }
        // Ist eine Grenze gesetzt, steht der Stand DARAN -- eine nackte
        // Zahl beantwortet die Frage "passt das noch?" nicht.
        let grenze = '';
        if (state.limit > 0) {
            const over = data.bytes > state.limit;
            grenze = '<span class="' + (over ? 'exp-warn' : 'exp-ok') + '">' +
                (over ? 'über ' : 'von ') + fmtBytes(state.limit) + '</span>';
        }
        // Die Groesse ist die der Zeilen, nicht die der Datei auf der Platte:
        // ein Archiv packt sie noch. Eine Zahl, die fuer beide Formen
        // dieselbe waere, waere fuer eines von beiden falsch.
        const mit = (data.sections || []).filter(s => s.rows).length;
        sum.innerHTML =
            '<span class="exp-groesse">' + fmtBytes(data.bytes) + grenze + '</span>' +
            '<span class="exp-zeilen">' + zahl(data.total_rows) + ' Zeilen · ' +
                (state.format === 'zip' ? 'gepackt deutlich kleiner' : tabellen(mit)) + '</span>';
        sample.textContent = (data.sample || '') + (data.truncated ? '\n…' : '');
    }

    /* Die Spalten eines Moduls, einen Griff tiefer. Geändert wird sofort --
       der Dialog darunter rechnet die Vorschau nach, „Fertig“ schließt nur. */
    function spaltenDialog(state, groupKey, geaendert) {
        const g = state.groups.find(x => x.key === groupKey);
        const items = itemsOf(state, groupKey).filter(s => state.picked.has(s.key));
        const stand = (key) => {
            const all = state.columns[key] || [];
            const gew = state.chosen[key];
            return gew ? gew.size + ' von ' + all.length : 'alle ' + all.length;
        };
        const inhalt = '<div class="exp-spalten">' + items.map(s => {
            const all = state.columns[s.key] || [];
            const kopf = '<div class="exp-spalten-kopf"><span class="exp-spalten-name">' +
                esc(teile(s.label).name) + '</span>';
            if (all.length < 2) {
                return '<div class="exp-spalten-sek">' + kopf + '</div>' +
                    '<p class="exp-hint">' + (all.length ? 'Nur eine Spalte.'
                        : 'Die Spalten stehen fest, sobald die Vorschau gerechnet ist.') + '</p></div>';
            }
            const gew = state.chosen[s.key];
            return '<div class="exp-spalten-sek" data-sek="' + esc(s.key) + '">' + kopf +
                    '<span class="exp-spalten-stand">' + stand(s.key) + '</span>' +
                    '<button type="button" class="v-btn v-btn--ghost v-btn--sm" data-alle="' + esc(s.key) + '"' + (gew ? '' : ' hidden') + '>Alle</button>' +
                '</div>' +
                '<div class="exp-chips">' + all.map(c => {
                    const an = !gew || gew.has(c);
                    return '<button type="button" class="v-chip' + (an ? ' is-active' : '') + '" aria-pressed="' + an + '"' +
                        ' data-col="' + esc(c) + '">' + esc(c) + '</button>';
                }).join('') + '</div>' +
            '</div>';
        }).join('') + '</div>' +
        '<div class="modal-fuss"><button type="button" class="v-btn v-btn--primary" data-fertig>Fertig</button></div>';
        const dlg = VexModal.open('Spalten · ' + esc(g ? g.label : ''), inhalt, {});
        dlg.box.classList.add('exp-spalten-dialog');

        const malen = (key) => {
            const sek = dlg.root.querySelector('[data-sek="' + key + '"]');
            if (!sek) return;
            const gew = state.chosen[key];
            sek.querySelectorAll('[data-col]').forEach(b => {
                const an = !gew || gew.has(b.dataset.col);
                b.classList.toggle('is-active', an);
                b.setAttribute('aria-pressed', an);
            });
            sek.querySelector('.exp-spalten-stand').textContent = stand(key);
            sek.querySelector('[data-alle]').hidden = !gew;
        };
        dlg.root.addEventListener('click', (e) => {
            if (e.target.closest('[data-fertig]')) { dlg.close(); return; }
            const alle = e.target.closest('[data-alle]');
            if (alle) {
                delete state.chosen[alle.dataset.alle];
                malen(alle.dataset.alle);
                geaendert();
                return;
            }
            const chip = e.target.closest('[data-col]');
            if (!chip) return;
            const key = chip.closest('[data-sek]').dataset.sek;
            const all = state.columns[key] || [];
            const set = new Set(state.chosen[key] || all);
            set.has(chip.dataset.col) ? set.delete(chip.dataset.col) : set.add(chip.dataset.col);
            // Eine Tabelle ohne Spalten waere eine kaputte Datei. Wer nichts
            // von ihr will, schaltet die Tabelle selbst ab.
            if (!set.size) {
                if (window.Toast) Toast.info('Eine Spalte bleibt mindestens. Ganz weglassen: Tabelle abwählen.');
                return;
            }
            if (set.size >= all.length) delete state.chosen[key];
            else state.chosen[key] = set;
            malen(key);
            geaendert();
        });
    }

    async function doExport(state) {
        const qs = queryOf(state).toString();
        if (window.Toast) Toast.info('Export wird erstellt…', { timeout: 2000 });
        try {
            const res = await apiCall('/api/export/all' + (qs ? '?' + qs : ''), { raw: true });
            if (!res || !res.ok) throw new Error('HTTP ' + (res && res.status));
            const blob = await res.blob();
            // Der Rueckfallname richtet sich nach der gewaehlten Form. Steht
            // hier fest .csv, bekommt ein Archiv die falsche Endung und laesst
            // sich nicht mehr oeffnen -- der Inhalt war nie das Problem.
            let filename = 'vexbob-gesamt-export' + (state.format === 'zip' ? '.zip' : '.csv');
            const cd = res.headers.get('content-disposition') || '';
            const m = cd.match(/filename="?([^";]+)"?/i);
            // Nur uebernehmen, wenn die Endung zur gewaehlten Form passt: ein
            // Zwischenspeicher oder ein alter Server darf dem Archiv keinen
            // .csv-Namen geben.
            if (m && m[1].toLowerCase().endsWith(filename.slice(-4))) filename = m[1];
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

    function wire(dlg, state) {
        const root = dlg.root;
        const sectionBox = root.querySelector('#expSections');
        const fromEl = root.querySelector('#expFrom');
        const toEl = root.querySelector('#expTo');
        const compactEl = root.querySelector('#expCompact');
        const limitNote = root.querySelector('#expLimitNote');
        const limitMbEl = root.querySelector('#expLimitMb');
        let previewTimer = null;
        let previewSeq = 0;
        dlg.stop = () => { clearTimeout(previewTimer); previewSeq++; };

        /* Was die Vorschau über den Aufbau der Datei verrät, fließt zurück in
           die Auswahl: Zeilen je Tabelle, die Spaltenlisten und die Stufe,
           auf die „Automatisch“ hinausläuft. */
        function absorb(data) {
            let neu = false;
            state.zeilen = {};
            (data.sections || []).forEach(s => {
                state.zeilen[s.key] = s.rows || 0;
                const before = (state.columns[s.key] || []).join(' ');
                const now = (s.columns || []).join(' ');
                if (before !== now) {
                    // Ob ein Spalten-Knopf erscheint, haengt an der Liste.
                    if (!before || !now) neu = true;
                    state.columns[s.key] = s.columns || [];
                    // Eine Auswahl, die es in der neuen Spaltenliste nicht mehr
                    // gibt (andere Aggregation), gilt nicht weiter.
                    if (state.chosen[s.key]) {
                        const kept = new Set(
                            (s.columns || []).filter(c => state.chosen[s.key].has(c)));
                        if (kept.size && kept.size < (s.columns || []).length) state.chosen[s.key] = kept;
                        else delete state.chosen[s.key];
                    }
                }
            });
            Object.keys(data.aggregate || {}).forEach(g => {
                state.resolved[g] = data.aggregate[g];
                const hint = sectionBox.querySelector('[data-agg-hint="' + g + '"]');
                if (hint) hint.textContent = aggHint(state, g);
            });
            if (neu) renderSections(sectionBox, state);
            else paintZahlen(sectionBox, state);
            sectionBox.classList.remove('is-alt');
        }

        function paintLimit() {
            root.querySelectorAll('#expLimit .v-chip').forEach(b => {
                const an = Number(b.dataset.limit) === state.limitPick;
                b.classList.toggle('is-active', an);
                b.setAttribute('aria-pressed', an);
                b.disabled = state.fitting;
            });
            root.querySelector('#expLimitCustom').hidden = state.limitPick !== -1;
            if (state.fitting) {
                // Laden heißt Skeleton, nicht „Lade …“ als Fließtext.
                limitNote.hidden = false;
                limitNote.innerHTML = '<span class="skel exp-skel-text"></span>';
            } else {
                limitNote.hidden = !state.fitNote;
                limitNote.textContent = state.fitNote || '';
            }
        }

        /* Der Server sucht die feinste Aggregation, die unter die Grenze
           passt, und liefert die fertige Vorschau gleich mit. Was er
           entschieden hat, landet in den Auswahlfeldern — sonst wäre die
           Einstellung eine Blackbox. */
        async function fitToLimit() {
            if (!state.limit || !state.picked.size) return;
            state.fitting = true;
            paintLimit();
            renderSumme(root, null, state);
            sectionBox.classList.add('is-alt');
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
                        + '“ mit ' + fmtBytes(data.largest_section.bytes) + '.';
                }
                state.fitting = false;
                renderSections(sectionBox, state);
                if (data.preview) {
                    state.letzteVorschau = data.preview;
                    renderSumme(root, data.preview, state);
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
                state.letzteVorschau = { sections: [], total_rows: 0, bytes: 0, sample: '' };
                renderSumme(root, state.letzteVorschau, state);
                return;
            }
            renderSumme(root, null, state);
            sectionBox.classList.add('is-alt');
            // Die Vorschau baut serverseitig den echten Export -- deshalb erst
            // kurz warten, statt bei jedem Haken eine Anfrage zu schicken.
            previewTimer = setTimeout(async () => {
                const seq = ++previewSeq;
                const qs = queryOf(state).toString();
                try {
                    const data = await apiCall('/api/export/preview' + (qs ? '?' + qs : ''));
                    if (seq !== previewSeq) return;   // eine neuere Anfrage laeuft
                    state.letzteVorschau = data;
                    renderSumme(root, data, state);
                    absorb(data);
                } catch (e) {
                    if (seq !== previewSeq) return;
                    renderSumme(root, { error: e.message || String(e) }, state);
                }
            }, 400);
        }

        function paintRange() {
            root.querySelectorAll('#expRange .v-chip').forEach(b => {
                const an = b.dataset.preset === state.preset;
                b.classList.toggle('is-active', an);
                b.setAttribute('aria-pressed', an);
            });
            root.querySelector('#expCustom').hidden = state.preset !== 'custom';
        }

        function paintFormat() {
            root.querySelectorAll('#expFormat .exp-form').forEach(b => {
                b.setAttribute('aria-pressed', b.dataset.format === state.format);
            });
        }

        root.querySelector('#expFormat').addEventListener('click', (e) => {
            const b = e.target.closest('.exp-form');
            if (!b) return;
            state.format = b.dataset.format;
            paintFormat();
            // Die Form aendert die Verpackung, nicht den Inhalt -- die
            // Vorschau zaehlt dieselben Zeilen. Nur der Hinweis unter der
            // Groesse muss nachziehen.
            if (state.letzteVorschau) renderSumme(root, state.letzteVorschau, state);
        });

        root.querySelector('#expLimit').addEventListener('click', (e) => {
            const b = e.target.closest('.v-chip');
            if (!b || state.fitting) return;
            const value = Number(b.dataset.limit);
            state.limitPick = value;
            if (value === -1) {
                // „Eigene“ öffnet nur das Feld -- gerechnet wird erst auf
                // „Anpassen“, sonst liefe die Suche bei jeder getippten Ziffer.
                paintLimit();
                limitMbEl.focus();
                return;
            }
            state.limit = value;
            state.fitNote = '';
            paintLimit();
            if (value > 0) fitToLimit(); else refreshPreview();
        });

        root.querySelector('#expLimitApply').addEventListener('click', () => {
            const mb = parseFloat(String(limitMbEl.value).replace(',', '.'));
            if (!mb || mb <= 0) {
                if (window.Toast) Toast.error('Bitte eine Größe in Megabyte angeben');
                return;
            }
            state.limit = Math.round(mb * 1048576);
            state.fitNote = '';
            fitToLimit();
        });

        root.querySelector('#expRange').addEventListener('click', (e) => {
            const b = e.target.closest('.v-chip');
            if (!b) return;
            state.preset = b.dataset.preset;
            paintRange();
            if (state.preset !== 'custom' || (state.from || state.to)) refreshPreview();
        });
        compactEl.value = state.compactBefore || '';
        compactEl.addEventListener('change', () => {
            state.compactBefore = compactEl.value || '';
            refreshPreview();
        });
        [fromEl, toEl].forEach(el => el.addEventListener('change', () => {
            state.from = fromEl.value;
            state.to = toEl.value;
            if (state.from && state.to && state.from > state.to) {
                if (window.Toast) Toast.error('„Von“ liegt nach „Bis“');
                return;
            }
            refreshPreview();
        }));

        sectionBox.addEventListener('click', (e) => {
            const spalten = e.target.closest('[data-spalten]');
            if (spalten) {
                spaltenDialog(state, spalten.dataset.spalten, () => {
                    paintZahlen(sectionBox, state);
                    refreshPreview();
                });
                return;
            }
            // Der Schalter am Modul: an heißt alle Tabellen, aus heißt keine.
            const kopf = e.target.closest('.exp-mod-kopf');
            if (!kopf) return;
            const keys = itemsOf(state, kopf.dataset.group).map(s => s.key);
            const an = keys.some(k => state.picked.has(k));
            keys.forEach(k => an ? state.picked.delete(k) : state.picked.add(k));
            renderSections(sectionBox, state);
            refreshPreview();
        });

        sectionBox.addEventListener('change', (e) => {
            const el = e.target;
            if (el.dataset.aggGroup) {
                state.agg[el.dataset.aggGroup] = el.value;
                // Nur der Hinweistext darunter aendert sich. Die ganze Liste
                // neu zu zeichnen naehme dem Auswahlfeld mitten im Bedienen
                // den Fokus.
                const hint = sectionBox.querySelector('[data-agg-hint="' + el.dataset.aggGroup + '"]');
                // „Einzeln“ sagt schon selbst, was es heißt.
                if (hint) {
                    hint.textContent = aggHint(state, el.dataset.aggGroup);
                    hint.hidden = el.value === 'none';
                }
                refreshPreview();
                return;
            }
            if (!el.dataset.section) return;
            el.checked ? state.picked.add(el.dataset.section)
                       : state.picked.delete(el.dataset.section);
            renderSections(sectionBox, state);
            refreshPreview();
        });

        root.querySelector('#expGo').onclick = async () => {
            if (!state.picked.size) {
                if (window.Toast) Toast.error('Ohne Modul gäbe es nichts zu exportieren');
                return;
            }
            const r = rangeOf(state);
            if (r.from && r.to && r.from > r.to) {
                if (window.Toast) Toast.error('„Von“ liegt nach „Bis“');
                return;
            }
            dlg.close();
            await doExport(state);
        };

        paintFormat();
        paintRange();
        paintLimit();
        return { refreshPreview, fitToLimit };
    }

    window.exportAll = async function exportAll() {
        // Ein Dialog, in dem man tippt (Datum, Megabyte), ist am Handy
        // ``voll`` -- als Blatt rückte er bei jeder Höhenänderung.
        let steuerung = null;
        const dlg = VexModal.open('Export', dialogHtml(), {
            voll: true,
            beimSchliessen: () => { if (steuerung) steuerung.stop(); },
        });
        dlg.box.classList.add('exp-dialog');
        steuerung = dlg;
        renderSumme(dlg.root, null, null);

        let meta;
        try {
            // Die Voreinstellung KOMMT VOM SERVER, nicht aus dem Cache. Der
            // localStorage ist nur ein Cache, und `navReady()` steigt früh
            // aus, sobald die Leiste steht — er kann hier also veraltet oder
            // leer sein. `load()` ist idempotent, der Aufruf kostet eine Anfrage.
            const [sections] = await Promise.all([
                apiCall('/api/export/sections'),
                (window.VexPrefs ? VexPrefs.load() : Promise.resolve()).catch(() => {}),
            ]);
            meta = sections;
        } catch (e) {
            // Der Fehler steht dort, wo die Module stünden -- und „Exportieren“
            // ist aus, weil ohne die Liste nichts zusammenzustellen ist.
            dlg.root.querySelector('#expSections').innerHTML =
                '<div class="empty is-error"><span class="empty-mark">⚠️</span>' +
                '<p class="empty-text">Die Modulliste konnte nicht geladen werden. ' +
                'Ohne sie lässt sich nichts zusammenstellen.</p></div>';
            dlg.root.querySelector('#expSummary').innerHTML = '';
            dlg.root.querySelector('#expGo').disabled = true;
            return;
        }
        const state = newState(meta);
        renderSections(dlg.root.querySelector('#expSections'), state);
        wire(dlg, state).refreshPreview();
    };
})();
