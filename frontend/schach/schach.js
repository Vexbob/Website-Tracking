/* schach.js — v1.95.0
 *
 * Wertungsverlauf, Bilanz und Partien von Lichess und Chess.com.
 *
 * Der Ueberblick beantwortet vier Fragen, und zwar alle vier ueber DENSELBEN
 * Zeitraum -- der Knopf oben gilt fuer die ganze Seite:
 *
 *   1. **Wo stehe ich, und wohin geht es?** Der Wertungsverlauf, je Disziplin
 *      eine eigene kleine Kurve, beide Plattformen darin. Vorher war das ein
 *      Diagramm mit einem Umschalter aus sechs Disziplinen: man musste
 *      fuenfmal klicken, um zu sehen, was jetzt nebeneinander steht.
 *   2. **Wie steht es?** Bilanz und Form.
 *   3. **Wann lief es?** Die Aktivitaet je Tag, Woche oder Monat, nach
 *      Ergebnis gestapelt -- eine Siegquote allein sagt nie, wann sie entstand.
 *   4. **Gegen wen?** Die Gegnerstaerke: 60 % gegen Schwaechere und 60 %
 *      gegen Staerkere sind nicht dasselbe. Dazu die Ranglisten.
 *
 * Fuenf Eigenheiten, die dieses Modul von den anderen unterscheiden:
 *
 *   - **Die Daten liegen woanders.** Beide Plattformen geben sie oeffentlich
 *     heraus; hinterlegt wird nur ein Benutzername. Deshalb gibt es hier kein
 *     Formular zum Eintragen von Partien -- nur einen Knopf, der holt.
 *   - **Der Import laeuft in Stuecken.** Der Server holt je Aufruf ein Stueck
 *     und sagt, ob noch mehr kommt; diese Seite ruft in einer Schleife, zeigt
 *     den Stand mit und laesst sich jederzeit anhalten.
 *   - **Den Verlauf gibt es nur hier.** Beide Plattformen kennen nur den
 *     aktuellen Stand. Der Verlauf entsteht aus den Partien selbst: jede
 *     gewertete Partie traegt die eigene Wertung, und daraus wird eine Kurve
 *     ueber die ganze Spielzeit. Die Tageszeilen je Abruf fuellen, was keine
 *     Partie hergibt -- Tage ohne Spiel und die Raetsel-Wertung.
 *   - **Gerechnet wird im Server.** Die Seite bekommt eine fertige Auswertung
 *     ueber den ganzen Bestand (``/api/chess/stats``) statt selbst ueber die
 *     zuletzt geladenen Partien zu rechnen. Vorher standen auf einem
 *     Bildschirm zwei Grundgesamtheiten nebeneinander.
 *   - **Nicht jede Zahl bedeutet dasselbe.** Chess.com gibt zur
 *     Raetsel-Wertung nur den Bestwert heraus und zu keiner Partie eine
 *     Wertungsdifferenz. Beides steht dabei, statt dass eine Luecke wie eine
 *     Null aussieht.
 */

const API = {
    konten:    ()     => apiCall('/api/chess/accounts'),
    // Das Objekt bleibt ein Objekt: apiCall schickt einen fertigen String als
    // Formulardaten, ein Plain-Object dagegen als JSON -- und der Endpunkt
    // erwartet JSON.
    verbinden: (p, n) => apiCall('/api/chess/accounts', {
        method: 'POST', body: { platform: p, username: n } }),
    loesen:    (id)   => apiCall('/api/chess/accounts/' + id, { method: 'DELETE' }),
    aktualisieren: () => apiCall('/api/chess/refresh', { method: 'POST' }),
    holen:     (id)   => apiCall('/api/chess/import?account_id=' + id, { method: 'POST' }),
    vonVorn:   (id)   => apiCall('/api/chess/import/reset?account_id=' + id, { method: 'POST' }),
    partien:   (qs)   => apiCall('/api/chess/games' + qs),
    stats:     (qs)   => apiCall('/api/chess/stats' + qs),
    summary:   ()     => apiCall('/api/chess/summary'),
    setzen:    (d)    => apiCall('/api/chess/settings', { method: 'PUT', body: d }),
};

const PLATTFORMEN = [
    { key: 'chesscom', label: 'Chess.com', hinweis: 'Benutzername auf chess.com' },
    { key: 'lichess',  label: 'Lichess',   hinweis: 'Benutzername auf lichess.org' },
];
const LABEL = { lichess: 'Lichess', chesscom: 'Chess.com' };

const TABS = ['ueberblick', 'partien', 'konten'];
const SEITE = 50;

const state = {
    konten: [], arten: [], einstellungen: null,
    stats: null,                   // die Auswertung des gewaehlten Zeitraums
    gezeigt: [],                   // die Partien, die gerade in der Liste stehen
    offset: 0,
    laeuft: false, stopp: false,
    range: null, rangeMount: null, filterFeldZu: null,
    statsLauf: null, statsQs: null,
    charts: { verlauf: [], aktivitaet: null, staerke: null },
    filter: { platform: '', result: '', perf: '', rated: '', q: '',
              sort: 'datum', direction: 'desc' },
    takt: null,
};

/* ------------------------------------------------------------- Werkzeug */

const esc = (v) => String(v == null ? '' : v)
    .replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

// Die Zahlen- und Diagrammfarbe: ohne eigenes Preset faellt sie auf den
// Modulton zurueck (DESIGN.md 3).
const figurFarbe = () => cssVar('--figure') || cssVar('--m-schach');
const plattformFarbe = (p) => p === 'chesscom' ? cssVar('--chart-6') : figurFarbe();
const plattformTon = (p) => p === 'chesscom' ? 'var(--sch-chesscom)' : 'var(--sch-lichess)';

const melde = (text, art) => { if (window.Toast) Toast[art || 'info'](text); };

const zahl = (n) => Number(n || 0).toLocaleString('de-DE');
// Eine Wertungszahl wird ohne Tausenderpunkt geschrieben -- "1.721" liest
// niemand, der Schach spielt.
const wertung = (n) => String(n == null ? '–' : n);
const anteil = (teil, ganz) => ganz ? Math.round((teil / ganz) * 100) : 0;
// So zaehlt es die Schachwelt: ein Remis ist ein halber Punkt.
const punktequote = (t) => t.partien
    ? Math.round(((t.siege + t.remis / 2) / t.partien) * 100) : 0;

function datum(iso, mitZeit) {
    if (!iso) return '–';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '–';
    const t = d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
    return mitZeit ? t + ' ' + d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' }) : t;
}

const ERGEBNIS_LABEL = { sieg: 'Sieg', remis: 'Remis', niederlage: 'Niederlage' };
const ERGEBNIS_KURZ  = { sieg: 'S', remis: 'R', niederlage: 'N' };
const ergebnisTon = (r) => r === 'sieg' ? 'var(--ok)'
    : (r === 'niederlage' ? 'var(--danger)' : 'var(--text-3)');

/* Die Beschriftung einer Disziplin steht am Server. Hier wird sie nur
   nachgeschlagen, damit keine zweite Liste entsteht, die auseinanderlaufen
   kann. */
function perfLabel(perf) {
    const karte = (state.stats && state.stats.perf_labels) || {};
    if (karte[perf]) return karte[perf];
    const art = state.arten.find(a => a.perf === perf);
    if (art) return art.label;
    for (const k of state.konten) {
        const r = (k.ratings || []).find(x => x.perf === perf);
        if (r && r.label) return r.label;
    }
    return perf || '–';
}

function vorTagen(iso) {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    const tage = Math.floor((Date.now() - d.getTime()) / 86400000);
    if (tage <= 0) return 'heute';
    if (tage === 1) return 'gestern';
    return 'vor ' + tage + ' Tagen';
}

/* -------------------------------------------------------- Leerer Zustand */

function leerKarte(mark, text, knopf) {
    return `<div class="empty">
        <span class="empty-mark" aria-hidden="true">${mark}</span>
        <p class="empty-text">${text}</p>
        ${knopf || ''}
    </div>`;
}

/* Ein leerer Zeitraum ist etwas anderes als ein leerer Bestand: der eine
   loest sich mit einem anderen Zeitraum, der andere mit einem Import. Die
   beiden Saetze auseinanderzuhalten ist der Unterschied zwischen "hier ist
   nichts" und "hier ist nichts, und deshalb". */
function leerImZeitraum(mark, was) {
    const s = state.stats;
    if (s && s.erste_partie) {
        return leerKarte(mark, `Zwischen ${datum(s.von)} und ${datum(s.bis)} liegt keine
            Partie — ${was} braucht welche. Die erste im Bestand ist vom
            ${datum(s.erste_partie)}; ein anderer Zeitraum oben zeigt mehr.`);
    }
    return leerKarte(mark,
        'Noch keine Partien im Bestand. Sie werden nicht von Hand erfasst, sondern unter '
        + '<strong>Konten</strong> von der Plattform geholt.',
        '<button type="button" class="v-btn v-btn--sm" data-zu-konten>Zu den Konten</button>');
}

/* Ein Klick auf "Zu den Konten" gibt es in mehreren leeren Karten -- gebunden
   wird er an einer Stelle, nach jedem Zeichnen. */
function bindeKontenKnoepfe(wurzel) {
    (wurzel || document).querySelectorAll('[data-zu-konten]').forEach(b => {
        if (b.dataset.gebunden) return;
        b.dataset.gebunden = '1';
        b.addEventListener('click', () => activateTab('konten'));
    });
}

/* --------------------------------------------------------- Diagramm-Basis */

/* Tooltip und Achsen sehen in jedem Diagramm dieser Seite gleich aus
   (DESIGN.md 7). Zwei Fassungen davon waeren zwei Diagrammsprachen in einer
   Karte. */
function tooltipStil(extra) {
    return Object.assign({
        backgroundColor: cssVar('--surface-3'),
        borderColor: cssVar('--line-strong'), borderWidth: 1,
        titleColor: cssVar('--text-1'), bodyColor: cssVar('--text-2'),
        cornerRadius: 12, padding: 10, displayColors: true,
    }, extra || {});
}

function achseX(extra) {
    return Object.assign({
        ticks: { color: cssVar('--chart-axis'), font: { size: 11 }, maxRotation: 0,
                 autoSkipPadding: 16 },
        grid: { display: false }, border: { display: false },
    }, extra || {});
}

function achseY(extra) {
    return Object.assign({
        ticks: { color: cssVar('--chart-axis'), font: { size: 11 }, maxTicksLimit: 6 },
        grid: { color: cssVar('--chart-grid') }, border: { display: false },
    }, extra || {});
}

/* Kurze Beschriftung fuer die Achse, ausgeschriebene fuer den Tooltip
   (DESIGN.md 7: im Tooltip steht immer die Jahreszahl). Bei Wochen und
   Monaten sagt die lange Fassung auch, dass eine Periode gemeint ist und
   nicht ein Tag. */
function achsenTexte(achse, koernung) {
    const kurz = [], voll = [];
    (achse || []).forEach(iso => {
        const tag = iso.slice(8, 10) + '.' + iso.slice(5, 7) + '.';
        if (koernung === 'monat') {
            const d = new Date(iso + 'T00:00:00');
            kurz.push(isNaN(d.getTime()) ? iso
                : d.toLocaleDateString('de-DE', { month: 'short', year: '2-digit' }));
            voll.push(VexCharts.fullMonth(iso.slice(0, 7)));
        } else if (koernung === 'woche') {
            kurz.push(tag);
            voll.push('Woche ab ' + VexCharts.fullDay(iso));
        } else {
            kurz.push(tag);
            voll.push(VexCharts.fullDay(iso));
        }
    });
    return { kurz, voll };
}

const KOERNUNG_WORT = { tag: 'je Tag', woche: 'je Woche', monat: 'je Monat' };

/* Verlauf von 18 % auf 0 % derselben Farbe (DESIGN.md 7). */
function flaeche(ctx, farbe) {
    const chart = ctx.chart;
    if (!chart.chartArea || !/^#[0-9a-f]{6}$/i.test(farbe)) return 'transparent';
    const g = chart.ctx.createLinearGradient(0, chart.chartArea.top, 0, chart.chartArea.bottom);
    g.addColorStop(0, farbe + '2e');
    g.addColorStop(1, farbe + '00');
    return g;
}

/* ------------------------------------------------------------- Überblick */

function zeichneUeberblick() {
    const leer = document.getElementById('schLeer');
    const box = document.getElementById('schUeberblick');

    if (!state.konten.length) {
        box.hidden = true;
        leer.hidden = false;
        leer.innerHTML = `<div class="v-card">${leerKarte('♟️',
            'Noch ist nichts verbunden. Vexbob holt Wertungszahlen und Partien bei Lichess und '
            + 'Chess.com ab — dafür reicht der Benutzername, ein Passwort braucht es nicht.',
            '<button type="button" class="v-btn v-btn--primary" data-zu-konten>Konto verbinden</button>')}</div>`;
        bindeKontenKnoepfe(leer);
        return;
    }
    leer.hidden = true;
    box.hidden = false;
    zeichneKopfleiste();
    mountRange();
}

/* Die Kopfleiste sagt, worueber die Seite gerade rechnet. Ohne diesen Satz
   waeren dieselben Karten mit "30 Tage" und mit "Gesamt" nicht zu
   unterscheiden. */
function zeichneKopfleiste() {
    const s = state.stats;
    const zeitraum = document.getElementById('schZeitraum');
    const stand = document.getElementById('schStand');
    if (s) {
        zeitraum.textContent = s.ganzer_bestand
            ? `Alle Partien seit ${datum(s.erste_partie)}`
            : `${datum(s.von)} bis ${datum(s.bis)}`;
    }
    const zuletzt = state.konten.map(k => k.ratings_at).filter(Boolean).sort().slice(-1)[0];
    stand.textContent = zuletzt ? 'Wertungen abgerufen ' + datum(zuletzt, true) : '';
}

/* Wenn die Auswertung nicht kommt, soll die Seite das SAGEN und nicht in
   Skeletons stehenbleiben. Ein Ladezustand, der nie endet, sieht aus wie ein
   kaputter Browser -- und man wartet auf etwas, das nicht mehr kommt.
   Deshalb tritt der ganze Ueberblick beiseite und es steht ein Satz da, der
   sagt, was los ist, mit einem Knopf, der es noch einmal versucht. */
function zeigeStatsFehler(text) {
    const leer = document.getElementById('schLeer');
    document.getElementById('schUeberblick').hidden = true;
    leer.hidden = false;
    leer.innerHTML = `<div class="v-card"><div class="empty is-error">
        <span class="empty-mark" aria-hidden="true">⚠️</span>
        <p class="empty-text">${esc(text)}</p>
        <button type="button" class="v-btn v-btn--primary" id="schNochmal">Erneut versuchen</button>
    </div></div>`;
    const knopf = document.getElementById('schNochmal');
    if (knopf) knopf.addEventListener('click', async () => {
        knopf.classList.add('is-loading');
        // Ohne Konten ist die Auswertung gar nicht angelaufen -- dann muss
        // der Knopf von vorn anfangen und nicht nur nachladen.
        if (!state.konten.length) await ladeSummary();
        else await ladeStats();
    });
}

/* Aus der Meldung des Servers einen Satz machen, der weiterhilft. Ein
   fehlender Endpunkt heisst hier fast immer dasselbe: das Frontend liegt
   schon neu auf dem Server, das Backend laeuft noch in der alten Fassung. */
function statsFehlerText(err) {
    const roh = (err && err.message) || '';
    if (/404|not found/i.test(roh)) {
        return 'Die Auswertung kennt der Server noch nicht. Auf dem Server läuft '
            + 'vermutlich noch die vorherige Fassung des Backends — dort fehlt ein '
            + 'Neustart.';
    }
    if (/netzwerkfehler/i.test(roh)) {
        return 'Keine Verbindung zum Server. Sobald er wieder antwortet, hilft ein '
            + 'Klick auf „Erneut versuchen“.';
    }
    return 'Die Auswertung konnte nicht geladen werden'
        + (roh ? ' (' + roh + ').' : '.');
}

function zeichneAlles() {
    zeichneKopfleiste();
    zeichneKpi();
    zeichneVerlauf();
    zeichneBilanz();
    zeichneForm();
    zeichneAktivitaet();
    zeichneStaerke();
    zeichneArten();
    zeichneEroeffnungen();
    zeichneGegner();
}

/* Die Summe ueber alle Plattformen -- an mehreren Stellen gebraucht, deshalb
   einmal gerechnet. */
function gesamtBilanz() {
    return (state.stats ? state.stats.plattformen : []).reduce((a, b) => ({
        partien: a.partien + (b.partien || 0), siege: a.siege + (b.siege || 0),
        remis: a.remis + (b.remis || 0), niederlagen: a.niederlagen + (b.niederlagen || 0),
    }), { partien: 0, siege: 0, remis: 0, niederlagen: 0 });
}

/* Die fuehrende Reihe: die Disziplin und Plattform mit den meisten Punkten im
   Zeitraum. Sie traegt die Kopfzahl "Wertung" -- eine Zahl aus einer
   Disziplin, in der drei Partien liegen, waere die falsche Antwort auf "wie
   hat sich meine Wertung entwickelt". */
function fuehrendeReihe() {
    const reihen = (state.stats && state.stats.verlauf) ? state.stats.verlauf.reihen : [];
    let beste = null;
    reihen.forEach(r => {
        if (!r.punkte) return;
        if (!beste || r.punkte > beste.punkte) beste = r;
    });
    return beste;
}

/* ----------------------------------------------------------- Kopfzahlen */

function kpiKarte(icon, label, wert, sub, ton) {
    return `<div class="stat-kpi">
        <div class="stat-kpi-icon" aria-hidden="true">${icon}</div>
        <div class="stat-kpi-label">${label}</div>
        <div class="stat-kpi-value"${ton ? ` style="color:${ton}"` : ''}>${wert}</div>
        <div class="stat-kpi-sub">${sub || ''}</div>
    </div>`;
}

function zeichneKpi() {
    const ziel = document.getElementById('schKpi');
    const s = state.stats;
    if (!s) { ziel.innerHTML = ''; return; }

    const g = gesamtBilanz();
    const wochen = Math.max(1, s.tage / 7);
    const karten = [];

    karten.push(kpiKarte('♟️', 'Partien', zahl(g.partien),
        g.partien ? `Ø ${(g.partien / wochen).toFixed(1)} pro Woche` : 'in diesem Zeitraum'));

    karten.push(kpiKarte('⚖️', 'Punktequote', g.partien ? punktequote(g) + ' %' : '–',
        g.partien ? `${anteil(g.siege, g.partien)} % gewonnen · Remis zählt halb`
                  : 'Remis zählt halb'));

    // Die Wertungsentwicklung im Zeitraum, aus der fuehrenden Reihe.
    const f = fuehrendeReihe();
    if (f) {
        const basis = f.start != null ? f.start : f.erste;
        const delta = (f.letzte != null && basis != null) ? f.letzte - basis : null;
        karten.push(kpiKarte('📈', 'Wertung',
            delta == null ? wertung(f.letzte)
                : (delta > 0 ? '+' + delta : (delta < 0 ? '−' + Math.abs(delta) : '±0')),
            `${esc(f.label)} auf ${esc(LABEL[f.platform] || f.platform)}`
                + (basis != null && f.letzte != null ? ` · ${basis} → ${f.letzte}` : ''),
            delta == null || delta === 0 ? '' : (delta > 0 ? 'var(--ok)' : 'var(--danger)')));
    } else {
        karten.push(kpiKarte('📈', 'Wertung', '–', 'in diesem Zeitraum keine gewertete Partie'));
    }

    const stark = s.staerkster_sieg;
    karten.push(kpiKarte('👥', 'Ø Gegner', s.gegner_schnitt ? wertung(s.gegner_schnitt) : '–',
        stark ? `Stärkster Sieg: ${wertung(stark.opponent_rating)} gegen ${esc(stark.opponent)}`
              : 'noch kein Sieg mit bekannter Gegnerwertung'));

    ziel.innerHTML = karten.join('');
}

/* --------------------------------------------------------------- Verlauf */

function mountRange() {
    if (state.rangeMount) return;
    const host = document.getElementById('schRange');
    if (!host) return;
    // Der Zeitraum-Knopf meldet beim Einhaengen einmal -- das ist die erste
    // Ladung der Auswertung. Kein eigenes Preset: ohne ausdruecklichen Wunsch
    // gilt die Einstellung des Kontos (ui_default_range), wie in jedem
    // anderen Modul.
    state.rangeMount = VexRange.mount(host, {
        onChange: (r) => { state.range = r; ladeStats(); },
    });
}

function zerstoereVerlaufCharts() {
    state.charts.verlauf.forEach(c => { try { c.destroy(); } catch (e) { /* weg */ } });
    state.charts.verlauf = [];
}

/* Die Bestwerte -- bei Chess.com ist die Raetsel-Wertung nur als Hoechstwert
   zu haben. Sie gehoert nicht in eine Kurve, aber sie ist eine Zahl, die man
   sehen will. */
function bestwertZeilen() {
    const raus = [];
    state.konten.forEach(k => (k.ratings || []).forEach(r => {
        if (r.is_best) raus.push({ platform: k.platform, perf: r.perf,
                                   label: r.label, rating: r.rating });
    }));
    return raus;
}

function zeichneVerlauf() {
    const ziel = document.getElementById('schVerlauf');
    const note = document.getElementById('schVerlaufNote');
    const legende = document.getElementById('schLegende');
    zerstoereVerlaufCharts();

    const s = state.stats;
    if (!s) { ziel.innerHTML = '<span class="skel skel-block"></span>'; return; }

    const verlauf = s.verlauf || { achse: [], reihen: [] };
    const reihen = verlauf.reihen || [];
    const bestwerte = bestwertZeilen();

    // Welche Plattformen ueberhaupt vorkommen -- die Legende steht einmal
    // oben statt in jeder der kleinen Kurven.
    const plattformen = [...new Set(reihen.map(r => r.platform))];
    legende.innerHTML = plattformen.length < 2 ? '' : plattformen.map(p =>
        `<span class="sch-leg"><span class="sch-dot" data-platform="${esc(p)}"
            aria-hidden="true"></span>${esc(LABEL[p] || p)}</span>`).join('');

    if (!reihen.length && !bestwerte.length) {
        ziel.innerHTML = leerKarte('📈',
            'Für den Verlauf fehlen gewertete Partien. Er entsteht aus ihnen: jede Partie '
            + 'trägt die Wertung, die danach galt — geholt werden sie unter '
            + '<strong>Konten</strong>.',
            '<button type="button" class="v-btn v-btn--sm" data-zu-konten>Zu den Konten</button>');
        bindeKontenKnoepfe(ziel);
        note.textContent = '';
        return;
    }

    // Je Disziplin ein Kaestchen, in der Reihenfolge des Servers.
    const ordnung = s.perfs || [];
    const rang = (p) => { const i = ordnung.indexOf(p); return i < 0 ? 99 : i; };
    const arten = [...new Set(reihen.map(r => r.perf))].sort((a, b) => rang(a) - rang(b));

    const kaesten = arten.map(perf => kastenHtml(perf, reihen.filter(r => r.perf === perf)));
    // Bestwerte bekommen ein eigenes Kaestchen, auch wenn dieselbe Disziplin
    // auf der anderen Plattform eine Kurve hat: eine Zahl, die "jemals"
    // bedeutet, darf nicht als Punkt in einer Kurve landen, die "heute"
    // bedeutet — verschweigen will man sie deswegen trotzdem nicht.
    bestwerte.forEach(b => {
        kaesten.push(`<div class="sch-vk">
            <div class="sch-vk-kopf">
                <span class="sch-vk-name">${esc(b.label || perfLabel(b.perf))} · Bestwert</span>
                <span class="sch-vk-zahlen">
                    <span class="sch-vk-zahl" style="--ton:${plattformTon(b.platform)}"
                        >${wertung(b.rating)}</span>
                </span>
            </div>
            <p class="sch-vk-satz">Bestwert auf ${esc(LABEL[b.platform] || b.platform)}.
                Den heutigen Stand gibt die Plattform hier nicht heraus — und ein Bestwert
                kann sich nur nach oben bewegen.</p>
        </div>`);
    });

    ziel.innerHTML = kaesten.join('');

    // Erst nach dem Einhaengen zeichnen: vorher hat das Canvas keine Groesse.
    const texte = achsenTexte(verlauf.achse, s.koernung);
    arten.forEach(perf => {
        const eigene = reihen.filter(r => r.perf === perf);
        if (!eigene.some(r => r.punkte > 1)) return;
        const canvas = document.getElementById('schVk_' + perf);
        if (canvas) state.charts.verlauf.push(miniVerlauf(canvas, eigene, texte));
    });

    const wort = s.koernung === 'tag' ? ''
        : ` Bei diesem Zeitraum steht ${KOERNUNG_WORT[s.koernung]} der letzte Stand.`;
    note.innerHTML = 'Gerechnet aus jeder gewerteten Partie — gezeigt wird die Wertung '
        + '<em>nach</em> der Partie. An Tagen ohne Partie gilt der letzte bekannte Stand '
        + 'weiter: eine Wertungszahl bewegt sich nur, wenn gespielt wurde.' + wort
        + reichweiteSatz();
}

/* Wie weit die Kurven zurueckreichen -- und warum nicht weiter.
   Der Verlauf steht auf den geholten Partien: er beginnt, wo die aelteste
   von ihnen liegt, nicht wo das Konto beginnt. Solange die Historie noch
   nicht ganz da ist, ist das der wichtigste Satz auf der Seite: sonst sieht
   ein halb geholter Bestand aus wie ein Nutzer, der erst seit vorgestern
   spielt. */
function reichweiteSatz() {
    const s = state.stats;
    const ab = s && s.erste_partie ? datum(s.erste_partie) : null;
    const offen = (state.konten || []).filter(k => k.games_count && !k.backfill_done);
    let text = ab
        ? ` Die Kurven beginnen mit der ältesten geholten Partie (${ab}).`
        : '';
    if (offen.length) {
        text += ` <strong>Von ${offen.map(k => esc(LABEL[k.platform] || k.platform)).join(' und ')}`
            + ' ist die Historie noch nicht vollständig geholt</strong> — bis dahin ist die Kurve'
            + ' kürzer als deine Spielzeit. Unter <em>Konten</em> weiterholen.';
    }
    return text;
}

/* Ein Kaestchen je Disziplin: Name, aktuelle Zahl je Plattform, Entwicklung,
   darunter die Kurve. Ohne Kurve, wenn es nichts zu zeichnen gibt -- eine
   waagerechte Linie ueber einen Zeitraum ohne Partie sieht aus wie ein
   kaputtes Diagramm, und genau das war sie vorher auch. */
function kastenHtml(perf, eigene) {
    const label = eigene[0].label || perfLabel(perf);
    const fuehrend = eigene.slice().sort((a, b) => b.punkte - a.punkte)[0];
    const basis = fuehrend.start != null ? fuehrend.start : fuehrend.erste;
    const delta = (fuehrend.punkte && fuehrend.letzte != null && basis != null)
        ? fuehrend.letzte - basis : null;

    const zahlen = eigene.map(r => `<span class="sch-vk-zahl"
        style="--ton:${plattformTon(r.platform)}"
        title="${esc(LABEL[r.platform] || r.platform)}">${wertung(r.letzte)}</span>`).join('');

    const marke = delta == null || delta === 0 ? ''
        : `<span class="sch-trend is-${delta > 0 ? 'hoch' : 'runter'}">${
            delta > 0 ? '▲ +' : '▼ −'}${Math.abs(delta)}</span>`;

    const kopf = `<div class="sch-vk-kopf">
        <span class="sch-vk-name">${esc(label)}</span>
        <span class="sch-vk-zahlen">${zahlen}</span>
        ${marke}
    </div>`;

    const gespielt = eigene.reduce((a, r) => a + r.punkte, 0);
    if (!eigene.some(r => r.punkte > 1)) {
        // Zwei Gruende, zwei Saetze. Sie saehen sonst beide aus wie "keine Daten".
        const satz = !gespielt
            ? `In diesem Zeitraum nicht gespielt — die Zahl steht seitdem unverändert.`
            : `Genau eine gewertete Partie in diesem Zeitraum. Eine Kurve braucht zwei Punkte.`;
        return `<div class="sch-vk">${kopf}<p class="sch-vk-satz">${satz}</p></div>`;
    }

    const hoch = eigene.map(r => r.hoch).filter(Boolean)
        .sort((a, b) => b.rating - a.rating)[0];
    return `<div class="sch-vk">${kopf}
        <div class="sch-vk-kurve"><canvas id="schVk_${esc(perf)}"></canvas></div>
        <div class="sch-vk-fuss">${zahl(gespielt)} ${gespielt === 1 ? 'Tag' : 'Tage'} mit Partie${
            hoch ? ` · höchster Stand ${hoch.rating} am ${datum(hoch.tag)}` : ''}</div>
    </div>`;
}

function miniVerlauf(canvas, eigene, texte) {
    const einzeln = eigene.length === 1;
    const datasets = eigene.map(r => {
        const farbe = plattformFarbe(r.platform);
        return {
            label: LABEL[r.platform] || r.platform,
            data: r.werte,
            borderColor: farbe,
            // Flaeche unter der Linie nur bei einer einzigen Reihe -- zwei
            // sich ueberlagernde Fuellungen ergeben eine dritte Farbe, die
            // nichts bedeutet.
            fill: einzeln,
            backgroundColor: einzeln ? (ctx) => flaeche(ctx, farbe) : undefined,
            tension: 0.3, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4,
            spanGaps: false,
            order: VexCharts.ORDER.VALUE,
        };
    });

    return new Chart(canvas, {
        type: 'line',
        data: { labels: texte.kurz, datasets },
        options: VexCharts.applyFullDates({
            maintainAspectRatio: false,
            animation: { duration: 200 },
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: tooltipStil({
                    callbacks: {
                        title: VexCharts.titleFrom(texte.voll),
                        label: (item) => item.parsed.y == null ? null
                            : ' ' + item.dataset.label + ': ' + item.parsed.y,
                    },
                }),
            },
            scales: {
                x: achseX({ ticks: { color: cssVar('--chart-axis'), font: { size: 10 },
                                     maxRotation: 0, autoSkipPadding: 24, maxTicksLimit: 6 } }),
                y: achseY({ ticks: { color: cssVar('--chart-axis'), font: { size: 10 },
                                     maxTicksLimit: 4 }, beginAtZero: false }),
            },
        }, texte.voll),
    });
}

/* ---------------------------------------------------------------- Bilanz */

function zeichneBilanz() {
    const ziel = document.getElementById('schBilanz');
    const sub = document.getElementById('schBilanzSub');
    const s = state.stats;
    if (!s) { ziel.innerHTML = '<span class="skel skel-block"></span>'; return; }

    const g = gesamtBilanz();
    if (!g.partien) {
        sub.textContent = '';
        ziel.innerHTML = leerImZeitraum('⚖️', 'eine Bilanz');
        bindeKontenKnoepfe(ziel);
        return;
    }

    sub.textContent = `${zahl(g.partien)} Partien`;
    ziel.innerHTML = `
        <div class="sch-quote">
            <span class="sch-quote-num">${punktequote(g)} %</span>
            <span class="sch-quote-lbl">Punktequote<br>
                <span style="color:var(--text-4)">${anteil(g.siege, g.partien)} % gewonnen,
                    Remis zählt halb</span></span>
        </div>
        ${balken(g, 'gross')}
        <div class="sch-bilanz-zahlen">
            <span class="is-sieg">${zahl(g.siege)} Siege</span>
            <span class="is-remis">${zahl(g.remis)} Remis</span>
            <span class="is-verlust">${zahl(g.niederlagen)} Niederlagen</span>
        </div>
        ${s.plattformen.length < 2 ? '' : s.plattformen.map(b => `
            <div class="sch-bilanz">
                <div class="sch-bilanz-kopf">
                    <span class="sch-dot" data-platform="${esc(b.platform)}" aria-hidden="true"></span>
                    <strong>${esc(LABEL[b.platform] || b.platform)}</strong>
                    <span class="sch-bilanz-zeit">${zahl(b.partien)} Partien</span>
                </div>
                ${balken(b)}
                <div class="sch-bilanz-zahlen">
                    <span class="is-sieg">${anteil(b.siege, b.partien)} % gewonnen</span>
                    <span>Punktequote ${punktequote(b)} %</span>
                </div>
            </div>`).join('')}`;
}

function balken(b, gross) {
    const g = b.partien || 1;
    const t = (n) => anteil(n, g);
    return `<div class="sch-balken${gross ? ' sch-balken--gross' : ''}" role="img"
         aria-label="${b.siege} Siege, ${b.remis} Remis, ${b.niederlagen} Niederlagen">
        <span class="sch-teil is-sieg" style="width:${t(b.siege)}%"></span>
        <span class="sch-teil is-remis" style="width:${t(b.remis)}%"></span>
        <span class="sch-teil is-verlust" style="width:${t(b.niederlagen)}%"></span>
    </div>`;
}

/* ------------------------------------------------------------------ Form */

/* Die Form: die Strecke, nicht die Summe. Eine Reihe aus Marken liest sich
   schneller als "13 Siege, 3 Remis, 4 Niederlagen" -- und darunter steht die
   Zahl, die man danach erzaehlt: die laufende Serie. */
function zeichneForm() {
    const ziel = document.getElementById('schForm');
    const s = state.stats;
    if (!s) { ziel.innerHTML = '<span class="skel skel-block"></span>'; return; }

    const spiele = s.form || [];
    if (!spiele.length) {
        ziel.innerHTML = leerImZeitraum('🔥', 'die Form');
        bindeKontenKnoepfe(ziel);
        return;
    }

    const serie = s.serie;
    const wort = serie && (serie.art === 'sieg' ? 'gewonnen'
        : serie.art === 'remis' ? 'remis' : 'verloren');

    // Jede Marke traegt ihre eigene Beschriftung: ein role="img" mit einer
    // Sammelbeschriftung waere hier falsch, weil die Marken anklickbar sind
    // -- Vorlesehilfen verstecken alles, was in einem Bild liegt.
    const marke = (g) => `${ERGEBNIS_LABEL[g.result] || 'Partie'} gegen `
        + `${g.opponent || 'Unbekannt'} · ${datum(g.played_at)}`;
    ziel.innerHTML = `
        <div class="sch-pips">
            ${spiele.map(g => `<button type="button" class="sch-pip is-${esc(g.result)}"
                data-pip="${esc(g.opponent || '')}"
                aria-label="${esc(marke(g))}" title="${esc(marke(g))}"></button>`).join('')}
        </div>
        <p class="sch-serie">${serie
            ? `Zuletzt <strong>${serie.n}${serie.offen ? '+' : ''}
               ${serie.n === 1 ? 'Partie' : 'Partien'}</strong> in Folge ${wort},
               die letzte ${esc(vorTagen(spiele[0].played_at))}.` : ''}</p>
        <p class="sch-note">Die Reihe zeigt die letzten ${spiele.length} Partien des Zeitraums,
            neueste links. Ein Tippen sucht den Gegner in den Partien.</p>`;

    ziel.querySelectorAll('[data-pip]').forEach(b => b.addEventListener('click', () => {
        if (b.dataset.pip) sucheInPartien(b.dataset.pip);
    }));
}

/* ------------------------------------------------------------ Aktivität */

/* Wie viel gespielt wurde und wie es ausging -- gestapelt, weil beides
   dieselbe Saeule ist: die Hoehe ist die Menge, die Aufteilung das Ergebnis. */
function zeichneAktivitaet() {
    const box = document.getElementById('schAktivitaetBox');
    const leer = document.getElementById('schAktivitaetLeer');
    const sub = document.getElementById('schAktivitaetSub');
    if (state.charts.aktivitaet) { state.charts.aktivitaet.destroy(); state.charts.aktivitaet = null; }

    const s = state.stats;
    if (!s) return;
    const liste = s.aktivitaet || [];
    const g = gesamtBilanz();

    if (!g.partien) {
        box.hidden = true;
        leer.hidden = false;
        leer.innerHTML = leerImZeitraum('📊', 'dieses Diagramm');
        bindeKontenKnoepfe(leer);
        sub.textContent = '';
        return;
    }
    leer.hidden = true;
    box.hidden = false;

    const beste = liste.reduce((a, b) => (b.partien > (a ? a.partien : -1) ? b : a), null);
    sub.textContent = KOERNUNG_WORT[s.koernung]
        + (beste && beste.partien ? ` · am meisten: ${zahl(beste.partien)} Partien` : '');

    const texte = achsenTexte(liste.map(p => p.eimer), s.koernung);
    const reihe = (name, feld, farbe) => ({
        label: name, data: liste.map(p => p[feld]),
        backgroundColor: farbe, borderRadius: 6, borderSkipped: false,
        maxBarThickness: 48, order: VexCharts.ORDER.VALUE,
    });

    state.charts.aktivitaet = new Chart(document.getElementById('schAktivitaetChart'), {
        type: 'bar',
        data: {
            labels: texte.kurz,
            datasets: [
                reihe('Siege', 'siege', cssVar('--ok')),
                reihe('Remis', 'remis', cssVar('--text-4')),
                reihe('Niederlagen', 'niederlagen', cssVar('--danger')),
            ],
        },
        options: VexCharts.applyFullDates({
            maintainAspectRatio: false,
            animation: { duration: 200 },
            interaction: { mode: 'index', intersect: false },
            plugins: {
                // Drei Reihen, die man nicht am Punkt beschriften kann
                // (DESIGN.md 7) -- hier gehoert eine Legende hin.
                legend: { display: true, position: 'top',
                          labels: { color: cssVar('--text-3'), font: { size: 11 },
                                    boxWidth: 10, boxHeight: 10, usePointStyle: true,
                                    pointStyle: 'circle' } },
                tooltip: tooltipStil({
                    callbacks: {
                        title: VexCharts.titleFrom(texte.voll),
                        label: (i) => ' ' + i.dataset.label + ': ' + i.parsed.y,
                        footer: (items) => {
                            const i = items[0].dataIndex;
                            const p = liste[i];
                            return p.partien
                                ? `${p.partien} Partien · Punktequote ${punktequote(p)} %` : '';
                        },
                    },
                }),
            },
            scales: {
                x: achseX({ stacked: true }),
                y: achseY({ stacked: true, beginAtZero: true,
                            ticks: { color: cssVar('--chart-axis'), font: { size: 11 },
                                     maxTicksLimit: 5, precision: 0 } }),
            },
        }, texte.voll),
    });
}

/* ------------------------------------------------------- Gegnerstärke */

/* Die Frage, die eine Siegquote allein nie beantwortet. Die Saeulen sind die
   Menge, die Linie darueber die Punktequote je Stufe -- sie liegt mit
   ORDER.TREND obenauf (DESIGN.md 7). */
function zeichneStaerke() {
    const box = document.getElementById('schStaerkeBox');
    const leer = document.getElementById('schStaerkeLeer');
    const note = document.getElementById('schStaerkeNote');
    if (state.charts.staerke) { state.charts.staerke.destroy(); state.charts.staerke = null; }

    const s = state.stats;
    if (!s) return;
    const stufen = s.gegnerstaerke || [];
    const gesamt = stufen.reduce((a, b) => a + b.partien, 0);

    if (!gesamt) {
        box.hidden = true;
        leer.hidden = false;
        leer.innerHTML = leerImZeitraum('🎯', 'der Vergleich nach Gegnerstärke');
        bindeKontenKnoepfe(leer);
        note.textContent = '';
        return;
    }
    leer.hidden = true;
    box.hidden = false;

    const quote = stufen.map(x => x.partien ? punktequote(x) : null);
    const reihe = (name, feld, farbe) => ({
        type: 'bar', label: name, data: stufen.map(x => x[feld]),
        backgroundColor: farbe, borderRadius: 6, borderSkipped: false,
        maxBarThickness: 56, yAxisID: 'y', order: VexCharts.ORDER.VALUE,
    });

    state.charts.staerke = new Chart(document.getElementById('schStaerkeChart'), {
        data: {
            // Zweizeilig: „50–200 stärker“ steht auf 60 Pixeln Achsenbreite
            // sonst als abgeschnittenes Wort da. Chart.js bricht ein Array.
            labels: stufen.map(x => x.label.split(' ')),
            datasets: [
                reihe('Siege', 'siege', cssVar('--ok')),
                reihe('Remis', 'remis', cssVar('--text-4')),
                reihe('Niederlagen', 'niederlagen', cssVar('--danger')),
                {
                    type: 'line', label: 'Punktequote', data: quote, yAxisID: 'quote',
                    borderColor: cssVar('--text-2'), borderWidth: 2, borderDash: [5, 4],
                    pointRadius: 3, pointBackgroundColor: cssVar('--text-2'),
                    tension: 0.3, fill: false, spanGaps: true,
                    order: VexCharts.ORDER.TREND,
                },
            ],
        },
        options: {
            maintainAspectRatio: false,
            animation: { duration: 200 },
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: true, position: 'top',
                          labels: { color: cssVar('--text-3'), font: { size: 11 },
                                    boxWidth: 10, boxHeight: 10, usePointStyle: true,
                                    pointStyle: 'circle' } },
                tooltip: tooltipStil({
                    callbacks: {
                        title: (items) => stufen[items[0].dataIndex].label,
                        label: (i) => i.parsed.y == null ? null
                            : ' ' + i.dataset.label + ': ' + i.parsed.y
                              + (i.dataset.yAxisID === 'quote' ? ' %' : ''),
                        footer: (items) => {
                            const x = stufen[items[0].dataIndex];
                            return x.partien ? `${x.partien} Partien` : '';
                        },
                    },
                }),
            },
            scales: {
                x: achseX({ stacked: true,
                            ticks: { color: cssVar('--chart-axis'), font: { size: 10 },
                                     maxRotation: 0, autoSkip: false } }),
                y: achseY({ stacked: true, beginAtZero: true,
                            ticks: { color: cssVar('--chart-axis'), font: { size: 11 },
                                     maxTicksLimit: 5, precision: 0 } }),
                quote: { position: 'right', min: 0, max: 100,
                         ticks: { color: cssVar('--chart-axis'), font: { size: 10 },
                                  maxTicksLimit: 3, callback: (v) => v + ' %' },
                         grid: { display: false }, border: { display: false } },
            },
        },
    });

    // Die Zahl, wegen der man hinschaut: wie es gegen Staerkere lief.
    const hoch = stufen.filter(x => x.key === 'ueber' || x.key === 'weit_ueber')
        .reduce((a, b) => ({ partien: a.partien + b.partien, siege: a.siege + b.siege,
                             remis: a.remis + b.remis, niederlagen: a.niederlagen + b.niederlagen }),
                { partien: 0, siege: 0, remis: 0, niederlagen: 0 });
    note.innerHTML = (hoch.partien
        ? `Gegen höher bewertete Gegner: <strong>${punktequote(hoch)} %</strong> aus
           ${zahl(hoch.partien)} Partien. ` : '')
        + 'Gerechnet wird über die Partien, bei denen beide Wertungen bekannt sind.';
}

/* ------------------------------------------- Zeitkontrollen, Farbe, Listen */

function rangListe(zeilen) {
    const max = Math.max(1, ...zeilen.map(z => z.partien));
    return `<div class="rank-list">${zeilen.map((z, i) => `
        <${z.wert ? 'button type="button"' : 'div'} class="rank-row"
                style="--tone:${z.ton || 'var(--figure, var(--m-schach))'}"
                ${z.wert ? `data-suche="${esc(z.wert)}" data-art="${esc(z.art || '')}"` : ''}
                ${z.titel ? `title="${esc(z.titel)}"` : ''}>
            <span class="rank-mark${z.mark ? ' sch-farbe-mark' : ''}">${esc(z.mark || (i + 1))}</span>
            <span class="rank-name">${esc(z.name)}</span>
            <span class="rank-val">${zahl(z.partien)}</span>
            <span class="rank-bar"><i style="width:${anteil(z.partien, max)}%"></i></span>
            <span class="rank-sub">${punktequote(z)} % Punkte · ${z.siege} S, ${z.remis} R,
                ${z.niederlagen} N${z.extra ? ' · ' + esc(z.extra) : ''}</span>
        </${z.wert ? 'button' : 'div'}>`).join('')}</div>`;
}

function bindeRang(ziel) {
    ziel.querySelectorAll('[data-suche]').forEach(b => b.addEventListener('click', () => {
        if (b.dataset.art) {
            state.filter.perf = b.dataset.art;
            const feld = document.getElementById('schArt');
            if (feld) feld.value = b.dataset.art;
            activateTab('partien');
            zeichneFilterStand();
            ladePartien(true);
            return;
        }
        sucheInPartien(b.dataset.suche);
    }));
}

const FARB_LABEL = { weiss: 'Mit Weiß', schwarz: 'Mit Schwarz' };

function zeichneArten() {
    const ziel = document.getElementById('schArten');
    const s = state.stats;
    if (!s) { ziel.innerHTML = '<span class="skel skel-block"></span>'; return; }

    const arten = (s.zeitkontrollen || []).filter(a => a.partien);
    const farben = (s.farben || []).filter(f => f.partien && FARB_LABEL[f.color]);

    if (!arten.length && !farben.length) {
        ziel.innerHTML = leerImZeitraum('⏱️', 'eine Aufteilung');
        bindeKontenKnoepfe(ziel);
        return;
    }

    // Zwei kleine Ranglisten in einer Karte: beides sind Aufteilungen
    // derselben Partien, und beide haben zwei bis vier Posten. Zwei Karten
    // dafuer waeren zwei halbleere Karten.
    ziel.innerHTML = (arten.length ? `<div class="sch-unterteil">Zeitkontrolle</div>`
        + rangListe(arten.map(a => ({
            ...a, name: a.label || perfLabel(a.perf), wert: a.perf, art: a.perf,
            titel: 'Nur diese Zeitkontrolle in den Partien zeigen',
        }))) : '')
        + (farben.length ? `<div class="sch-unterteil">Farbe</div>`
        + rangListe(farben.map(f => ({
            ...f, name: FARB_LABEL[f.color], mark: f.color === 'weiss' ? '◻' : '◼',
            ton: f.color === 'weiss' ? 'var(--text-1)' : 'var(--text-3)',
        }))) : '');

    bindeRang(ziel);
}

function zeichneEroeffnungen() {
    const ziel = document.getElementById('schEroeffnungen');
    const s = state.stats;
    if (!s) { ziel.innerHTML = '<span class="skel skel-block"></span>'; return; }

    const liste = s.eroeffnungen || [];
    if (!liste.length) {
        ziel.innerHTML = gesamtBilanz().partien
            ? leerKarte('📖', 'Zu diesen Partien hat keine der beiden Plattformen eine '
                + 'Eröffnung mitgeliefert — bei sehr kurzen Partien lassen sie das Feld leer.')
            : leerImZeitraum('📖', 'eine Eröffnungsliste');
        bindeKontenKnoepfe(ziel);
        return;
    }
    ziel.innerHTML = rangListe(liste.map(e => ({
        ...e, name: e.name, wert: e.name,
        titel: 'Diese Eröffnung in den Partien suchen',
    })));
    bindeRang(ziel);
}

function zeichneGegner() {
    const ziel = document.getElementById('schGegner');
    const s = state.stats;
    if (!s) { ziel.innerHTML = '<span class="skel skel-block"></span>'; return; }

    const liste = s.gegner || [];
    if (!liste.length) {
        ziel.innerHTML = gesamtBilanz().partien
            ? leerKarte('👥', 'In diesem Zeitraum ist dir niemand zweimal begegnet — gegen '
                + 'einen einzelnen Gegner gibt es noch keine Bilanz.')
            : leerImZeitraum('👥', 'eine Gegnerliste');
        bindeKontenKnoepfe(ziel);
        return;
    }
    ziel.innerHTML = rangListe(liste.map(g => ({
        ...g, name: g.opponent, wert: g.opponent,
        extra: g.hoechste ? 'bis ' + g.hoechste : '',
        titel: 'Partien gegen ' + g.opponent + ' suchen',
    })));
    bindeRang(ziel);
}

/* Ein Klick in einer Auswertung landet im selben Zustand, den man von Hand
   erzeugen wuerde: Suchfeld gefuellt, Reiter gewechselt, Liste neu geladen. */
function sucheInPartien(wert) {
    state.filter.q = wert;
    document.getElementById('schSuche').value = wert;
    activateTab('partien');
    zeichneFilterStand();
    ladePartien(true);
}

/* --------------------------------------------------------------- Partien */

async function ladePartien(vonVorn) {
    if (vonVorn) state.offset = 0;
    const ziel = document.getElementById('schPartienListe');
    const mehr = document.getElementById('schMehr');

    const f = state.filter;
    const abfrage = new URLSearchParams({
        limit: SEITE, offset: state.offset, sort: f.sort, direction: f.direction,
    });
    if (f.platform) abfrage.set('platform', f.platform);
    if (f.result) abfrage.set('result', f.result);
    if (f.perf) abfrage.set('perf', f.perf);
    if (f.rated) abfrage.set('rated', f.rated);
    if (f.q) abfrage.set('q', f.q);

    if (vonVorn) ziel.innerHTML = '<span class="skel skel-block"></span>';

    let res;
    try {
        res = await API.partien('?' + abfrage.toString());
    } catch (err) {
        ziel.innerHTML = `<div class="empty is-error"><span class="empty-mark">⚠️</span>
            <p class="empty-text">Die Partien konnten nicht geladen werden.</p></div>`;
        mehr.hidden = true;
        return;
    }

    if (!res.total) {
        mehr.hidden = true;
        document.getElementById('schPartienSumme').textContent = '';
        // Zwei verschiedene Gruende, zwei verschiedene Saetze: "noch nichts
        // geholt" und "der Filter trifft nichts" saehen sonst gleich aus.
        ziel.innerHTML = filterAktiv()
            ? leerKarte('🔎', 'Keine Partie passt zu diesem Filter.',
                '<button type="button" class="v-btn v-btn--sm" id="schLeerWeg">Filter zurücksetzen</button>')
            : leerKarte('♟️',
                'Noch keine Partien im Bestand. Sie werden nicht von Hand erfasst, sondern unter '
                + '<strong>Konten</strong> von der Plattform geholt.',
                '<button type="button" class="v-btn v-btn--sm" data-zu-konten>Zu den Konten</button>');
        const weg = document.getElementById('schLeerWeg');
        if (weg) weg.addEventListener('click', filterZuruecksetzen);
        bindeKontenKnoepfe(ziel);
        return;
    }

    const zeilen = res.games.map(partieZeile).join('');
    const liste = ziel.querySelector('.rec-list');
    if (vonVorn || !liste) {
        ziel.innerHTML = `<div class="rec-list">${zeilen}</div>`;
        state.gezeigt = res.games.slice();
    } else {
        liste.insertAdjacentHTML('beforeend', zeilen);
        state.gezeigt = state.gezeigt.concat(res.games);
    }

    state.offset += res.games.length;
    const offen = res.total - state.offset;
    mehr.hidden = offen <= 0;
    mehr.textContent = `Weitere ${Math.min(SEITE, offen)} laden`;
    document.getElementById('schPartienSumme').textContent =
        `${zahl(state.offset)} von ${zahl(res.total)}`;

    // Chess.com liefert zu keiner Partie eine Wertungsdifferenz mit. Das
    // einmal dazuzuschreiben ist ehrlicher, als eine leere Spalte stehen zu
    // lassen, die wie "keine Veraenderung" aussieht.
    const ohneDiff = state.gezeigt.some(g => g.platform === 'chesscom');
    let note = ziel.parentElement.querySelector('.sch-note');
    if (ohneDiff && !note) {
        ziel.insertAdjacentHTML('afterend',
            '<p class="sch-note">Chess.com gibt keine Wertungsdifferenz je Partie heraus — '
            + 'dort bleibt die Zahl rechts leer.</p>');
    } else if (!ohneDiff && note) {
        note.remove();
    }

    ziel.querySelectorAll('[data-partie]').forEach(b => {
        if (b.dataset.gebunden) return;
        b.dataset.gebunden = '1';
        b.addEventListener('click', () => {
            const g = state.gezeigt.find(x => String(x.id) === b.dataset.partie);
            if (g) zeigePartie(g);
        });
    });
}

function partieZeile(g) {
    const diff = g.rating_diff;
    const diffText = diff == null ? '<span style="color:var(--text-4)">—</span>'
        : (diff > 0 ? '+' + diff : (diff < 0 ? '−' + Math.abs(diff) : '±0'));
    const diffFarbe = diff == null || diff === 0 ? ''
        : ` style="color:${diff > 0 ? 'var(--ok)' : 'var(--danger)'}"`;
    const meta = [
        `<span class="sch-dot" data-platform="${esc(g.platform)}" aria-hidden="true"></span>`
            + esc(LABEL[g.platform] || g.platform),
        esc(datum(g.played_at, true)),
        esc(g.perf_label || perfLabel(g.perf)),
        g.color === 'weiss' ? '◻ Weiß' : '◼ Schwarz',
        // Die Eroeffnungsfamilie kommt vom Server -- dieselbe, nach der die
        // Rangliste im Ueberblick gruppiert.
        g.opening_family ? esc(g.opening_family) : (g.opening ? esc(g.opening) : ''),
        g.rated === false ? 'ungewertet' : '',
    ].filter(Boolean);

    // Das S/R/N ist eine Abkuerzung -- im Titel steht das Ergebnis
    // ausgeschrieben, damit die Zeile auch vorgelesen einen Sinn ergibt.
    const titel = `${ERGEBNIS_LABEL[g.result] || 'Partie'} gegen ${g.opponent || 'Unbekannt'}`;
    return `<button type="button" class="rec-row" data-partie="${esc(g.id)}"
            title="${esc(titel)} — für alle Angaben antippen">
        <span class="rec-mark" style="--tone:${ergebnisTon(g.result)}">${ERGEBNIS_KURZ[g.result] || '?'}</span>
        <span class="rec-main">
            <span class="rec-title">${esc(g.opponent || 'Unbekannt')}${g.opponent_rating
                ? ` <span style="color:var(--text-3);font-weight:500">${g.opponent_rating}</span>` : ''}</span>
            <span class="rec-meta">${meta.join('<span class="sep">·</span>')}</span>
        </span>
        <span class="rec-side">
            <span class="rec-val"${diffFarbe}>${diffText}</span>
            ${g.own_rating ? `<span class="rec-sub">${g.own_rating}</span>` : ''}
        </span>
        <span class="rec-go" aria-hidden="true">›</span>
    </button>`;
}

/* Alles, was in die Zeile nicht passt, in einem schwebenden Fenster. Das ist
   auf dem Handy der Platz, an dem eine Tabelle acht Spalten haette. */
function zeigePartie(g) {
    const zeile = (dt, dd, klasse) => dd
        ? `<dt>${dt}</dt><dd${klasse ? ` class="${klasse}"` : ''}>${dd}</dd>` : '';
    const diff = g.rating_diff;
    const inhalt = `<dl class="sch-detail">
        ${zeile('Ergebnis', esc(ERGEBNIS_LABEL[g.result] || '–')
            + (g.end_reason ? ` <span style="color:var(--text-3)">· ${esc(g.end_reason)}</span>` : ''),
            'is-' + esc(g.result))}
        ${zeile('Gespielt', esc(datum(g.played_at, true)))}
        ${zeile('Plattform', `<span class="sch-dot" data-platform="${esc(g.platform)}"
            aria-hidden="true"></span> ${esc(LABEL[g.platform] || g.platform)}`)}
        ${zeile('Art', esc(g.perf_label || perfLabel(g.perf))
            + (g.rated === false ? ' · ungewertet' : ' · gewertet'))}
        ${zeile('Farbe', g.color === 'weiss' ? '◻ Weiß' : '◼ Schwarz')}
        ${zeile('Gegner', esc(g.opponent || 'Unbekannt')
            + (g.opponent_rating ? ` <span style="color:var(--text-3)">${g.opponent_rating}</span>` : ''))}
        ${zeile('Eigene Wertung', g.own_rating ? String(g.own_rating) : '')}
        ${zeile('Veränderung', diff == null ? '' : (diff > 0 ? '+' + diff : String(diff)),
            diff == null ? '' : (diff > 0 ? 'is-sieg' : (diff < 0 ? 'is-niederlage' : '')))}
        ${zeile('Eröffnung', g.opening ? esc(g.opening) : '')}
    </dl>
    ${diff == null && g.platform === 'chesscom'
        ? '<p class="sch-detail-hinweis">Eine Wertungsdifferenz gibt Chess.com zur einzelnen '
          + 'Partie nicht heraus — sie fehlt hier, sie ist nicht null.</p>' : ''}
    <div class="sch-detail-fuss">
        ${g.url ? `<a class="v-btn v-btn--primary" href="${esc(g.url)}" target="_blank"
            rel="noopener">Auf ${esc(LABEL[g.platform] || 'der Plattform')} ansehen</a>` : ''}
        ${g.opening_family || g.opening
            ? `<button type="button" class="v-btn" id="schDetailEroeffnung">Eröffnung suchen</button>` : ''}
        ${g.opponent ? `<button type="button" class="v-btn" id="schDetailGegner">Partien gegen ${esc(g.opponent)}</button>` : ''}
    </div>`;

    const modal = openModal(esc(g.opponent || 'Partie'), inhalt);
    const such = (wert) => { modal.close(); sucheInPartien(wert); };
    const e1 = document.getElementById('schDetailEroeffnung');
    if (e1) e1.addEventListener('click', () => such(g.opening_family || g.opening));
    const e2 = document.getElementById('schDetailGegner');
    if (e2) e2.addEventListener('click', () => such(g.opponent));
}

/* Dasselbe Muster wie im Ausgaben-Modul: Overlay, Kopf, Koerper, Escape und
   Klick daneben schliessen. Native Dialoge sind in dieser App raus. */
/* Der Dialog liegt seit v2.1.0 in /js/modal.js -- eine Fassung fuer alle
   Module, mit gesperrtem Hintergrund, Fokus im Kasten und role="dialog".
   Der Name hier bleibt, damit die Aufrufstellen unveraendert bleiben. */
function openModal(titel, inhalt) {
    return VexModal.open(titel, inhalt);
}


/* ---------------------------------------------------------------- Filter */

const CHIPS_ERGEBNIS = [
    { wert: '', label: 'Alle' },
    { wert: 'sieg', label: 'Siege' },
    { wert: 'remis', label: 'Remis' },
    { wert: 'niederlage', label: 'Niederlagen' },
];

function zeichneChips(id, liste, feld) {
    const ziel = document.getElementById(id);
    if (!ziel) return;
    ziel.innerHTML = liste.map(c => `<button type="button" class="v-chip${
        state.filter[feld] === c.wert ? ' is-active' : ''}" data-wert="${esc(c.wert)}">${esc(c.label)}</button>`).join('');
    ziel.querySelectorAll('.v-chip').forEach(b => b.addEventListener('click', () => {
        state.filter[feld] = b.dataset.wert;
        zeichneChips(id, liste, feld);
        zeichneFilterStand();
        ladePartien(true);
    }));
}

/* Die Plattform-Wahl gibt es nur, wenn zwei Konten verbunden sind. Ein
   Filter, der nichts trennen kann, ist nur eine weitere Zeile im Weg. */
function zeichnePlattformAuswahl() {
    const feld = document.getElementById('schPlattform');
    const zeile = document.getElementById('schPlattformZeile');
    if (state.konten.length < 2) {
        zeile.hidden = true;
        state.filter.platform = '';
        return;
    }
    zeile.hidden = false;
    feld.innerHTML = '<option value="">Beide Plattformen</option>'
        + state.konten.map(k =>
            `<option value="${esc(k.platform)}">${esc(LABEL[k.platform] || k.platform)}</option>`).join('');
    feld.value = state.filter.platform;
}

function zeichneArtAuswahl() {
    // Angeboten wird, was im Bestand wirklich vorkommt -- der Server zaehlt
    // das aus den Partien (summary.time_controls). Aus den Wertungszahlen
    // liesse es sich nicht bilden: eine Zeitkontrolle ohne gewertete Partie
    // hat dort keine Zeile, steht aber in den Partien.
    const feld = document.getElementById('schArt');
    feld.innerHTML = '<option value="">Alle Arten</option>'
        + state.arten.map(a =>
            `<option value="${esc(a.perf)}">${esc(a.label)}</option>`).join('');
    feld.value = state.filter.perf;
}

function filterAktiv() {
    const f = state.filter;
    return !!(f.platform || f.result || f.perf || f.rated || f.q);
}

/* Ein Filter, den man nicht sieht, ist eine Falle (DESIGN.md 6b). Gezaehlt
   wird nur, was im Feld liegt -- Suche und Ergebnis stehen sichtbar davor
   und brauchen keine Zahl, die sie wiederholt. */
function zeichneFilterStand() {
    const f = state.filter;
    const n = [f.platform, f.perf, f.rated].filter(Boolean).length;
    const badge = document.getElementById('schFilterBadge');
    const knopf = document.getElementById('schFilterKnopf');
    if (!badge || !knopf) return;
    badge.textContent = String(n);
    badge.hidden = n === 0;
    knopf.classList.toggle('has-active', n > 0);
}

/* Das schwebende Feld: Klick daneben und Escape schliessen es -- dasselbe
   Verhalten wie beim Zeitraum und beim Filter der Ausgaben. */
function bindeFilterFeld() {
    const knopf = document.getElementById('schFilterKnopf');
    const feld = document.getElementById('schFilterFeld');
    if (!knopf || !feld) return;
    const daneben = (e) => {
        if (!feld.contains(e.target) && !knopf.contains(e.target)) zu();
    };
    const taste = (e) => { if (e.key === 'Escape') zu(); };
    const auf = () => {
        feld.hidden = false;
        knopf.setAttribute('aria-expanded', 'true');
        setTimeout(() => document.addEventListener('click', daneben), 0);
        document.addEventListener('keydown', taste);
    };
    const zu = () => {
        feld.hidden = true;
        knopf.setAttribute('aria-expanded', 'false');
        document.removeEventListener('click', daneben);
        document.removeEventListener('keydown', taste);
    };
    knopf.addEventListener('click', () => { feld.hidden ? auf() : zu(); });
    document.getElementById('schFilterFertig').addEventListener('click', zu);
    state.filterFeldZu = zu;
}

function filterZuruecksetzen() {
    state.filter = { platform: '', result: '', perf: '', rated: '', q: '',
                     sort: 'datum', direction: 'desc' };
    if (state.filterFeldZu) state.filterFeldZu();
    document.getElementById('schSuche').value = '';
    document.getElementById('schArt').value = '';
    document.getElementById('schPlattform').value = '';
    document.getElementById('schWertung').value = '';
    document.getElementById('schSort').value = 'datum:desc';
    zeichneChips('schChipsErgebnis', CHIPS_ERGEBNIS, 'result');
    zeichnePlattformAuswahl();
    zeichneFilterStand();
    ladePartien(true);
}

/* ---------------------------------------------------------------- Konten */

/* Die Kontokarte traegt den Satz zum Import selbst -- und zwar den, der
   gerade gilt: vor dem ersten Lauf die Warnung, dass es dauert, danach den
   Hinweis, dass nur noch Neues kommt. */
function zeichneKonten() {
    const ziel = document.getElementById('schKonten');
    ziel.innerHTML = PLATTFORMEN.map(p => {
        const k = state.konten.find(x => x.platform === p.key);
        const kopf = `<div class="v-card-head">
                <h3><span class="sch-dot" data-platform="${p.key}" aria-hidden="true"></span>
                    ${p.label}</h3>
                <span class="v-card-sub">${k ? 'verbunden seit ' + datum(k.linked_at)
                                             : 'nicht verbunden'}</span>
            </div>`;
        if (!k) {
            return `<div class="v-card">${kopf}
                <form class="sch-form" data-platform="${p.key}">
                    <label class="sch-feld">
                        <span>${p.hinweis}</span>
                        <input type="text" name="username" autocomplete="off"
                               spellcheck="false" placeholder="Benutzername">
                    </label>
                    <button type="submit" class="v-btn v-btn--primary">Verbinden</button>
                </form>
                <p class="sch-hinweis sch-hinweis--klein">Nur der Name — ${p.label} gibt Wertung
                    und Partien öffentlich heraus, ein Passwort braucht es dafür nicht.</p>
            </div>`;
        }
        const bestand = k.games_count
            ? `${zahl(k.games_count)} Partien · ${datum(k.games_from)} – ${datum(k.games_to)}`
            : 'noch keine Partien geholt';
        const geholt = k.games_at ? 'zuletzt geholt ' + vorTagen(k.games_at) : '';
        // Der Zeiger allein sieht nach dem ersten Stueck aus wie nach dem
        // letzten. Ob davor noch Jahre fehlen, steht deshalb als eigener
        // Satz da -- und der Knopf heisst danach.
        const offen = k.games_count && !k.backfill_done;
        const stand = !k.games_count ? ''
            : (offen
                ? '<span class="v-tag v-tag--warn">Historie noch nicht vollständig</span>'
                : '<span class="v-tag">Historie vollständig geholt</span>');
        return `<div class="v-card">${kopf}
            <div class="sch-konto">
                <span class="v-icon-tile sch-konto-tile" style="--tone:var(--m-schach)" aria-hidden="true">♟️</span>
                <div class="sch-konto-text">
                    <a href="${esc(k.profile_url)}" target="_blank" rel="noopener">${esc(k.username)}</a>
                    <div class="sch-konto-sub">${bestand}</div>
                    ${geholt ? `<div class="sch-konto-sub">${geholt}</div>` : ''}
                    ${stand ? `<div class="sch-konto-sub">${stand}</div>` : ''}
                </div>
            </div>
            <div class="sch-lauf" data-rolle="lauf-${k.id}" role="status" aria-live="polite" hidden></div>
            <div class="sch-konto-tasten">
                <button type="button" class="v-btn v-btn--primary" data-holen="${k.id}">
                    ${!k.games_count ? 'Alle Partien holen'
                      : (offen ? 'Historie weiterholen' : 'Neue Partien holen')}</button>
                <button type="button" class="v-btn" data-stopp="${k.id}" hidden>Anhalten</button>
                ${k.games_count ? `<button type="button" class="v-btn" data-vorn="${k.id}">Von vorn holen</button>` : ''}
                <button type="button" class="v-btn v-btn--danger" data-loesen="${k.id}">Konto lösen</button>
            </div>
            <p class="sch-hinweis sch-hinweis--klein">${!k.games_count
                ? 'Beim ersten Mal dauert das bei langer Historie ein paar Minuten. Geholt wird '
                  + 'stückweise — Anhalten verliert nichts, der nächste Lauf setzt dort fort. '
                  + 'Der Wertungsverlauf entsteht dabei mit: er steckt in den Partien.'
                : (offen
                    ? 'Es ist noch Historie offen: der Lauf setzt dort fort, wo er zuletzt '
                      + 'aufgehört hat, und läuft weiter, bis nichts mehr kommt. Erst dann '
                      + 'reicht der Wertungsverlauf so weit zurück wie dein Konto.'
                    : 'Die Historie ist vollständig — geholt wird nur noch, was dazukommt. '
                      + '„Von vorn holen“ fängt trotzdem wieder ganz vorn an; doppelte '
                      + 'Partien fallen dabei weg, verloren geht nichts.')}</p>
        </div>`;
    }).join('');

    ziel.querySelectorAll('.sch-form').forEach(f => f.addEventListener('submit', verbinden));
    ziel.querySelectorAll('[data-holen]').forEach(b =>
        b.addEventListener('click', () => importieren(Number(b.dataset.holen), b)));
    ziel.querySelectorAll('[data-stopp]').forEach(b =>
        b.addEventListener('click', () => { state.stopp = true; b.disabled = true; }));
    ziel.querySelectorAll('[data-loesen]').forEach(b =>
        b.addEventListener('click', () => loesen(Number(b.dataset.loesen))));
    ziel.querySelectorAll('[data-vorn]').forEach(b =>
        b.addEventListener('click', () => vonVorn(Number(b.dataset.vorn), b)));
}

/* Den Zeiger zuruecksetzen und gleich weiterholen. Gebraucht wird das, wenn
   der Zeiger zu weit vorn steht -- dann ist alles davor mit dem normalen
   Knopf nicht mehr erreichbar, weil der ab dem Zeiger fragt. */
async function vonVorn(id, knopf) {
    if (state.laeuft) return;
    const ok = await askConfirm({
        title: 'Historie von vorn holen?',
        text: 'Der Lauf fängt wieder bei der ältesten Partie an. Das dauert bei langer '
            + 'Historie ein paar Minuten; schon gespeicherte Partien werden dabei nicht '
            + 'doppelt angelegt, verloren geht nichts.',
        confirmText: 'Von vorn holen',
    });
    if (!ok) return;
    try {
        const res = await API.vonVorn(id);
        state.konten = res.accounts;
        zeichneKonten();
        const neuerKnopf = document.querySelector('[data-holen="' + id + '"]');
        if (neuerKnopf) importieren(id, neuerKnopf);
    } catch (err) {
        melde(err.message || 'Das ging nicht.', 'error');
    }
}

async function verbinden(e) {
    e.preventDefault();
    const form = e.currentTarget;
    const name = form.username.value.trim();
    if (!name) return;
    const knopf = form.querySelector('button');
    knopf.classList.add('is-loading');
    try {
        const res = await API.verbinden(form.dataset.platform, name);
        state.konten = res.accounts;
        zeichneKonten();
        zeichnePlattformAuswahl();
        zeichneUeberblick();
        await ladeStats();
        melde('Konto verbunden.', 'success');
    } catch (err) {
        // Der Server sagt, woran es lag (Name gibt es nicht, Konto
        // geschlossen, Plattform bremst) — das ist die bessere Meldung als
        // ein allgemeines „hat nicht geklappt“.
        melde(err.message || 'Das Konto konnte nicht verbunden werden.', 'error');
    } finally {
        knopf.classList.remove('is-loading');
    }
}

async function loesen(id) {
    const konto = state.konten.find(k => k.id === id);
    const ok = await askConfirm({
        title: 'Konto lösen?',
        text: `Die ${konto && konto.games_count ? zahl(konto.games_count) + ' gespeicherten ' : ''}`
            + 'Partien und der bisherige Wertungsverlauf werden dabei gelöscht. '
            + 'Erneut verbinden holt beides wieder — der Verlauf steckt in den Partien.',
        confirmText: 'Lösen', danger: true,
    });
    if (!ok) return;
    try {
        await API.loesen(id);
        await ladeSummary();
        await Promise.all([ladeStats(), ladePartien(true)]);
        melde('Konto gelöst.', 'success');
    } catch (err) {
        melde(err.message || 'Das Konto konnte nicht gelöst werden.', 'error');
    }
}

/* ----------------------------------------------------------- Importieren */

/* Warten, ohne den Anhalten-Knopf taub zu machen: ein schlichtes setTimeout
   ueber 20 Sekunden liesse den Lauf erst danach merken, dass jemand gedrückt
   hat -- und so lange sieht ein Knopf, der nichts tut, aus wie ein Fehler. */
const warte = (ms) => new Promise(r => {
    const ende = Date.now() + ms;
    const takt = setInterval(() => {
        if (state.stopp || Date.now() >= ende) { clearInterval(takt); r(); }
    }, 200);
});

async function importieren(id, knopf) {
    if (state.laeuft) return;
    state.laeuft = true;
    state.stopp = false;
    knopf.classList.add('is-loading');
    const karte = knopf.closest('.v-card');
    const lauf = karte ? karte.querySelector('[data-rolle="lauf-' + id + '"]') : null;
    const stopp = karte ? karte.querySelector('[data-stopp="' + id + '"]') : null;
    if (stopp) { stopp.hidden = false; stopp.disabled = false; }
    const zeige = (text) => { if (lauf) { lauf.hidden = false; lauf.innerHTML = text; } };

    let neu = 0, runden = 0;
    zeige('Holt das erste Stück …');
    try {
        // Der Server deckelt jeden Lauf; hier wird gerufen, solange er sagt,
        // dass noch Historie offen ist. Die Obergrenze ist nur ein Riegel
        // gegen eine Schleife, die sich selbst nicht beendet.
        while (runden < 1000 && !state.stopp) {
            let res;
            try {
                res = await API.holen(id);
            } catch (err) {
                // Zu schnell gefragt ist kein Abbruchgrund: der Zeiger steht,
                // es fehlt nur eine Minute Geduld. Vorher endete eine lange
                // Historie hier mit einer Fehlermeldung -- und der Bestand
                // blieb auf halbem Weg stehen, ohne dass das jemand sah.
                if (!/429|rate limit|zu viele/i.test(err.message || '')) throw err;
                zeige(`<span class="sch-lauf-zahl">${zahl(neu)}</span> neue Partien geholt`
                    + ' · kurze Pause, der Server bremst — es läuft von selbst weiter');
                await warte(20000);
                continue;
            }
            neu += res.new; runden++;
            zeige(`<span class="sch-lauf-zahl">${zahl(neu)}</span> neue Partien geholt`
                + (res.through ? ` · bis ${datum(res.through)}` : '')
                + (res.more ? ' · läuft weiter, Anhalten verliert nichts' : ''));
            if (!res.more) break;
            // Takt halten: der Server laesst 30 Laeufe je Minute zu, und die
            // Plattformen bitten selbst um hoechstens eine Abfrage je Sekunde.
            await warte(2200);
        }
        const res = await API.konten();
        state.konten = res.accounts;
        zeichneKonten();
        zeichnePlattformAuswahl();
        await Promise.all([ladeSummary(), ladeStats(), ladePartien(true)]);
        if (state.stopp) {
            melde(`Angehalten. ${zahl(neu)} Partien sind da, der nächste Lauf setzt dort fort.`, 'info');
        } else {
            melde(neu ? `${zahl(neu)} Partien geholt.`
                      : 'Keine neuen Partien — alles schon da.', 'success');
        }
    } catch (err) {
        melde(err.message || 'Die Partien konnten nicht geholt werden.', 'error');
        if (lauf && neu) {
            lauf.innerHTML = `<span class="sch-lauf-zahl">${zahl(neu)}</span> Partien geholt, `
                + 'dann abgebrochen — der nächste Lauf setzt dort fort';
        }
    } finally {
        state.laeuft = false;
        state.stopp = false;
        knopf.classList.remove('is-loading');
        const s = document.querySelector('[data-stopp="' + id + '"]');
        if (s) s.hidden = true;
    }
}

/* ------------------------------------------------------------- Automatik */

function zeichneAutomatik() {
    const e = state.einstellungen;
    if (!e) return;
    const stunde = document.getElementById('schAutoHour');
    if (!stunde.options.length) {
        stunde.innerHTML = Array.from({ length: 24 }, (_, i) =>
            `<option value="${i}">${String(i).padStart(2, '0')}:00</option>`).join('');
    }
    document.getElementById('schAutoDaily').checked = !!e.auto_daily;
    stunde.value = String(e.daily_hour);
    document.getElementById('schLive').value = String(e.live_minutes);
    document.getElementById('schTz').textContent = e.timezone || 'Ortszeit';
    document.getElementById('schAutoStand').textContent = e.last_auto_at
        ? 'Zuletzt: ' + datum(e.last_auto_at, true)
            + (e.last_auto_note ? ' · ' + e.last_auto_note : '')
        : 'Noch nicht gelaufen';
}

async function speichereAutomatik() {
    const knopf = document.getElementById('schAutoSpeichern');
    knopf.classList.add('is-loading');
    try {
        state.einstellungen = await API.setzen({
            auto_daily: document.getElementById('schAutoDaily').checked,
            daily_hour: Number(document.getElementById('schAutoHour').value),
            live_minutes: Number(document.getElementById('schLive').value),
        });
        zeichneAutomatik();
        starteTakt();
        melde('Automatik gespeichert.', 'success');
    } catch (err) {
        melde(err.message || 'Die Einstellung konnte nicht gespeichert werden.', 'error');
    } finally {
        knopf.classList.remove('is-loading');
    }
}

/* Der Takt bei offener Seite. Bewusst still: er meldet nichts, er haelt nur
   die Zahlen aktuell. In einem Hintergrund-Tab pausiert er -- Abfragen fuer
   eine Seite, die niemand ansieht, sind reine Last bei beiden Plattformen. */
function starteTakt() {
    if (state.takt) { clearInterval(state.takt); state.takt = null; }
    const minuten = state.einstellungen ? state.einstellungen.live_minutes : 0;
    if (!minuten || !state.konten.length) return;
    state.takt = setInterval(async () => {
        if (document.hidden || state.laeuft) return;
        try {
            const res = await API.aktualisieren();
            state.konten = res.accounts;
            await ladeStats(true);
        } catch (e) { /* beim naechsten Takt wieder */ }
    }, minuten * 60 * 1000);
}

async function aktualisieren() {
    const knopf = document.getElementById('schRefresh');
    knopf.classList.add('is-loading');
    try {
        const res = await API.aktualisieren();
        state.konten = res.accounts;
        zeichneKonten();
        await ladeStats(true);
        if (res.problems && res.problems.length) melde(res.problems.join(' · '), 'error');
        else melde('Wertungszahlen sind auf dem neuesten Stand.', 'success');
    } catch (err) {
        melde(err.message || 'Die Wertungszahlen konnten nicht geholt werden.', 'error');
    } finally {
        knopf.classList.remove('is-loading');
    }
}

/* ------------------------------------------------------------------ Laden */

async function ladeSummary() {
    try {
        const res = await API.summary();
        state.konten = res.accounts;
        state.arten = res.time_controls || [];
        if (res.settings) state.einstellungen = res.settings;
    } catch (e) {
        // Ein fehlgeschlagener Abruf ist NICHT dasselbe wie "kein Konto
        // verbunden". Vorher sah beides gleich aus: eine Stoerung erschien
        // als Einladung, ein Konto zu verbinden, das laengst verbunden ist.
        state.konten = []; state.arten = [];
        zeigeStatsFehler(statsFehlerText(e));
        zeichneKonten();
        return;
    }
    zeichneUeberblick();
    zeichneKonten();
    zeichnePlattformAuswahl();
    zeichneArtAuswahl();
    zeichneAutomatik();
}

/* Die ganze Auswertung in einer Abfrage. ``still`` heisst: kein Skeleton --
   der Takt im Hintergrund soll die Seite nicht flackern lassen. */
async function ladeStats(still) {
    if (!state.konten.length) { state.stats = null; zerstoereVerlaufCharts(); return; }
    const range = state.range || (state.rangeMount ? state.rangeMount.get() : null);
    const abfrage = new URLSearchParams();
    if (range && range.from) abfrage.set('from', range.from);
    if (range && range.to) abfrage.set('to', range.to);
    const qs = abfrage.toString();

    // Zwei Anstoesse zur selben Zeit -- der Zeitraum-Knopf meldet sich beim
    // Einhaengen, und ein frisch verbundenes Konto laedt ebenfalls -- sollen
    // EINE Abfrage sein und nicht zwei, die sich gegenseitig ueberzeichnen.
    if (state.statsLauf && state.statsQs === qs) return state.statsLauf;
    state.statsQs = qs;

    if (!still && !state.stats) {
        // Nur beim ersten Mal: ein Skeleton ueber bereits gezeichnete Karten
        // waere ein Rueckschritt, kein Ladezustand.
        document.getElementById('schVerlauf').innerHTML = '<span class="skel skel-block"></span>';
    }

    state.statsLauf = (async () => {
        try {
            state.stats = await API.stats(qs ? '?' + qs : '');
            document.getElementById('schLeer').hidden = true;
            document.getElementById('schUeberblick').hidden = false;
            zeichneAlles();
        } catch (e) {
            // Im stillen Takt bleibt stehen, was dasteht: eine Fehlerseite
            // ueber gueltigen Zahlen waere ein Rueckschritt.
            if (still) return;
            state.stats = null;
            zerstoereVerlaufCharts();
            zeigeStatsFehler(statsFehlerText(e));
        } finally {
            state.statsLauf = null;
        }
    })();
    return state.statsLauf;
}

/* -------------------------------------------------------------- Reiter */

function activateTab(tab, ohneHash) {
    if (TABS.indexOf(tab) < 0) tab = TABS[0];
    document.querySelectorAll('.tab-btn').forEach(b =>
        b.classList.toggle('active', b.dataset.tab === tab));
    TABS.forEach(t => {
        const el = document.getElementById('tab-' + t);
        if (el) el.hidden = t !== tab;
    });
    // Der Reiter steht in der Adresse: ein Neuladen landet dort, wo man war,
    // und ein Link auf die Partien ist ein Link auf die Partien.
    if (!ohneHash) history.replaceState(null, '', tab === TABS[0] ? location.pathname : '#' + tab);
}

/* ------------------------------------------------------------------ Boot */

document.addEventListener('DOMContentLoaded', async () => {
    if (!isLoggedIn()) { location.href = '/private/login.html'; return; }
    // Freigabe direkt nach dem synchronen Login-Check (css/statistics.css
    // versteckt den Body, bis sie kommt).
    document.body.classList.add('ready');

    try {
        const me = await fetchMe();
        document.getElementById('userLabel').textContent = '👤 ' + me.username;
    } catch (e) { /* Name ist Beiwerk */ }

    document.getElementById('logoutBtn').addEventListener('click',
        () => { clearToken(); location.href = '/private/login.html'; });
    document.querySelectorAll('.tab-btn').forEach(b =>
        b.addEventListener('click', () => activateTab(b.dataset.tab)));
    document.getElementById('schRefresh').addEventListener('click', aktualisieren);
    document.getElementById('schMehr').addEventListener('click', () => ladePartien(false));
    document.getElementById('schAutoSpeichern').addEventListener('click', speichereAutomatik);
    document.getElementById('schFilterWeg').addEventListener('click', filterZuruecksetzen);
    bindeFilterFeld();

    zeichneChips('schChipsErgebnis', CHIPS_ERGEBNIS, 'result');
    document.getElementById('schArt').addEventListener('change', (e) => {
        state.filter.perf = e.target.value;
        zeichneFilterStand();
        ladePartien(true);
    });
    document.getElementById('schPlattform').addEventListener('change', (e) => {
        state.filter.platform = e.target.value;
        zeichneFilterStand();
        ladePartien(true);
    });
    document.getElementById('schWertung').addEventListener('change', (e) => {
        state.filter.rated = e.target.value;
        zeichneFilterStand();
        ladePartien(true);
    });
    document.getElementById('schSort').addEventListener('change', (e) => {
        const teile = e.target.value.split(':');
        state.filter.sort = teile[0];
        state.filter.direction = teile[1];
        ladePartien(true);
    });
    let tippen = null;
    document.getElementById('schSuche').addEventListener('input', (e) => {
        clearTimeout(tippen);
        const wert = e.target.value.trim();
        tippen = setTimeout(() => {
            state.filter.q = wert;
            zeichneFilterStand();
            ladePartien(true);
        }, 300);
    });

    activateTab((location.hash || '').replace('#', '') || TABS[0], true);

    // Erst die Konten: ohne sie steht auf dem Ueberblick nur der eine Satz,
    // und der Zeitraum-Knopf (der die Auswertung anstoesst) haengt daran.
    await ladeSummary();
    starteTakt();
    await ladePartien(true);
});
