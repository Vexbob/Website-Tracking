/* schach.js — v1.83.0
 *
 * Wertungszahlen und Partien von Lichess und Chess.com.
 *
 * Drei Dinge, die dieses Modul von den anderen unterscheiden:
 *
 *   1. **Die Daten liegen woanders.** Beide Plattformen geben sie oeffentlich
 *      heraus; hinterlegt wird nur ein Benutzername. Deshalb gibt es hier
 *      kein Formular zum Eintragen von Partien -- nur einen Knopf, der holt.
 *   2. **Der Import laeuft in Stuecken.** Der Server holt je Aufruf ein
 *      Stueck und sagt, ob noch mehr kommt; diese Seite ruft in einer
 *      Schleife und zeigt den Fortschritt. Ein Abbruch verliert nichts.
 *   3. **Nicht jede Zahl bedeutet dasselbe.** Chess.com gibt zur
 *      Raetsel-Wertung nur den Bestwert heraus, Lichess den aktuellen Stand.
 *      Die Kachel sagt das dazu, statt beide Zahlen gleich aussehen zu lassen.
 */

const API = {
    konten:    ()    => apiCall('/api/chess/accounts'),
    // Das Objekt bleibt ein Objekt: apiCall schickt einen fertigen String als
    // Formulardaten, ein Plain-Object dagegen als JSON -- und der Endpunkt
    // erwartet JSON.
    verbinden: (p, n) => apiCall('/api/chess/accounts', {
        method: 'POST', body: { platform: p, username: n } }),
    loesen:    (id)  => apiCall('/api/chess/accounts/' + id, { method: 'DELETE' }),
    aktualisieren: () => apiCall('/api/chess/refresh', { method: 'POST' }),
    holen:     (id)  => apiCall('/api/chess/import?account_id=' + id, { method: 'POST' }),
    partien:   (qs)  => apiCall('/api/chess/games' + qs),
    summary:   ()    => apiCall('/api/chess/summary'),
};

const PLATTFORMEN = [
    { key: 'lichess',  label: 'Lichess',   hinweis: 'Benutzername auf lichess.org' },
    { key: 'chesscom', label: 'Chess.com', hinweis: 'Benutzername auf chess.com' },
];

const TABS = ['ueberblick', 'partien', 'konten'];
const SEITE = 50;

const state = { konten: [], bilanz: [], offset: 0, gesamt: 0, laeuft: false };

const esc = (v) => String(v == null ? '' : v)
    .replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const melde = (text, art) => {
    if (window.Toast) Toast[art || 'info'](text);
};

function datum(iso, mitZeit) {
    if (!iso) return '–';
    const d = new Date(iso);
    const t = d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
    return mitZeit ? t + ' ' + d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' }) : t;
}

/* ------------------------------------------------------------- Überblick */

function zeichneWertungen() {
    const ziel = document.getElementById('schRatings');
    const stand = document.getElementById('schStand');
    const mitWertung = state.konten.filter(k => k.ratings.length);

    if (!state.konten.length) {
        stand.textContent = '';
        ziel.innerHTML = `<div class="empty">
            <span class="empty-mark">📈</span>
            <p class="empty-text">Noch keine Wertungszahl, weil noch kein Konto verbunden ist.
            Unter <strong>Konten</strong> reicht dafür der Benutzername.</p>
        </div>`;
        return;
    }
    if (!mitWertung.length) {
        stand.textContent = '';
        ziel.innerHTML = `<div class="empty">
            <span class="empty-mark">📈</span>
            <p class="empty-text">Das Konto ist verbunden, hat dort aber noch keine gewertete
            Partie — deshalb gibt die Plattform auch keine Wertungszahl heraus.</p>
        </div>`;
        return;
    }

    const zuletzt = mitWertung
        .map(k => k.ratings_at).filter(Boolean).sort().slice(-1)[0];
    stand.textContent = zuletzt ? 'Stand: ' + datum(zuletzt, true) : '';

    ziel.innerHTML = mitWertung.map(k => `
        <div class="sch-block">
            <div class="sch-block-head">
                <span class="sch-dot" data-platform="${esc(k.platform)}" aria-hidden="true"></span>
                <a href="${esc(k.profile_url)}" target="_blank" rel="noopener">${esc(k.platform_label)} · ${esc(k.username)}</a>
            </div>
            <div class="sch-rating-grid">
                ${k.ratings.map(r => `
                    <div class="sch-rating">
                        <div class="sch-rating-lbl">${esc(r.label)}</div>
                        <div class="sch-rating-num">${r.rating}</div>
                        <div class="sch-rating-sub">${r.is_best
                            ? 'Bestwert'
                            : (r.games ? r.games.toLocaleString('de-DE') + ' Partien' : 'aktuell')}</div>
                    </div>`).join('')}
            </div>
        </div>`).join('');
}

function zeichneBilanz() {
    const karte = document.getElementById('schBilanzCard');
    const ziel = document.getElementById('schBilanz');
    if (!state.bilanz.length) { karte.hidden = true; return; }
    karte.hidden = false;
    ziel.innerHTML = state.bilanz.map(b => {
        const gesamt = b.partien || 1;
        const teil = (n) => Math.round((n / gesamt) * 100);
        return `<div class="v-row sch-bilanz">
            <div class="sch-bilanz-kopf">
                <span class="sch-dot" data-platform="${esc(b.platform)}" aria-hidden="true"></span>
                <strong>${esc(b.platform === 'lichess' ? 'Lichess' : 'Chess.com')}</strong>
                <span class="sch-bilanz-zeit">${datum(b.von)} – ${datum(b.bis)}</span>
            </div>
            <div class="sch-balken" role="img"
                 aria-label="${b.siege} Siege, ${b.remis} Remis, ${b.niederlagen} Niederlagen">
                <span class="sch-teil is-sieg" style="width:${teil(b.siege)}%"></span>
                <span class="sch-teil is-remis" style="width:${teil(b.remis)}%"></span>
                <span class="sch-teil is-verlust" style="width:${teil(b.niederlagen)}%"></span>
            </div>
            <div class="sch-bilanz-zahlen">
                <span>${b.partien.toLocaleString('de-DE')} Partien</span>
                <span class="is-sieg">${b.siege} Siege</span>
                <span class="is-remis">${b.remis} Remis</span>
                <span class="is-verlust">${b.niederlagen} Niederlagen</span>
            </div>
        </div>`;
    }).join('');
}

/* ---------------------------------------------------------------- Konten */

function zeichneKonten() {
    const ziel = document.getElementById('schKonten');
    ziel.innerHTML = PLATTFORMEN.map(p => {
        const k = state.konten.find(x => x.platform === p.key);
        if (!k) {
            return `<div class="v-card">
                <div class="v-card-head"><h3>${p.label}</h3>
                    <span class="v-card-sub">nicht verbunden</span></div>
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
            ? `${k.games_count.toLocaleString('de-DE')} Partien · ${datum(k.games_from)} – ${datum(k.games_to)}`
            : 'noch keine Partien geholt';
        return `<div class="v-card">
            <div class="v-card-head">
                <h3>${p.label}</h3>
                <span class="v-card-sub">verbunden seit ${datum(k.linked_at)}</span>
            </div>
            <div class="sch-konto">
                <span class="v-icon-tile sch-konto-tile" style="--tone:var(--m-schach)" aria-hidden="true">♟️</span>
                <div class="sch-konto-text">
                    <a href="${esc(k.profile_url)}" target="_blank" rel="noopener">${esc(k.username)}</a>
                    <div class="sch-konto-sub" data-rolle="stand">${partien}</div>
                </div>
            </div>
            <div class="sch-konto-tasten">
                <button type="button" class="v-btn v-btn--primary" data-holen="${k.id}">
                    ${k.games_count ? 'Neue Partien holen' : 'Alle Partien holen'}</button>
                <button type="button" class="v-btn v-btn--danger" data-loesen="${k.id}">Konto lösen</button>
            </div>
        </div>`;
    }).join('');

    ziel.querySelectorAll('.sch-form').forEach(f =>
        f.addEventListener('submit', verbinden));
    ziel.querySelectorAll('[data-holen]').forEach(b =>
        b.addEventListener('click', () => importieren(Number(b.dataset.holen), b)));
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
        zeichneKonten(); zeichneWertungen();
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
        text: `Die ${konto && konto.games_count ? konto.games_count.toLocaleString('de-DE') + ' gespeicherten ' : ''}`
            + 'Partien und der bisherige Wertungsverlauf werden dabei gelöscht. '
            + 'Erneut verbinden holt die Partien wieder, den Verlauf nicht.',
        confirmText: 'Lösen', danger: true,
    });
    if (!ok) return;
    try {
        const res = await API.loesen(id);
        state.konten = res.accounts;
        zeichneKonten(); zeichneWertungen();
        await ladePartien(true);
        melde('Konto gelöst.', 'success');
    } catch (err) {
        melde(err.message || 'Das Konto konnte nicht gelöst werden.', 'error');
    }
}

/* -------------------------------------------------------------- Importieren */

async function importieren(id, knopf) {
    if (state.laeuft) return;
    state.laeuft = true;
    knopf.classList.add('is-loading');
    const karte = knopf.closest('.v-card');
    const stand = karte ? karte.querySelector('[data-rolle="stand"]') : null;
    let neu = 0, gesehen = 0, runden = 0;
    try {
        // Der Server deckelt jeden Lauf; hier wird gerufen, solange er sagt,
        // dass noch Historie offen ist. Die Obergrenze ist nur ein Riegel
        // gegen eine Schleife, die sich selbst nicht beendet.
        while (runden < 400) {
            const res = await API.holen(id);
            neu += res.new; gesehen += res.seen; runden++;
            if (stand) {
                stand.textContent = `Holt … ${neu.toLocaleString('de-DE')} neue Partien`
                    + (res.more ? ' (läuft weiter)' : '');
            }
            if (!res.more) break;
        }
        const res = await API.konten();
        state.konten = res.accounts;
        zeichneKonten();
        await Promise.all([ladeSummary(), ladePartien(true)]);
        melde(neu
            ? `${neu.toLocaleString('de-DE')} Partien geholt.`
            : 'Keine neuen Partien — alles schon da.', 'success');
    } catch (err) {
        melde(err.message || 'Die Partien konnten nicht geholt werden.', 'error');
        if (stand && neu) {
            stand.textContent = `${neu.toLocaleString('de-DE')} Partien geholt, dann abgebrochen`;
        }
    } finally {
        state.laeuft = false;
        knopf.classList.remove('is-loading');
    }
}

/* --------------------------------------------------------------- Partien */

async function ladePartien(vonVorn) {
    if (vonVorn) state.offset = 0;
    const koerper = document.getElementById('schPartienBody');
    const tabelle = document.getElementById('schPartienTabelle');
    const leer = document.getElementById('schPartienLeer');
    const mehr = document.getElementById('schMehr');

    let res;
    try {
        res = await API.partien(`?limit=${SEITE}&offset=${state.offset}`);
    } catch (err) {
        leer.innerHTML = `<div class="empty is-error"><span class="empty-mark">⚠️</span>
            <p class="empty-text">Die Partien konnten nicht geladen werden.</p></div>`;
        return;
    }
    state.gesamt = res.total;

    if (!res.total) {
        tabelle.hidden = true; mehr.hidden = true;
        leer.innerHTML = `<div class="empty">
            <span class="empty-mark">♟️</span>
            <p class="empty-text">Noch keine Partien im Bestand. Sie werden nicht von Hand
            erfasst, sondern unter <strong>Konten</strong> von der Plattform geholt.</p></div>`;
        document.getElementById('schPartienSumme').textContent = '';
        return;
    }

    const zeilen = res.games.map(g => `
        <tr>
            <td>${datum(g.played_at, true)}</td>
            <td><span class="sch-dot" data-platform="${esc(g.platform)}" aria-hidden="true"></span></td>
            <td>${esc(g.perf || '–')}</td>
            <td>${g.color === 'weiss' ? '◻' : '◼'}</td>
            <td>${esc(g.opponent)}${g.opponent_rating ? ` <span class="sch-klein">${g.opponent_rating}</span>` : ''}</td>
            <td class="sch-erg is-${esc(g.result)}">${g.result === 'sieg' ? 'Sieg'
                : g.result === 'remis' ? 'Remis' : 'Niederlage'}
                <span class="sch-klein">${esc(g.end_reason || '')}</span></td>
            <td class="num">${g.rating_diff == null ? '' :
                (g.rating_diff > 0 ? '+' : '') + g.rating_diff}</td>
            <td>${g.url ? `<a href="${esc(g.url)}" target="_blank" rel="noopener">ansehen</a>` : ''}</td>
        </tr>`).join('');

    if (vonVorn) { koerper.innerHTML = zeilen; leer.innerHTML = ''; }
    else koerper.insertAdjacentHTML('beforeend', zeilen);

    tabelle.hidden = false;
    state.offset += res.games.length;
    mehr.hidden = state.offset >= res.total;
    document.getElementById('schPartienSumme').textContent =
        `${state.offset.toLocaleString('de-DE')} von ${res.total.toLocaleString('de-DE')}`;
}

/* ----------------------------------------------------------------- Laden */

async function ladeSummary() {
    try {
        const res = await API.summary();
        state.konten = res.accounts;
        state.bilanz = res.per_platform;
    } catch (e) {
        state.konten = []; state.bilanz = [];
    }
    zeichneWertungen(); zeichneBilanz(); zeichneKonten();
}

async function aktualisieren() {
    const knopf = document.getElementById('schRefresh');
    knopf.classList.add('is-loading');
    try {
        const res = await API.aktualisieren();
        state.konten = res.accounts;
        zeichneWertungen(); zeichneKonten();
        if (res.problems && res.problems.length) melde(res.problems.join(' · '), 'error');
        else melde('Wertungszahlen sind auf dem neuesten Stand.', 'success');
    } catch (err) {
        melde(err.message || 'Die Wertungszahlen konnten nicht geholt werden.', 'error');
    } finally {
        knopf.classList.remove('is-loading');
    }
}

function activateTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(b =>
        b.classList.toggle('active', b.dataset.tab === tab));
    TABS.forEach(t => {
        const el = document.getElementById('tab-' + t);
        if (el) el.hidden = t !== tab;
    });
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

    await ladeSummary();
    await ladePartien(true);
});
