/* verwalten.js — v2.21.0
 *
 * Die Seite ist ein Wegweiser: fünf Zeilen, jede zu einer der Pflegeseiten.
 * Die Zahl am Rand sagt, ob dort etwas wartet -- vor allem bei den
 * Dubletten, die sonst niemand öffnet, solange nichts drin ist. Die Zahlen
 * kommen einzeln: fehlt eine, bleibt nur ihr Feld leer. */
async function zahl(id, laden, text) {
    const el = document.getElementById(id);
    if (!el) return;
    try { const r = await laden(); const t = text(r); el.textContent = t[0]; el.classList.toggle('ist-offen', !!t[1]); }
    catch (e) { el.textContent = ''; }
}

(async function () {
    const me = await ensureLoggedIn(); if (!me) return;
    renderSubnav();
    const n = (a) => Array.isArray(a) ? a.length : 0;
    zahl('azNLaeden', AUSGABEN_API.stores, (r) => [n(r) + (n(r) === 1 ? ' Laden' : ' Läden')]);
    zahl('azNKategorien', AUSGABEN_API.categories, (r) => [n(r) + (n(r) === 1 ? ' Kategorie' : ' Kategorien')]);
    zahl('azNMarken', () => AUSGABEN_API.brands(), (r) => [n(r) + (n(r) === 1 ? ' Marke' : ' Marken')]);
    zahl('azNDubletten', AUSGABEN_API.duplicateGroups, (r) => n(r)
        ? [n(r) + (n(r) === 1 ? ' Verdacht' : ' Verdachtsfälle'), true] : ['keine']);
    zahl('azNImport', () => apiCall('/api/expenses/imports'), (r) => {
        if (!n(r)) return ['noch keiner'];
        const d = r[0].created_at || r[0].uploaded_at || r[0].date_to || null;
        return [d ? 'zuletzt ' + fmtDate(d) : n(r) + ' Importe'];
    });
})();
