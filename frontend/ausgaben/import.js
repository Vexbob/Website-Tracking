/* Ausgaben-Import — v1.80.0
 *
 * Der Rückblick auf die Zeit vor August 2026 kommt als CSV aus der
 * Banking-App. Diese Seite tut zwei Dinge: sie zeigt vor dem Schreiben, was
 * passieren würde, und sie protokolliert, was passiert ist.
 *
 * Die Vorschau ist hier keine Höflichkeit, sondern die eigentliche Funktion.
 * Ein Import legt Läden an und räumt einen Zeitraum leer — beides sieht man
 * hinterher nur mühsam wieder ein. Deshalb läuft jeder Upload zuerst als
 * `dry_run` und zeigt die Zuordnung der Zahlungsempfänger im Klartext: welche
 * Schreibweisen zu welchem Laden zusammengefasst wurden, und welche Läden neu
 * entstünden. Stimmt die Zusammenfassung nicht, korrigiert man die Läden
 * vorher statt hinterher 300 Buchungen.
 */

const IMPORT_API = {
    upload: (file, dry) => {
        const fd = new FormData();
        fd.append('file', file);
        return apiCall('/api/expenses/import' + (dry ? '?dry_run=1' : ''),
                       { method: 'POST', body: fd });
    },
    imports: () => apiCall('/api/expenses/imports'),
    undo: (id) => apiCall('/api/expenses/imports/' + id, { method: 'DELETE' }),
};

const state = { file: null, plan: null };

const esc = (s) => (s == null ? '' : String(s).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])));
const fmtInt = (n) => (Number(n) || 0).toLocaleString('de-DE');
const fmtEuro = (n) => (Number(n) || 0).toLocaleString('de-DE',
    { style: 'currency', currency: 'EUR' });
const fmtDay = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    return isNaN(d) ? String(iso)
        : d.toLocaleDateString('de-DE', { day: '2-digit', month: 'short', year: 'numeric' });
};

/* Warum eine Zeile wegfiel. Klartext, keine Schlüssel — die Zahl allein
   ("14 übersprungen") wirft genau die Frage auf, die sie beantworten soll. */
const SKIP_LABEL = {
    gutschrift: 'Gutschrift (Gehalt, Erstattung)',
    ohne_datum: 'ohne lesbares Datum',
    ohne_betrag: 'ohne lesbaren Betrag',
    null: 'Betrag 0,00 €',
};

async function init() {
    const me = await ensureLoggedIn(); if (!me) return;
    renderSubnav();
    setupDropzone();
    await loadLog();
}

/* ------------------------------------------------------------ Ablegefläche */

function setupDropzone() {
    const drop = document.getElementById('impDrop');
    const input = document.getElementById('impFile');

    drop.onclick = () => input.click();
    drop.onkeydown = (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); }
    };
    drop.ondragover = (e) => { e.preventDefault(); drop.classList.add('drag'); };
    drop.ondragleave = () => drop.classList.remove('drag');
    drop.ondrop = (e) => {
        e.preventDefault();
        drop.classList.remove('drag');
        const f = e.dataTransfer.files && e.dataTransfer.files[0];
        if (f) take(f);
    };
    input.onchange = () => { if (input.files[0]) take(input.files[0]); };
}

function take(file) {
    state.file = file;
    const drop = document.getElementById('impDrop');
    drop.classList.add('has-files');
    document.getElementById('impDropSub').textContent = file.name;
    preview(file);
}

function resetDropzone() {
    state.file = null;
    state.plan = null;
    document.getElementById('impFile').value = '';
    document.getElementById('impDrop').classList.remove('has-files');
    document.getElementById('impDropSub').textContent =
        'Eine Datei, Semikolon oder Komma getrennt';
}

/* ----------------------------------------------------------------- Vorschau */

/* Kurzes Datum fuer die Zeitraum-Kachel: dort stehen zwei davon
   nebeneinander, ausgeschriebene Monatsnamen sprengen die Zeile. */
const fmtShort = (iso) => {
    if (!iso) return '?';
    const d = new Date(iso);
    return isNaN(d) ? String(iso)
        : d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: '2-digit' });
};

function kpis(p) {
    const cells = [
        [fmtInt(p.rows_ready), 'Buchungen'],
        [fmtEuro(p.total), 'Summe'],
        [fmtShort(p.from) + ' – ' + fmtShort(p.to), 'Zeitraum'],
        [fmtInt((p.stores_new || []).length), 'neue Läden'],
    ];
    return '<div class="imp-kpis">' + cells.map(([v, l]) =>
        '<div class="imp-kpi"><div class="imp-kpi-val' +
            (l === 'Zeitraum' ? ' is-span' : '') + '">' + esc(v) + '</div>' +
        '<div class="imp-kpi-lbl">' + esc(l) + '</div></div>').join('') + '</div>';
}

function storeList(items, opts) {
    if (!items || !items.length) return '';
    return '<div class="imp-sec">' +
        '<div class="imp-sec-head"><h3>' + esc(opts.title) + '</h3>' +
        '<span class="imp-sec-note">' + esc(opts.note) + '</span></div>' +
        '<div class="imp-list">' + items.map(s => {
            // Die Rohschreibweisen sind der Beleg für die Zusammenfassung.
            const raw = (s.payees || []).filter(x => x && x !== s.store_name && x !== s.name);
            return '<div class="imp-row">' +
                '<span class="imp-row-name">' + esc(s.store_name || s.name) + '</span>' +
                (raw.length ? '<span class="imp-row-raw" title="' + esc(raw.join(' · ')) + '">' +
                    esc(raw.join(' · ')) + '</span>' : '') +
                '<span class="imp-row-sub">' + fmtInt(s.rows) + '×</span>' +
                '<span class="imp-row-val">' + fmtEuro(s.amount) + '</span>' +
            '</div>';
        }).join('') + '</div></div>';
}

function categoryList(cats) {
    if (!cats || !cats.length) return '';
    return '<div class="imp-sec">' +
        '<div class="imp-sec-head"><h3>Kategorien der Bank</h3>' +
        '<span class="imp-sec-note">werden mitgespeichert, aber noch nicht zugeordnet</span></div>' +
        '<div class="imp-list">' + cats.map(c =>
            '<div class="imp-row">' +
                '<span class="imp-row-name">' + esc(c.category) +
                    (c.subcategory ? ' <span class="imp-row-sub">› ' + esc(c.subcategory) + '</span>' : '') +
                '</span>' +
                '<span class="imp-row-sub">' + fmtInt(c.rows) + '×</span>' +
                '<span class="imp-row-val">' + fmtEuro(c.amount) + '</span>' +
            '</div>').join('') + '</div></div>';
}

function skipNote(skipped) {
    const keys = Object.keys(skipped || {});
    if (!keys.length) return '';
    const parts = keys.map(k => fmtInt(skipped[k]) + ' ' + (SKIP_LABEL[k] || k));
    return '<p class="imp-note">Nicht übernommen: <strong class="imp-warn">' +
        esc(parts.join(', ')) + '</strong>.</p>';
}

function replaceNote(p, applied) {
    const out = [];
    if (p.replaces) {
        out.push('<p class="imp-note">In diesem Zeitraum liegen bereits ' +
            '<strong class="imp-warn">' + fmtInt(p.replaces) + ' früher importierte Buchungen</strong> — sie ' +
            (applied ? 'wurden ersetzt.' : 'werden ersetzt.') +
            ' Dadurch ist derselbe Upload zweimal hintereinander folgenlos.</p>');
    }
    // Der eine Fall, in dem etwas doppelt gezählt werden könnte.
    const own = p.own_in_range || {};
    if (own.count) {
        out.push('<p class="imp-note">Achtung: In denselben Zeitraum fallen ' +
            '<strong class="imp-warn">' + fmtInt(own.count) + ' selbst erfasste Bons</strong> über ' +
            fmtEuro(own.total) + '. Die bleiben unangetastet — wenn dieselben Einkäufe auch im ' +
            'Kontoauszug stehen, zählen sie danach doppelt.</p>');
    }
    if (p.without_store && p.without_store.rows) {
        out.push('<p class="imp-note">' + fmtInt(p.without_store.rows) +
            ' Buchungen haben keinen Empfänger und bleiben ohne Laden.</p>');
    }
    return out.join('');
}

function planHtml(p, applied) {
    const head =
        '<div class="imp-plan-head">' +
            '<span class="imp-plan-title">' +
                (applied ? 'Übernommen' : 'Das würde passieren') + '</span>' +
            '<span class="imp-plan-sub">' + fmtInt(p.rows_read) + ' Zeilen gelesen · ' +
                fmtInt(applied ? p.rows_written : p.rows_ready) + ' übernommen' +
            '</span>' +
        '</div>';

    const actions = applied ? '' :
        '<div class="imp-actions">' +
            '<button type="button" class="v-btn v-btn--primary" id="impApply">Übernehmen</button>' +
            '<button type="button" class="v-btn v-btn--ghost" id="impCancel">Verwerfen</button>' +
        '</div>';

    if (applied) {
        return head + skipNote(p.skipped) +
            '<p class="imp-note">' + fmtInt(p.stores_created) + ' Läden neu angelegt.</p>' +
            replaceNote(p, true);
    }

    return head + kpis(p) +
        storeList(p.stores_matched, { title: 'Bestehende Läden', note: 'werden wiederverwendet' }) +
        storeList(p.stores_new, { title: 'Neue Läden', note: 'werden angelegt' }) +
        categoryList(p.categories) +
        skipNote(p.skipped) +
        replaceNote(p, false) +
        actions;
}

async function preview(file) {
    const box = document.getElementById('impPlan');
    box.innerHTML = '<span class="skel skel-block"></span>';
    try {
        state.plan = await IMPORT_API.upload(file, true);
        box.innerHTML = planHtml(state.plan, false);
        document.getElementById('impApply').onclick = apply;
        document.getElementById('impCancel').onclick = () => {
            resetDropzone();
            box.innerHTML = '';
        };
    } catch (e) {
        state.plan = null;
        box.innerHTML = '<div class="empty is-error">' +
            '<span class="empty-mark" aria-hidden="true">⚠️</span>' +
            '<p class="empty-text">' + esc(e.message || e) + '</p></div>';
    }
}

async function apply() {
    const btn = document.getElementById('impApply');
    if (btn) { btn.disabled = true; btn.classList.add('is-loading'); }
    try {
        const result = await IMPORT_API.upload(state.file, false);
        document.getElementById('impPlan').innerHTML = planHtml(result, true);
        resetDropzone();
        showToast(fmtInt(result.rows_written) + ' Buchungen übernommen', 'success');
        await loadLog();
    } catch (e) {
        if (btn) { btn.disabled = false; btn.classList.remove('is-loading'); }
        showToast('Import fehlgeschlagen: ' + (e.message || e), 'error');
    }
}

/* ---------------------------------------------------------------- Protokoll */

function logSummary(r) {
    const parts = [fmtInt(r.rows_written) + ' übernommen'];
    if (r.rows_replaced) parts.push(fmtInt(r.rows_replaced) + ' ersetzt');
    if (r.rows_skipped) parts.push(fmtInt(r.rows_skipped) + ' übersprungen');
    if (r.stores_created) parts.push(fmtInt(r.stores_created) + ' Läden angelegt');
    return parts.join(' · ');
}

async function loadLog() {
    const box = document.getElementById('impLog');
    try {
        const rows = await IMPORT_API.imports();
        if (!rows.length) {
            box.innerHTML = '<div class="empty">' +
                '<span class="empty-mark" aria-hidden="true">🧾</span>' +
                '<p class="empty-text">Noch kein Kontoauszug übernommen. Sobald einer drin ist, ' +
                'steht hier, welchen Zeitraum er mitgebracht hat — und du kannst ihn als Ganzes ' +
                'wieder zurücknehmen.</p></div>';
            return;
        }
        box.innerHTML = rows.map(r =>
            '<div class="v-row imp-log-row">' +
                '<div>' +
                    '<div class="imp-log-name">' + esc(r.filename || 'ohne Dateiname') + '</div>' +
                    '<div class="imp-log-meta">' + fmtDay(r.uploaded_at) + ' · ' +
                        fmtDay(r.date_from) + ' – ' + fmtDay(r.date_to) + ' · ' +
                        esc(logSummary(r)) +
                    '</div>' +
                '</div>' +
                '<button type="button" class="v-btn v-btn--sm v-btn--danger" ' +
                        'data-undo="' + r.id + '">Zurücknehmen</button>' +
            '</div>').join('');
        box.querySelectorAll('[data-undo]').forEach(b => { b.onclick = () => undo(+b.dataset.undo); });
    } catch (e) {
        // "HTTP 404" allein beantwortet keine Frage -- der Satz davor sagt,
        // was nicht geladen werden konnte.
        box.innerHTML = '<div class="empty is-error">' +
            '<span class="empty-mark" aria-hidden="true">⚠️</span>' +
            '<p class="empty-text">Das Protokoll konnte nicht geladen werden. ' +
            'Deine Buchungen sind davon nicht betroffen.<br><small>' +
            esc(e.message || e) + '</small></p></div>';
    }
}

async function undo(id) {
    const ok = await askConfirm({
        title: 'Import zurücknehmen?',
        text: 'Alle Buchungen aus diesem Upload werden gelöscht. Läden, die dabei entstanden ' +
              'sind, bleiben stehen — sie könnten inzwischen an eigenen Bons hängen.',
        ok: 'Zurücknehmen', danger: true,
    });
    if (!ok) return;
    try {
        const r = await IMPORT_API.undo(id);
        showToast(fmtInt(r.removed) + ' Buchungen entfernt', 'success');
        await loadLog();
    } catch (e) {
        showToast('Fehlgeschlagen: ' + (e.message || e), 'error');
    }
}

init();
