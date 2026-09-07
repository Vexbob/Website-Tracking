/* range-filter.js — v1.60.0
 * Der Zeitraum-Filter als EINE Komponente für alle Seiten mit Statistik.
 *
 * Vorher stand auf jeder dieser Seiten eine Reihe aus fünf Chips plus zwei
 * Datumsfeldern dauerhaft im Weg — auf dem Handy nahm sie zwei Zeilen, obwohl
 * man den Zeitraum selten wechselt. Jetzt steht dort ein Knopf, der den
 * aktuellen Zeitraum benennt; alles Weitere liegt in seinem Menü.
 *
 * Verwendung:
 *   const rf = VexRange.mount(hostEl, {
 *       onChange: (r) => { ... },     // r: {preset, from, to, days, label}
 *       preset: '30',                 // optional, sonst die Einstellung
 *   });
 *   rf.get();          // aktueller Zeitraum
 *   rf.set('90');      // von außen setzen (löst onChange aus)
 *
 * `from`/`to` sind ISO-Tage oder null (offener Anfang bei „Gesamt"). `days`
 * ist die Länge des Fensters — für Beschriftung und Auflösung. `fetchDays`
 * ist die Spanne von heute bis `from`, für Endpunkte, die nur eine Tageszahl
 * kennen; wer damit lädt, schneidet danach mit VexRange.clip() auf `from`/`to`
 * zu — bei einem zurückliegenden Fenster hätte er sonst zu viel geholt.
 * Beide sind 0 bei „Gesamt", was dort „keine Begrenzung“ heißt.
 */
(function () {
    if (window.VexRange) return;

    const PRESETS = [
        { key: '7',   label: '7 Tage' },
        { key: '30',  label: '30 Tage' },
        { key: '90',  label: '90 Tage' },
        { key: '365', label: '1 Jahr' },
        { key: 'all', label: 'Gesamt' },
    ];
    const DEFAULT_PRESET = '30';

    const iso = (d) => {
        const p = (n) => String(n).padStart(2, '0');
        return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
    };
    const today = () => iso(new Date());
    const daysAgo = (n) => iso(new Date(Date.now() - (n - 1) * 86400000));
    const short = (v) => {
        if (!v) return '?';
        const d = new Date(v + 'T00:00:00');
        return isNaN(d) ? v : d.toLocaleDateString('de-DE',
            { day: '2-digit', month: '2-digit', year: 'numeric' });
    };

    /* Der Zeitraum als Objekt. Aus einem Preset wird hier alles abgeleitet,
       damit die Seiten nicht jede für sich rechnen. */
    const spanDays = (a, b) => Math.max(1, Math.round(
        (new Date(b + 'T00:00:00') - new Date(a + 'T00:00:00')) / 86400000) + 1);

    function resolve(preset, from, to) {
        if (preset === 'custom') {
            const f = from || null, t = to || today();
            return {
                preset: 'custom', from: f, to: t,
                days: f ? spanDays(f, t) : 0,             // Laenge des Fensters
                fetchDays: f ? spanDays(f, today()) : 0,  // von heute zurueck
                label: (f ? short(f) : 'Anfang') + ' – ' + short(t),
            };
        }
        if (preset === 'all') {
            return { preset: 'all', from: null, to: today(), days: 0, fetchDays: 0,
                     label: 'Gesamt' };
        }
        const n = parseInt(preset, 10) || 30;
        const p = PRESETS.find(x => x.key === String(n));
        return { preset: String(n), from: daysAgo(n), to: today(), days: n, fetchDays: n,
                 label: p ? p.label : n + ' Tage' };
    }

    const calendarIcon =
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" ' +
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
        '<rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M3.5 9.5h17M8 3.5v3M16 3.5v3"/></svg>';

    function mount(host, opts) {
        opts = opts || {};
        const wrap = document.createElement('div');
        wrap.className = 'filter-popover-wrap rf';
        wrap.innerHTML =
            '<button type="button" class="filter-toggle-btn rf-btn" aria-expanded="false" ' +
                    'aria-haspopup="dialog">' + calendarIcon +
                '<span class="rf-label"></span>' +
                '<svg class="rf-caret" viewBox="0 0 24 24" width="14" height="14" fill="none" ' +
                    'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
                    'stroke-linejoin="round" aria-hidden="true"><path d="M6 9.5l6 6 6-6"/></svg>' +
            '</button>' +
            '<div class="filter-popover rf-pop" role="dialog" aria-label="Zeitraum" hidden>' +
                '<div class="rf-presets">' +
                    PRESETS.map(p => '<button type="button" class="rf-opt" data-preset="' + p.key +
                        '">' + p.label + '<span class="rf-check" aria-hidden="true">✓</span></button>').join('') +
                '</div>' +
                '<div class="fp-row fp-two">' +
                    '<div><label class="fp-label">Von</label><input type="date" data-role="from"></div>' +
                    '<div><label class="fp-label">Bis</label><input type="date" data-role="to"></div>' +
                '</div>' +
                '<div class="fp-actions">' +
                    '<button type="button" class="fp-btn fp-btn-ghost" data-act="reset">Zurücksetzen</button>' +
                    '<button type="button" class="fp-btn fp-btn-primary" data-act="apply">Übernehmen</button>' +
                '</div>' +
            '</div>';
        host.appendChild(wrap);

        const btn = wrap.querySelector('.rf-btn');
        const pop = wrap.querySelector('.rf-pop');
        const lbl = wrap.querySelector('.rf-label');
        const fromEl = wrap.querySelector('[data-role="from"]');
        const toEl = wrap.querySelector('[data-role="to"]');

        // Ohne ausdrücklichen Wunsch gilt die Einstellung des Kontos.
        const start = opts.preset
            || (window.VexPrefs ? VexPrefs.get('ui_default_range', DEFAULT_PRESET) : DEFAULT_PRESET);
        let state = resolve(start);

        function paint() {
            lbl.textContent = state.label;
            btn.classList.toggle('has-active', state.preset === 'custom');
            wrap.querySelectorAll('.rf-opt').forEach(b => {
                b.classList.toggle('is-active', b.dataset.preset === state.preset);
            });
            fromEl.value = state.from || '';
            toEl.value = state.to || '';
        }
        const close = () => { pop.hidden = true; btn.setAttribute('aria-expanded', 'false'); };
        const open = () => { pop.hidden = false; btn.setAttribute('aria-expanded', 'true'); };

        function emit() {
            paint();
            if (typeof opts.onChange === 'function') opts.onChange(state);
        }

        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            pop.hidden ? open() : close();
        });
        document.addEventListener('click', (e) => { if (!wrap.contains(e.target)) close(); });
        document.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });

        wrap.querySelector('.rf-presets').addEventListener('click', (e) => {
            const b = e.target.closest('.rf-opt');
            if (!b) return;
            // Ein Preset ist die schnelle Antwort: anwenden und zumachen.
            state = resolve(b.dataset.preset);
            close();
            emit();
        });
        wrap.querySelector('.fp-actions').addEventListener('click', (e) => {
            const b = e.target.closest('button');
            if (!b) return;
            if (b.dataset.act === 'reset') {
                state = resolve(start);
                close();
                emit();
                return;
            }
            // Ein eigener Zeitraum wird bewusst bestätigt -- zwei Datumsfelder
            // sind zwei Eingaben, und nach der ersten waere jede Ladung falsch.
            const f = fromEl.value || '';
            const t = toEl.value || '';
            if (f && t && f > t) {
                if (window.Toast) Toast.error('„Von" liegt nach „Bis"');
                return;
            }
            if (!f && !t) { close(); return; }
            state = resolve('custom', f, t);
            close();
            emit();
        });

        // Beim Einhaengen einmal melden: die Seite laedt damit ihren ersten
        // Zeitraum, ohne ihn selbst zu kennen. `fire: false` unterdrueckt das.
        paint();
        if (opts.fire !== false) emit();
        return {
            get: () => Object.assign({}, state),
            set: (preset, from, to) => { state = resolve(preset, from, to); emit(); },
            el: wrap,
        };
    }

    /* Für Endpunkte, die nur eine Tageszahl kennen: erst mit `days` laden,
       dann hier auf das gewählte Fenster zuschneiden. */
    function clip(rows, fields, range) {
        if (!Array.isArray(rows) || !range) return rows || [];
        if (!range.from && !range.to) return rows;
        const list = Array.isArray(fields) ? fields : [fields];
        return rows.filter(r => {
            if (!r) return false;
            let raw = null;
            for (const f of list) { if (r[f]) { raw = r[f]; break; } }
            if (!raw) return false;
            const day = String(raw).slice(0, 10);
            if (range.from && day < range.from) return false;
            if (range.to && day > range.to) return false;
            return true;
        });
    }

    window.VexRange = { mount, resolve, clip, PRESETS, DEFAULT_PRESET };
})();
