/* erinnerungen.js — v2.42.0
 *
 * Erinnerungen auf der Startseite: „CS2-Bestand aktualisieren“ am Monats-
 * anfang, „Depot importieren“ quartalsweise am 14. des letzten Quartals-
 * monats. Gespeichert am Konto (ui_erinnerungen, geprueft in ui_router.py),
 * eingestellt unter /einstellungen/, gezeigt auf / -- und hier steht EINMAL,
 * wann eine faellig ist. Startseite und Einstellungen rechnen beide damit,
 * damit sie nie zwei verschiedene Termine nennen.
 *
 * Faellig ist eine Erinnerung ab ihrem Termin, bis „Erledigt“ gedrueckt
 * wird; danach erst wieder ab dem naechsten Termin.
 */
(function () {
    if (window.VexErinnerung) return;

    const PREF = 'ui_erinnerungen';
    // Ab Werk -- gespeichert wird erst, wenn jemand etwas aendert oder
    // erledigt (wie jede Einstellung: das Frontend kennt seinen Standard).
    const STANDARD = [
        { id: 'cs2', text: 'CS2-Bestand aktualisieren', href: '/cs2/', rhythmus: 'monat', tag: 1, monat: 1, erledigt: null },
        { id: 'depot', text: 'Depot: neuen Kontoauszug importieren', href: '/depot/', rhythmus: 'quartal', tag: 14, monat: 3, erledigt: null },
        { id: 'musik', text: 'Musik: Spotify- und Overcast-Export importieren', href: '/musik/', rhythmus: 'quartal', tag: 14, monat: 3, erledigt: null },
    ];
    const MONATE = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August',
        'September', 'Oktober', 'November', 'Dezember'];

    const pad = (n) => String(n).padStart(2, '0');
    const iso = (d) => d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
    const heuteOhneZeit = (h) => { const d = h ? new Date(h) : new Date(); return new Date(d.getFullYear(), d.getMonth(), d.getDate()); };

    /* Passt ein Monat (1–12) zum Rhythmus? Im Quartal zaehlt die Lage im
       Quartal: 3 heisst März, Juni, September, Dezember. */
    function monatPasst(e, m) {
        if (e.rhythmus === 'monat') return true;
        if (e.rhythmus === 'quartal') return (m - (e.monat || 1)) % 3 === 0;
        return m === (e.monat || 1);
    }

    /* Der juengste Termin an oder vor heute (hoechstens zwoelf Monate zurueck). */
    function letzterTermin(e, heute) {
        const h = heuteOhneZeit(heute);
        for (let i = 0; i <= 12; i++) {
            const d = new Date(h.getFullYear(), h.getMonth() - i, e.tag);
            if (d <= h && monatPasst(e, d.getMonth() + 1)) return d;
        }
        return null;
    }

    /* Der naechste Termin nach heute. */
    function naechsterTermin(e, heute) {
        const h = heuteOhneZeit(heute);
        for (let i = 0; i <= 12; i++) {
            const d = new Date(h.getFullYear(), h.getMonth() + i, e.tag);
            if (d > h && monatPasst(e, d.getMonth() + 1)) return d;
        }
        return null;
    }

    function faellig(e, heute) {
        const t = letzterTermin(e, heute);
        return !!t && (!e.erledigt || e.erledigt < iso(t));
    }

    function beschreibung(e) {
        if (e.rhythmus === 'monat') return 'monatlich am ' + e.tag + '.';
        if (e.rhythmus === 'jahr') return 'jährlich am ' + e.tag + '. ' + MONATE[(e.monat || 1) - 1];
        const monate = [0, 1, 2, 3].map(q => (e.monat || 1) + 3 * q);
        return 'quartalsweise am ' + monate.map(m => e.tag + '.' + m + '.').join(', ');
    }

    const datumLang = (d) => d.getDate() + '. ' + MONATE[d.getMonth()];

    function liste() {
        const v = window.VexPrefs ? VexPrefs.get(PREF, null) : null;
        return Array.isArray(v) ? v : STANDARD.map(e => Object.assign({}, e));
    }

    async function speichern(neu) { await VexPrefs.set(PREF, neu); }

    async function erledigen(id, heute) {
        const neu = liste().map(e => e.id === id ? Object.assign({}, e, { erledigt: iso(heuteOhneZeit(heute)) }) : e);
        await speichern(neu);
        return neu;
    }

    window.VexErinnerung = { PREF, STANDARD, MONATE, liste, speichern, erledigen, faellig,
        letzterTermin, naechsterTermin, beschreibung, datumLang, iso };
})();
