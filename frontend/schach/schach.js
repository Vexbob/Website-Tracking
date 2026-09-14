/* schach.js — v1.92.0
 *
 * Wertungszahlen, Verlauf und Partien von Lichess und Chess.com.
 *
 * Vier Dinge, die dieses Modul von den anderen unterscheiden:
 *
 *   1. **Die Daten liegen woanders.** Beide Plattformen geben sie oeffentlich
 *      heraus; hinterlegt wird nur ein Benutzername. Deshalb gibt es hier
 *      kein Formular zum Eintragen von Partien -- nur einen Knopf, der holt.
 *   2. **Der Import laeuft in Stuecken.** Der Server holt je Aufruf ein
 *      Stueck und sagt, ob noch mehr kommt; diese Seite ruft in einer
 *      Schleife, zeigt den Stand mit und laesst sich jederzeit anhalten. Ein
 *      Abbruch verliert nichts.
 *   3. **Den Verlauf gibt es nur hier.** Beide Plattformen kennen nur den
 *      aktuellen Stand. Vexbob haelt je Abruf eine Tageszeile fest -- das
 *      Diagramm ist damit der einzige Ort, an dem die Entwicklung steht, und
 *      es sagt selbst, wie weit es zurueckreicht.
 *   4. **Nicht jede Zahl bedeutet dasselbe.** Chess.com gibt zur
 *      Raetsel-Wertung nur den Bestwert heraus und zu keiner Partie eine
 *      Wertungsdifferenz. Beides steht dabei, statt dass eine Luecke wie eine
 *      Null aussieht.
 *
 * Die Auswertung (Form, Eroeffnungen, Zeitkontrollen) rechnet ueber die
 * juengsten ANALYSE_STUECK Partien, nicht ueber den ganzen Bestand: der
 * Endpunkt kennt keinen Zeitraum, und mehrere Seiten nachzuladen waere bei
 * zehn Jahren Historie ein Dutzend Abfragen fuer eine Randzahl. Wie weit der
 * Ausschnitt reicht, steht in jeder dieser Karten.
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
    partien:   (qs)   => apiCall('/api/chess/games' + qs),
    verlauf:   (qs)   => apiCall('/api/chess/ratings' + qs),
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
// Der Ausschnitt fuer die Auswertung. 200 ist die Obergrenze des Endpunkts
// und reicht fuer Form, Eroeffnungen und Zeitkontrollen aus.
const ANALYSE_STUECK = 200;

const state = {
    konten: [], bilanz: [], einstellungen: null,
    analyse: null,                 // { games, total } -- der Ausschnitt
    gezeigt: [],                   // die Partien, die gerade in der Liste stehen
    offset: 0, gesamt: 0,
    laeuft: false, stopp: false,
    perf: null,                    // Disziplin des Verlaufs
    range: null, rangeMount: null, filterFeldZu: null,
    chart: null,
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

const melde = (text, art) => { if (window.Toast) Toast[art || 'info'](text); };

const zahl = (n) => Number(n || 0).toLocaleString('de-DE');
// Eine Wertungszahl wird ohne Tausenderpunkt geschrieben -- "1.721" liest
// niemand, der Schach spielt.
const wertung = (n) => String(n == null ? '–' : n);
const anteil = (teil, ganz) => ganz ? Math.round((teil / ganz) * 100) : 0;

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

/* Die Beschriftung einer Disziplin steht am Server (PERF_LABEL); hier wird
   sie nur aus den geladenen Wertungen gesucht, damit keine zweite Liste
   entsteht, die auseinanderlaufen kann. */
function perfLabel(perf) {
    for (const k of state.konten) {
        const r = (k.ratings || []).find(x => x.perf === perf);
        if (r && r.label) return r.label;
    }
    return perf || '–';
}

/* Die Disziplin, um die es geht: die mit den meisten gespielten Partien.
   Raetsel und Bestwerte zaehlen nicht -- sie sind keine Spielstaerke im
   selben Sinn und haben keinen Tagesverlauf. */
function fuehrendeDisziplin() {
    const zaehler = {};
    state.konten.forEach(k => (k.ratings || []).forEach(r => {
        if (r.is_best || r.perf === 'puzzle') return;
        zaehler[r.perf] = (zaehler[r.perf] || 0) + (r.games || 1);
    }));
    const beste = Object.keys(zaehler).sort((a, b) => zaehler[b] - zaehler[a])[0];
    return beste || null;
}

/* Die Reihenfolge der Disziplinen kommt vom Server (dort steht PERFS) und
   soll erhalten bleiben, auch wenn jede Plattform nur einen Teil kennt. Ein
   zweiter Ordnungsbegriff im Frontend waere eine Liste, die mit der des
   Servers auseinanderlaufen kann; stattdessen werden die vorhandenen Listen
   so verschmolzen, dass keine ihre eigene Ordnung verliert. */
function verschmelze(listen) {
    const rest = listen.map(l => l.slice());
    const raus = [];
    const weg = (wert) => rest.forEach(l => {
        const i = l.indexOf(wert);
        if (i >= 0) l.splice(i, 1);
    });
    while (rest.some(l => l.length)) {
        // Genommen wird nur ein Kopf, den keine andere Liste erst spaeter
        // erwartet -- sonst stuende Rapid vor Blitz, weil eine Plattform
        // kein Blitz kennt.
        let kopf = null;
        for (const l of rest) {
            if (!l.length) continue;
            if (rest.some(a => a.indexOf(l[0]) > 0)) continue;
            kopf = l[0];
            break;
        }
        // Widersprechen sich die Listen, gilt die erste -- besser eine
        // Reihenfolge als eine Schleife.
        if (kopf == null) kopf = rest.find(l => l.length)[0];
        raus.push(kopf);
        weg(kopf);
    }
    return raus;
}

function disziplinen() {
    const raus = [];
    state.konten.forEach(k => (k.ratings || []).forEach(r => {
        if (r.is_best) return;
        if (!raus.some(d => d.perf === r.perf)) raus.push({ perf: r.perf, label: r.label });
    }));
    return raus;
}

/* -------------------------------------------------------- Leerer Zustand */

function leerKarte(mark, text, knopf) {
    return `<div class="empty">
        <span class="empty-mark" aria-hidden="true">${mark}</span>
        <p class="empty-text">${text}</p>
        ${knopf || ''}
    </div>`;
}

/* ------------------------------------------------------------- Überblick */

function zeichneUeberblick() {
    const leer = document.getElementById('schLeer');
    const box = document.getElementById('schUeberblick');

    if (!state.konten.length) {
        box.hidden = true;
        leer.hidden = false;
        leer.innerHTML = `<div class="v-card">${leerKarte('♟️',
            'Noch ist nichts verbunden. Vexbob holt Wertungszahl und Partien bei Lichess und '
            + 'Chess.com ab — dafür reicht der Benutzername, ein Passwort braucht es nicht.',
            '<button type="button" class="v-btn v-btn--primary" id="schZuKonten">Konto verbinden</button>')}</div>`;
        const zu = document.getElementById('schZuKonten');
        if (zu) zu.addEventListener('click', () => activateTab('konten'));
        return;
    }
    leer.hidden = true;
    box.hidden = false;

    zeichneKpi();
    zeichneWertungen();
    zeichneBilanz();
    zeichneAnalyse();
    mountRange();
}

/* Eine Hauptzahl, darunter die Einordnung. Sechs gleich grosse Kacheln
   nebeneinander waeren sechs Zahlen und keine Aussage (DESIGN.md,
   .kpi-block). */
function zeichneKpi() {
    const ziel = document.getElementById('schKpi');
    const perf = state.perf || fuehrendeDisziplin();
    let haupt = null;
    state.konten.forEach(k => (k.ratings || []).forEach(r => {
        if (r.perf !== perf || r.is_best) return;
        if (!haupt || r.rating > haupt.r.rating) haupt = { r, konto: k };
    }));

    const gesamt = state.bilanz.reduce((s, b) => s + (b.partien || 0), 0);
    const siege = state.bilanz.reduce((s, b) => s + (b.siege || 0), 0);
    const letzte = state.bilanz.map(b => b.bis).filter(Boolean).sort().slice(-1)[0];
    const serie = aktuelleSerie();

    const kopf = haupt
        ? `<div class="lbl">${esc(haupt.r.label)} · ${esc(LABEL[haupt.konto.platform])}</div>
           <div class="val">${wertung(haupt.r.rating)}</div>
           <div class="sub">${trendSatz(haupt.r)}</div>`
        : `<div class="lbl">Wertungszahl</div>
           <div class="val">–</div>
           <div class="sub">Das Konto hat dort noch keine gewertete Partie — deshalb gibt die
               Plattform auch keine Zahl heraus.</div>`;

    const stark = staerksterSieg();
    const minis = [
        { lbl: 'Partien', val: gesamt ? zahl(gesamt) : '–',
          note: gesamt ? state.bilanz.map(b => LABEL[b.platform]).join(' · ') : 'noch keine geholt' },
        { lbl: 'Siegquote', val: gesamt ? anteil(siege, gesamt) + ' %' : '–',
          note: gesamt ? zahl(siege) + ' Siege' : '' },
        { lbl: 'Serie', val: serie ? serie.kurz : '–', note: serie ? 'in Folge' : '' },
        { lbl: 'Stärkster Sieg', val: stark ? wertung(stark.opponent_rating) : '–',
          note: stark ? 'gegen ' + stark.opponent : (gesamt ? 'im Ausschnitt keiner' : '') },
        { lbl: 'Letzte Partie', val: letzte ? datum(letzte) : '–',
          note: letzte ? vorTagen(letzte) : '' },
    ];

    ziel.innerHTML = `<div class="kpi-hero"><div class="kpi-hero-main">${kopf}</div></div>
        <div class="kpi-mini-row">${minis.map(m => `<div class="kpi-mini">
            <div class="lbl">${esc(m.lbl)}</div>
            <div class="val">${esc(m.val)}</div>
            ${m.note ? `<div class="note">${esc(m.note)}</div>` : ''}
        </div>`).join('')}</div>`;
}

/* Der hoechstbewertete Gegner, den man geschlagen hat -- im Ausschnitt, wie
   alles aus den geladenen Partien. Es ist die Zahl, die man erzaehlt. */
function staerksterSieg() {
    const spiele = state.analyse ? state.analyse.games : [];
    let beste = null;
    spiele.forEach(g => {
        if (g.result !== 'sieg' || !g.opponent_rating) return;
        if (!beste || g.opponent_rating > beste.opponent_rating) beste = g;
    });
    return beste;
}

function vorTagen(iso) {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    const tage = Math.floor((Date.now() - d.getTime()) / 86400000);
    if (tage <= 0) return 'heute';
    if (tage === 1) return 'gestern';
    return 'vor ' + tage + ' Tagen';
}

/* Die Entwicklung als Satz. Sie steht erst da, wenn es einen zweiten Tag zum
   Vergleichen gibt -- ein Pfeil mit 0 daneben saehe aus wie "unveraendert",
   waehrend in Wahrheit noch nichts zu vergleichen ist. */
function trendSatz(r) {
    if (r.trend == null) {
        return 'Die Entwicklung steht hier, sobald der Verlauf zwei Tage umfasst — '
             + 'er beginnt mit dem ersten Abruf.';
    }
    const tage = r.trend_days;
    const zeit = tage >= 28 ? 'in den letzten 30 Tagen'
        : `seit ${tage} ${tage === 1 ? 'Tag' : 'Tagen'} — so weit reicht der Verlauf bisher`;
    return trendMarke(r) + ' ' + zeit;
}

function trendMarke(r) {
    if (r.trend == null) return '';
    const richtung = r.trend > 0 ? 'hoch' : (r.trend < 0 ? 'runter' : 'gleich');
    const pfeil = r.trend > 0 ? '▲' : (r.trend < 0 ? '▼' : '•');
    return `<span class="sch-trend is-${richtung}">${pfeil} ${r.trend > 0 ? '+' : ''}${r.trend}</span>`;
}

/* ---------------------------------------------------- Wertungen im Raster */

function zeichneWertungen() {
    const ziel = document.getElementById('schRatings');
    const stand = document.getElementById('schStand');
    const mitWertung = state.konten.filter(k => k.ratings.length);

    if (!mitWertung.length) {
        stand.textContent = '';
        ziel.innerHTML = leerKarte('🏅',
            'Das Konto ist verbunden, hat dort aber noch keine gewertete Partie — deshalb gibt '
            + 'die Plattform auch keine Wertungszahl heraus.');
        return;
    }

    const zuletzt = mitWertung.map(k => k.ratings_at).filter(Boolean).sort().slice(-1)[0];
    stand.textContent = zuletzt ? 'Stand: ' + datum(zuletzt, true) : '';

    // Eine Zeile je Disziplin, daneben die beiden Plattformen -- so steht
    // Blitz neben Blitz. Zwei Bloecke untereinander hiessen: zum Vergleichen
    // scrollen und die erste Zahl im Kopf behalten.
    const nachPlattform = {};
    state.konten.forEach(k => { nachPlattform[k.platform] = k; });
    const spalten = PLATTFORMEN.filter(p => nachPlattform[p.key]);

    const label = {};
    spalten.forEach(sp => nachPlattform[sp.key].ratings.forEach(r => { label[r.perf] = r.label; }));
    const reihen = verschmelze(spalten.map(sp =>
        nachPlattform[sp.key].ratings.map(r => r.perf)))
        .map(perf => ({ perf, label: label[perf] || perf }));

    const zelle = (konto, perf) => {
        const r = konto && konto.ratings.find(x => x.perf === perf);
        if (!r) return '<div class="sch-vz is-leer">–</div>';
        const sub = r.is_best ? 'Bestwert'
            : (r.games ? zahl(r.games) + ' Partien' : 'aktueller Stand');
        const inhalt = `<span class="sch-vz-num">${wertung(r.rating)}</span>${trendMarke(r)}
            <span class="sch-vz-sub">${sub}</span>`;
        // Ein Bestwert hat keinen Tagesverlauf -- die Zelle ist dann kein
        // Knopf, weil dahinter nichts aufginge.
        if (r.is_best) {
            return `<div class="sch-vz" title="Chess.com gibt zur Rätsel-Wertung nur den Bestwert heraus, nicht den aktuellen Stand">${inhalt}</div>`;
        }
        return `<button type="button" class="sch-vz${state.perf === perf ? ' is-gewaehlt' : ''}"
            data-perf="${esc(perf)}" title="Verlauf dieser Disziplin zeigen">${inhalt}</button>`;
    };

    ziel.innerHTML = `
        <div class="sch-vergleich" style="--spalten:${spalten.length}">
            <div class="sch-vk"></div>
            ${spalten.map(sp => `<div class="sch-vk">
                <span class="sch-dot" data-platform="${sp.key}" aria-hidden="true"></span>
                <a href="${esc(nachPlattform[sp.key].profile_url)}" target="_blank"
                   rel="noopener">${sp.label}</a>
                <span class="sch-vk-name">${esc(nachPlattform[sp.key].username)}</span>
            </div>`).join('')}
            ${reihen.map(d => `
                <div class="sch-vl${state.perf === d.perf ? ' is-gewaehlt' : ''}">${esc(d.label)}</div>
                ${spalten.map(sp => zelle(nachPlattform[sp.key], d.perf)).join('')}
            `).join('')}
        </div>
        <p class="sch-note">Ein Klick auf eine Zahl stellt den Verlauf darunter auf diese
        Disziplin.</p>`;

    ziel.querySelectorAll('[data-perf]').forEach(b => b.addEventListener('click', () => {
        state.perf = b.dataset.perf;
        zeichneWertungen();
        zeichneVerlaufChips();
        ladeVerlauf();
    }));
}

/* --------------------------------------------------------------- Verlauf */

function mountRange() {
    if (state.rangeMount) return;
    const host = document.getElementById('schVerlaufRange');
    if (!host) return;
    if (!state.perf) state.perf = fuehrendeDisziplin();
    zeichneVerlaufChips();
    // Der Zeitraum-Knopf meldet beim Einhaengen einmal -- das ist die erste
    // Ladung des Verlaufs.
    state.rangeMount = VexRange.mount(host, {
        preset: '30',
        onChange: (r) => { state.range = r; ladeVerlauf(); },
    });
}

function zeichneVerlaufChips() {
    const ziel = document.getElementById('schVerlaufChips');
    if (!ziel) return;
    const liste = disziplinen();
    if (liste.length < 2) { ziel.innerHTML = ''; return; }
    ziel.innerHTML = liste.map(d => `<button type="button" class="v-chip${
        state.perf === d.perf ? ' is-active' : ''}" data-perf="${esc(d.perf)}">${esc(d.label)}</button>`).join('');
    ziel.querySelectorAll('.v-chip').forEach(b => b.addEventListener('click', () => {
        state.perf = b.dataset.perf;
        zeichneVerlaufChips();
        zeichneWertungen();
        ladeVerlauf();
    }));
}

async function ladeVerlauf() {
    const leer = document.getElementById('schVerlaufLeer');
    const box = document.getElementById('schVerlaufBox');
    const note = document.getElementById('schVerlaufNote');
    const range = state.range || VexRange.resolve('30');
    if (!state.perf) state.perf = fuehrendeDisziplin();
    if (!state.perf) return;

    const abfrage = new URLSearchParams({ perf: state.perf });
    if (range.fetchDays) abfrage.set('days', String(range.fetchDays));

    let punkte;
    try {
        const res = await API.verlauf('?' + abfrage.toString());
        // Bestwerte sind keine Tagesform: sie gehoeren nicht in eine Kurve,
        // die von Tag zu Tag laeuft.
        punkte = VexRange.clip((res.points || []).filter(p => !p.is_best), 'taken_on', range);
    } catch (e) {
        box.hidden = true;
        leer.hidden = false;
        leer.innerHTML = `<div class="empty is-error"><span class="empty-mark">⚠️</span>
            <p class="empty-text">Der Verlauf konnte nicht geladen werden.</p></div>`;
        note.textContent = '';
        return;
    }

    const tage = [...new Set(punkte.map(p => p.taken_on))].sort();
    if (tage.length < 2) {
        if (state.chart) { state.chart.destroy(); state.chart = null; }
        box.hidden = true;
        leer.hidden = false;
        leer.innerHTML = leerKarte('📈', tage.length
            ? `Bisher steht genau ein Tag im Verlauf (${datum(tage[0])}). Eine Linie braucht zwei —
               der zweite kommt beim nächsten Abruf.`
            : 'Für diesen Zeitraum steht noch kein Stand fest. Der Verlauf entsteht hier und nicht '
              + 'bei den Plattformen: er beginnt mit dem ersten Abruf und wächst mit jedem Tag, an '
              + 'dem du vorbeischaust.');
        note.textContent = '';
        return;
    }
    leer.hidden = true;
    box.hidden = false;
    zeichneVerlauf(punkte, tage);
}

/* Die Kurve. Eine Wertungszahl aendert sich nur nach einer Partie -- an
   Tagen ohne Abruf wird deshalb der letzte bekannte Stand fortgeschrieben
   und nicht interpoliert oder auf null gesetzt (DESIGN.md 7: lueckenlos
   zeichnen). Vor dem ersten bekannten Tag bleibt die Reihe leer: dort gab es
   die Zahl nicht, sie war nur noch nicht abgeholt. */
function zeichneVerlauf(punkte, tage) {
    const canvas = document.getElementById('schVerlaufChart');
    if (state.chart) { state.chart.destroy(); state.chart = null; }

    const von = tage[0];
    const bis = tage[tage.length - 1];
    const achse = [];
    // Der Tag wird aus den lokalen Feldern gebaut, nicht mit toISOString:
    // das rechnet nach UTC um, und oestlich von Greenwich waere damit jeder
    // Tag des Rasters um einen verschoben.
    const tagText = (d) => d.getFullYear() + '-'
        + String(d.getMonth() + 1).padStart(2, '0') + '-'
        + String(d.getDate()).padStart(2, '0');
    for (let d = new Date(von + 'T00:00:00'), i = 0; i < 4000; d.setDate(d.getDate() + 1), i++) {
        const iso = tagText(d);
        achse.push(iso);
        if (iso >= bis) break;
    }

    const plattformen = [...new Set(punkte.map(p => p.platform))]
        .sort((a, b) => a === 'lichess' ? -1 : (b === 'lichess' ? 1 : 0));

    const reihen = plattformen.map(pf => {
        const jeTag = {};
        punkte.filter(p => p.platform === pf).forEach(p => { jeTag[p.taken_on] = p.rating; });
        let zuletzt = null;
        const werte = achse.map(t => {
            if (jeTag[t] != null) zuletzt = jeTag[t];
            return zuletzt;
        });
        return { platform: pf, farbe: plattformFarbe(pf), werte };
    });

    const voll = achse.map(t => VexCharts.fullDay(t));
    const kurz = achse.map(t => t.slice(8, 10) + '.' + t.slice(5, 7) + '.');
    const einzeln = reihen.length === 1;

    const datasets = reihen.map(r => ({
        label: LABEL[r.platform] || r.platform,
        data: r.werte,
        borderColor: r.farbe,
        // Flaeche unter der Linie nur bei einer einzigen Reihe -- zwei sich
        // ueberlagernde Fuellungen ergeben eine dritte Farbe, die nichts
        // bedeutet.
        fill: einzeln,
        backgroundColor: einzeln ? (ctx) => flaeche(ctx, r.farbe) : undefined,
        tension: 0.3, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4,
        spanGaps: false,
        order: VexCharts.ORDER.VALUE,
    }));

    const opts = VexCharts.applyFullDates({
        maintainAspectRatio: false,
        animation: { duration: 200 },
        interaction: { mode: 'index', intersect: false },
        plugins: {
            legend: { display: false },
            tooltip: {
                backgroundColor: cssVar('--surface-3'),
                borderColor: cssVar('--line-strong'), borderWidth: 1,
                titleColor: cssVar('--text-1'), bodyColor: cssVar('--text-2'),
                cornerRadius: 12, padding: 10, displayColors: true,
                callbacks: {
                    title: VexCharts.titleFrom(voll),
                    label: (item) => item.parsed.y == null ? null
                        : ' ' + item.dataset.label + ': ' + item.parsed.y,
                },
            },
        },
        scales: {
            x: { ticks: { color: cssVar('--chart-axis'), font: { size: 11 }, maxRotation: 0,
                          autoSkipPadding: 16 },
                 grid: { display: false }, border: { display: false } },
            y: { ticks: { color: cssVar('--chart-axis'), font: { size: 11 }, maxTicksLimit: 6,
                          callback: (v) => String(v) },
                 grid: { color: cssVar('--chart-grid') }, border: { display: false },
                 beginAtZero: false },
        },
    }, voll);

    state.chart = new Chart(canvas, { type: 'line', data: { labels: kurz, datasets }, options: opts });

    document.getElementById('schVerlaufLegende').innerHTML = reihen.length > 1
        ? reihen.map(r => `<span><i style="background:${r.farbe}"></i>${esc(LABEL[r.platform])}</span>`).join('')
        : '';

    const erste = reihen.map(r => r.werte.find(v => v != null)).filter(v => v != null);
    const letzte = reihen.map(r => [...r.werte].reverse().find(v => v != null)).filter(v => v != null);
    const diff = (erste.length === 1 && letzte.length === 1) ? letzte[0] - erste[0] : null;
    document.getElementById('schVerlaufNote').textContent =
        `${perfLabel(state.perf)} · ${datum(von)} bis ${datum(bis)}`
        + (diff != null ? ` · ${diff > 0 ? '+' : ''}${diff} in diesem Zeitraum` : '')
        + '. An Tagen ohne Abruf gilt der letzte bekannte Stand.';
}

/* Verlauf von 18 % auf 0 % derselben Farbe (DESIGN.md 7). */
function flaeche(ctx, farbe) {
    const chart = ctx.chart;
    if (!chart.chartArea || !/^#[0-9a-f]{6}$/i.test(farbe)) return 'transparent';
    const g = chart.ctx.createLinearGradient(0, chart.chartArea.top, 0, chart.chartArea.bottom);
    g.addColorStop(0, farbe + '2e');
    g.addColorStop(1, farbe + '00');
    return g;
}

/* ---------------------------------------------------------------- Bilanz */

function zeichneBilanz() {
    const ziel = document.getElementById('schBilanz');
    if (!state.bilanz.length) {
        ziel.innerHTML = leerKarte('⚖️',
            'Noch keine Partien im Bestand. Sie werden nicht von Hand erfasst, sondern unter '
            + '<strong>Konten</strong> von der Plattform geholt.');
        return;
    }

    const summe = state.bilanz.reduce((a, b) => ({
        partien: a.partien + (b.partien || 0), siege: a.siege + (b.siege || 0),
        remis: a.remis + (b.remis || 0), niederlagen: a.niederlagen + (b.niederlagen || 0),
    }), { partien: 0, siege: 0, remis: 0, niederlagen: 0 });

    // Zwei Masse, weil sie zwei Fragen beantworten: die Siegquote zaehlt
    // gewonnene Partien, die Punktequote rechnet ein Remis als halben Punkt
    // -- so zaehlt es die Schachwelt.
    const punkte = summe.partien
        ? Math.round(((summe.siege + summe.remis / 2) / summe.partien) * 100) : 0;

    ziel.innerHTML = `
        <div class="sch-quote">
            <span class="sch-quote-num">${anteil(summe.siege, summe.partien)} %</span>
            <span class="sch-quote-lbl">Siegquote · Punktequote ${punkte} %
                <span style="color:var(--text-4)">(Remis zählt halb)</span></span>
        </div>
        ${balken(summe, 'gross')}
        <div class="sch-bilanz-zahlen">
            <span>${zahl(summe.partien)} Partien</span>
            <span class="is-sieg">${zahl(summe.siege)} Siege</span>
            <span class="is-remis">${zahl(summe.remis)} Remis</span>
            <span class="is-verlust">${zahl(summe.niederlagen)} Niederlagen</span>
        </div>
        ${state.bilanz.length > 1 ? state.bilanz.map(b => `
            <div class="sch-bilanz">
                <div class="sch-bilanz-kopf">
                    <span class="sch-dot" data-platform="${esc(b.platform)}" aria-hidden="true"></span>
                    <strong>${esc(LABEL[b.platform] || b.platform)}</strong>
                    <span class="sch-bilanz-zeit">${datum(b.von)} – ${datum(b.bis)}</span>
                </div>
                ${balken(b)}
                <div class="sch-bilanz-zahlen">
                    <span>${zahl(b.partien)} Partien</span>
                    <span class="is-sieg">${anteil(b.siege, b.partien)} % gewonnen</span>
                </div>
            </div>`).join('') : `<p class="sch-note">${esc(LABEL[state.bilanz[0].platform])} ·
                ${datum(state.bilanz[0].von)} bis ${datum(state.bilanz[0].bis)}</p>`}`;
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

/* ------------------------------------------------------------ Auswertung */

/* Der Ausschnitt, ueber den Form, Eroeffnungen und Zeitkontrollen rechnen.
   Er sagt selbst, wie weit er reicht -- eine Auswertung ohne diese Angabe
   waere eine Behauptung ueber den ganzen Bestand. */
function ausschnittLabel() {
    if (!state.analyse) return '';
    const n = state.analyse.games.length;
    if (!n) return '';
    return state.analyse.total > n
        ? `die letzten ${zahl(n)} Partien` : `alle ${zahl(n)} Partien`;
}

function leerRechnung() { return { n: 0, s: 0, r: 0, v: 0 }; }

function zaehle(topf, g) {
    topf.n++;
    if (g.result === 'sieg') topf.s++;
    else if (g.result === 'remis') topf.r++;
    else topf.v++;
}

function aktuelleSerie() {
    const spiele = state.analyse ? state.analyse.games : [];
    if (!spiele.length) return null;
    const art = spiele[0].result;
    let n = 0;
    for (const g of spiele) { if (g.result !== art) break; n++; }
    const wort = { sieg: n === 1 ? 'Sieg' : 'Siege', remis: n === 1 ? 'Remis' : 'Remis',
                   niederlage: n === 1 ? 'Niederlage' : 'Niederlagen' }[art] || '';
    return { art, n, kurz: n + ' ' + wort };
}

function zeichneAnalyse() {
    zeichneForm();
    zeichneEroeffnungen();
    zeichneArten();
}

function zeichneForm() {
    const ziel = document.getElementById('schForm');
    const lbl = document.getElementById('schFormLbl');
    if (!state.analyse) { ziel.innerHTML = '<span class="skel skel-block"></span>'; return; }
    const spiele = state.analyse.games;
    lbl.textContent = ausschnittLabel();

    if (!spiele.length) {
        ziel.innerHTML = leerKarte('🔥',
            'Für die Form fehlen die Partien — geholt werden sie unter <strong>Konten</strong>.');
        return;
    }

    const letzte = spiele.slice(0, 20);
    const serie = aktuelleSerie();
    const farben = { weiss: leerRechnung(), schwarz: leerRechnung() };
    spiele.forEach(g => { if (farben[g.color]) zaehle(farben[g.color], g); });

    const reihen = [
        { key: 'weiss', label: 'Mit Weiß', mark: '◻', tone: 'var(--text-1)', topf: farben.weiss },
        { key: 'schwarz', label: 'Mit Schwarz', mark: '◼', tone: 'var(--text-3)', topf: farben.schwarz },
    ].filter(r => r.topf.n);
    const maxFarbe = Math.max(1, ...reihen.map(r => r.topf.n));

    ziel.innerHTML = `
        <div class="sch-pips" role="img" aria-label="Die letzten ${letzte.length} Partien,
             neueste zuerst: ${letzte.map(g => ERGEBNIS_LABEL[g.result]).join(', ')}">
            ${letzte.map(g => `<span class="sch-pip is-${esc(g.result)}"></span>`).join('')}
        </div>
        <p class="sch-serie">${serie
            ? `Gerade <strong>${serie.n} ${serie.n === 1 ? 'Partie' : 'Partien'}</strong> in Folge
               ${serie.art === 'sieg' ? 'gewonnen' : serie.art === 'remis' ? 'remis' : 'verloren'},
               zuletzt ${esc(vorTagen(spiele[0].played_at))}.`
            : ''}
            Die Reihe oben zeigt die letzten ${letzte.length} Partien, neueste links.</p>
        <div class="rank-list">${reihen.map(r => `
            <div class="rank-row" style="--tone:${r.tone}">
                <span class="rank-mark sch-farbe-mark">${r.mark}</span>
                <span class="rank-name">${r.label}</span>
                <span class="rank-val">${anteil(r.topf.s, r.topf.n)} %</span>
                <span class="rank-bar"><i style="width:${anteil(r.topf.n, maxFarbe)}%"></i></span>
                <span class="rank-sub">${zahl(r.topf.n)} Partien · ${r.topf.s} Siege,
                    ${r.topf.r} Remis, ${r.topf.v} Niederlagen</span>
            </div>`).join('')}</div>`;
}

/* Aus "Sicilian Defense: Najdorf Variation" und "Sicilian Defense Najdorf
   Variation 6.Be3" wird dieselbe Familie. Lichess trennt mit Doppelpunkt,
   Chess.com haengt Variante und Zugfolge einfach an -- ohne das Zusammenlegen
   stuende dieselbe Eroeffnung zwanzigmal in der Liste, jedes Mal mit einer
   Partie. */
function eroeffnungsFamilie(name) {
    let s = String(name || '').trim();
    if (!s) return null;
    s = s.split(':')[0];
    s = s.replace(/\s+\d+\..*$/, '');
    const m = s.match(/^(.*?\b(?:Defense|Defence|Opening|Game|Gambit|Attack|System|Variation)\b)/);
    if (m) s = m[1];
    return s.trim() || null;
}

function zeichneEroeffnungen() {
    const ziel = document.getElementById('schEroeffnungen');
    const lbl = document.getElementById('schEroeffnungenLbl');
    if (!state.analyse) { ziel.innerHTML = '<span class="skel skel-block"></span>'; return; }
    lbl.textContent = ausschnittLabel();

    const topf = {};
    state.analyse.games.forEach(g => {
        const fam = eroeffnungsFamilie(g.opening);
        if (!fam) return;
        if (!topf[fam]) topf[fam] = leerRechnung();
        zaehle(topf[fam], g);
    });
    const liste = Object.keys(topf).map(k => ({ name: k, ...topf[k] }))
        .sort((a, b) => b.n - a.n).slice(0, 6);

    if (!liste.length) {
        ziel.innerHTML = leerKarte('📖',
            'Zu diesen Partien hat keine der beiden Plattformen eine Eröffnung mitgeliefert — '
            + 'bei sehr kurzen Partien lassen sie das Feld leer.');
        return;
    }
    const max = liste[0].n;
    ziel.innerHTML = `<div class="rank-list">${liste.map((e, i) => `
        <button type="button" class="rank-row" style="--tone:var(--figure, var(--m-schach))"
                data-eroeffnung="${esc(e.name)}" title="Diese Eröffnung in den Partien suchen">
            <span class="rank-mark">${i + 1}</span>
            <span class="rank-name">${esc(e.name)}</span>
            <span class="rank-val">${zahl(e.n)}</span>
            <span class="rank-bar"><i style="width:${anteil(e.n, max)}%"></i></span>
            <span class="rank-sub">${anteil(e.s, e.n)} % gewonnen · ${e.s} S, ${e.r} R, ${e.v} N</span>
        </button>`).join('')}</div>
        <p class="sch-note">Klick sucht die Eröffnung in den Partien.</p>`;

    ziel.querySelectorAll('[data-eroeffnung]').forEach(b => b.addEventListener('click', () => {
        state.filter.q = b.dataset.eroeffnung;
        document.getElementById('schSuche').value = b.dataset.eroeffnung;
        activateTab('partien');
        zeichneFilterStand();
        ladePartien(true);
    }));
}

function zeichneArten() {
    const ziel = document.getElementById('schArten');
    const lbl = document.getElementById('schArtenLbl');
    if (!state.analyse) { ziel.innerHTML = '<span class="skel skel-block"></span>'; return; }
    lbl.textContent = ausschnittLabel();

    const topf = {};
    state.analyse.games.forEach(g => {
        const k = g.perf || 'unbekannt';
        if (!topf[k]) topf[k] = leerRechnung();
        zaehle(topf[k], g);
    });
    const liste = Object.keys(topf).map(k => ({ perf: k, ...topf[k] })).sort((a, b) => b.n - a.n);

    if (!liste.length) {
        ziel.innerHTML = leerKarte('⏱️',
            'Ohne Partien im Bestand gibt es hier nichts zu verteilen.');
        return;
    }
    const max = liste[0].n;
    ziel.innerHTML = `<div class="rank-list">${liste.map((a, i) => `
        <button type="button" class="rank-row" style="--tone:var(--figure, var(--m-schach))"
                data-art="${esc(a.perf)}" title="Nur diese Zeitkontrolle in den Partien zeigen">
            <span class="rank-mark">${i + 1}</span>
            <span class="rank-name">${esc(perfLabel(a.perf))}</span>
            <span class="rank-val">${zahl(a.n)}</span>
            <span class="rank-bar"><i style="width:${anteil(a.n, max)}%"></i></span>
            <span class="rank-sub">${anteil(a.s, a.n)} % gewonnen · ${a.s} S, ${a.r} R, ${a.v} N</span>
        </button>`).join('')}</div>
        <p class="sch-note">Klick filtert die Partien auf diese Zeitkontrolle.</p>`;

    ziel.querySelectorAll('[data-art]').forEach(b => b.addEventListener('click', () => {
        state.filter.perf = b.dataset.art;
        const feld = document.getElementById('schArt');
        if (feld) feld.value = b.dataset.art;
        activateTab('partien');
        zeichneFilterStand();
        ladePartien(true);
    }));
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
    state.gesamt = res.total;

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
                '<button type="button" class="v-btn v-btn--sm" id="schLeerKonten">Zu den Konten</button>');
        const weg = document.getElementById('schLeerWeg');
        if (weg) weg.addEventListener('click', filterZuruecksetzen);
        const zu = document.getElementById('schLeerKonten');
        if (zu) zu.addEventListener('click', () => activateTab('konten'));
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
        esc(perfLabel(g.perf)),
        g.color === 'weiss' ? '◻ Weiß' : '◼ Schwarz',
        g.opening ? esc(eroeffnungsFamilie(g.opening) || g.opening) : '',
        g.rated === false ? 'ungewertet' : '',
    ].filter(Boolean);

    return `<button type="button" class="rec-row" data-partie="${esc(g.id)}">
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
        ${zeile('Art', esc(perfLabel(g.perf)) + (g.rated === false ? ' · ungewertet' : ' · gewertet'))}
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
        ${g.opening ? `<button type="button" class="v-btn" id="schDetailEroeffnung">Eröffnung suchen</button>` : ''}
        ${g.opponent ? `<button type="button" class="v-btn" id="schDetailGegner">Partien gegen ${esc(g.opponent)}</button>` : ''}
    </div>`;

    const modal = openModal(esc(g.opponent || 'Partie'), inhalt);
    const such = (wert) => {
        state.filter.q = wert;
        document.getElementById('schSuche').value = wert;
        modal.close();
        zeichneFilterStand();
        ladePartien(true);
    };
    const e1 = document.getElementById('schDetailEroeffnung');
    if (e1) e1.addEventListener('click', () => such(eroeffnungsFamilie(g.opening) || g.opening));
    const e2 = document.getElementById('schDetailGegner');
    if (e2) e2.addEventListener('click', () => such(g.opponent));
}

/* Dasselbe Muster wie im Ausgaben-Modul: Overlay, Kopf, Koerper, Escape und
   Klick daneben schliessen. Native Dialoge sind in dieser App raus. */
function openModal(titel, inhalt) {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `<div class="modal-box">
        <div class="modal-head"><h3>${titel}</h3>
            <button class="modal-close" aria-label="Schließen">✕</button></div>
        <div class="modal-body">${inhalt}</div>
    </div>`;
    document.body.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add('show'));
    const close = () => {
        overlay.classList.remove('show');
        setTimeout(() => overlay.remove(), 200);
        document.removeEventListener('keydown', onKey);
    };
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    overlay.querySelector('.modal-close').addEventListener('click', close);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    document.addEventListener('keydown', onKey);
    return { close };
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
    // Nur die Zeitkontrollen anbieten, die im eigenen Bestand vorkommen --
    // eine Auswahl, die nichts trifft, ist eine Falle. Raetsel sind keine
    // Partien und stehen deshalb nicht dabei.
    const bekannt = state.konten.flatMap(k => k.ratings || []);
    const arten = [...new Set(bekannt.map(r => r.perf))].filter(a => a !== 'puzzle');
    const feld = document.getElementById('schArt');
    feld.innerHTML = '<option value="">Alle Arten</option>'
        + arten.map(a => {
            const label = (bekannt.find(r => r.perf === a) || {}).label || a;
            return `<option value="${esc(a)}">${esc(label)}</option>`;
        }).join('');
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

function zeichneKonten() {
    const ziel = document.getElementById('schKonten');
    ziel.innerHTML = PLATTFORMEN.map(p => {
        const k = state.konten.find(x => x.platform === p.key);
        if (!k) {
            return `<div class="v-card">
                <div class="v-card-head">
                    <h3><span class="sch-dot" data-platform="${p.key}" aria-hidden="true"></span>
                        ${p.label}</h3>
                    <span class="v-card-sub">nicht verbunden</span>
                </div>
                <form class="sch-form" data-platform="${p.key}">
                    <label class="sch-feld">
                        <span>${p.hinweis}</span>
                        <input type="text" name="username" autocomplete="off"
                               spellcheck="false" placeholder="Benutzername">
                    </label>
                    <button type="submit" class="v-btn v-btn--primary">Verbinden</button>
                </form>
            </div>`;
        }
        const partien = k.games_count
            ? `${zahl(k.games_count)} Partien · ${datum(k.games_from)} – ${datum(k.games_to)}`
            : 'noch keine Partien geholt';
        return `<div class="v-card">
            <div class="v-card-head">
                <h3><span class="sch-dot" data-platform="${p.key}" aria-hidden="true"></span>
                    ${p.label}</h3>
                <span class="v-card-sub">verbunden seit ${datum(k.linked_at)}</span>
            </div>
            <div class="sch-konto">
                <span class="v-icon-tile sch-konto-tile" style="--tone:var(--m-schach)" aria-hidden="true">♟️</span>
                <div class="sch-konto-text">
                    <a href="${esc(k.profile_url)}" target="_blank" rel="noopener">${esc(k.username)}</a>
                    <div class="sch-konto-sub">${partien}</div>
                </div>
            </div>
            <div class="sch-lauf" data-rolle="lauf-${k.id}" hidden></div>
            <div class="sch-konto-tasten">
                <button type="button" class="v-btn v-btn--primary" data-holen="${k.id}">
                    ${k.games_count ? 'Neue Partien holen' : 'Alle Partien holen'}</button>
                <button type="button" class="v-btn" data-stopp="${k.id}" hidden>Anhalten</button>
                <button type="button" class="v-btn v-btn--danger" data-loesen="${k.id}">Konto lösen</button>
            </div>
        </div>`;
    }).join('');

    ziel.querySelectorAll('.sch-form').forEach(f => f.addEventListener('submit', verbinden));
    ziel.querySelectorAll('[data-holen]').forEach(b =>
        b.addEventListener('click', () => importieren(Number(b.dataset.holen), b)));
    ziel.querySelectorAll('[data-stopp]').forEach(b =>
        b.addEventListener('click', () => { state.stopp = true; b.disabled = true; }));
    ziel.querySelectorAll('[data-loesen]').forEach(b =>
        b.addEventListener('click', () => loesen(Number(b.dataset.loesen))));
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
        state.perf = state.perf || fuehrendeDisziplin();
        zeichneKonten();
        zeichnePlattformAuswahl();
        zeichneArtAuswahl();
        zeichneUeberblick();
        if (state.rangeMount) ladeVerlauf();
        melde('Konto verbunden.', 'success');
    } catch (err) {
        // Der Server sagt, woran es lag (Name gibt es nicht, Konto
        // geschlossen, Plattform bremst) — das ist die bessere Meldung als
        // ein allgemeines „hat nicht geklappt".
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
            + 'Erneut verbinden holt die Partien wieder, den Verlauf nicht.',
        confirmText: 'Lösen', danger: true,
    });
    if (!ok) return;
    try {
        await API.loesen(id);
        await ladeSummary();
        await Promise.all([ladeAnalyse(), ladePartien(true)]);
        melde('Konto gelöst.', 'success');
    } catch (err) {
        melde(err.message || 'Das Konto konnte nicht gelöst werden.', 'error');
    }
}

/* ----------------------------------------------------------- Importieren */

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
        while (runden < 400 && !state.stopp) {
            const res = await API.holen(id);
            neu += res.new; runden++;
            zeige(`<span class="sch-lauf-zahl">${zahl(neu)}</span> neue Partien geholt`
                + (res.more ? ' · läuft weiter, Anhalten verliert nichts' : ''));
            if (!res.more) break;
        }
        const res = await API.konten();
        state.konten = res.accounts;
        zeichneKonten();
        zeichnePlattformAuswahl();
        zeichneArtAuswahl();
        await Promise.all([ladeSummary(), ladeAnalyse(), ladePartien(true)]);
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
            zeichneKpi();
            zeichneWertungen();
        } catch (e) { /* beim naechsten Takt wieder */ }
    }, minuten * 60 * 1000);
}

async function aktualisieren() {
    const knopf = document.getElementById('schRefresh');
    knopf.classList.add('is-loading');
    try {
        const res = await API.aktualisieren();
        state.konten = res.accounts;
        zeichneKpi();
        zeichneWertungen();
        zeichneKonten();
        if (state.rangeMount) ladeVerlauf();
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
        state.bilanz = res.per_platform;
        if (res.settings) state.einstellungen = res.settings;
    } catch (e) {
        state.konten = []; state.bilanz = [];
    }
    if (!state.perf) state.perf = fuehrendeDisziplin();
    zeichneUeberblick();
    zeichneKonten();
    zeichnePlattformAuswahl();
    zeichneAutomatik();
}

async function ladeAnalyse() {
    try {
        const res = await API.partien(
            '?limit=' + ANALYSE_STUECK + '&offset=0&sort=datum&direction=desc');
        state.analyse = { games: res.games || [], total: res.total || 0 };
    } catch (e) {
        state.analyse = { games: [], total: 0 };
    }
    if (state.konten.length) { zeichneKpi(); zeichneAnalyse(); }
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

    await ladeSummary();
    zeichneArtAuswahl();
    starteTakt();
    await Promise.all([ladeAnalyse(), ladePartien(true)]);
});
