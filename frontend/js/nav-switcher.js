/* nav-switcher.js — v1.59.0
 * Injiziert die Navigation in jede .navbar: am Rechner eine offene Leiste mit
 * allen Modulen, dazu den Punkte-Schalter fuer das, was nicht mehr hineinpasst.
 *
 * Bis v1.58.x lagen die Module ausschliesslich hinter dem Punkte-Schalter --
 * am Rechner ist dafuer reichlich Platz, und zwei Klicks fuer einen
 * Modulwechsel waren zwei zu viel. Die Leiste blendet vom Ende her aus, was
 * nicht mehr passt; ein neues Modul in MODULES braucht deshalb keine Regel und
 * keine Breitenangabe, es rutscht bei Bedarf von selbst ins Menue.
 * Läuft automatisch beim DOM-Ready. Erkennt die aktuelle Sektion anhand
 * der URL und markiert sie aktiv. Berücksichtigt Login-Status (für
 * geschützte Module) und is_admin (für Admin-Bereich).
 *
 * Einbindung: <script src="/js/nav-switcher.js" defer></script> nach api.js.
 */

(function () {
    // v1.21.1: Blog hatte zwei separate Eintraege (öffentliche Ansicht +
    // "Blog-Admin"). Fuer Admins gibt es jetzt nur noch EINEN Blog-Eintrag,
    // der direkt in den Editor fuehrt (die öffentliche Ansicht ist von dort
    // per "Live-Ansicht"-Link erreichbar). Nicht-Admins sehen weiterhin nur
    // die öffentliche Ansicht.
    // v1.51.0: ``icon`` und ``short`` sind fuer die mobile Tab-Leiste unten.
    // Sie stehen hier und nicht in einer zweiten Liste, damit ein neues Modul
    // an genau einer Stelle eingetragen werden muss.
    const MODULES = [
        { href: '/',            label: '🏠 Dashboard',      public: false, icon: 'home',   short: 'Home' },
        { href: '/sparziel/',   label: '💰 Sparziel',       public: false, icon: 'coin',   short: 'Sparen' },
        { href: '/ausgaben/',   label: '💶 Ausgaben',       public: false, icon: 'wallet', short: 'Ausgaben' },
        { href: '/notizen/',    label: '📝 Notizen',        public: false, icon: 'note',   short: 'Notizen' },
        { href: '/health/',     label: '🏋️ Gesundheit',     public: false, icon: 'pulse',  short: 'Gesundheit' },
        { href: '/blog/',       label: '📰 Blog',           public: true, hideForAdmin: true, icon: 'news', short: 'Blog' },
        { href: '/blog/admin/', label: '📰 Blog',           public: false, admin: true, icon: 'news', short: 'Blog' },
        { href: '/admin/',      label: '👥 User-Verwaltung', public: false, admin: true, icon: 'users', short: 'User' },
    ];

    // Von build() gefuellt: die Module, die dieses Konto ueberhaupt sehen
    // darf. Tab-Leiste und Einstell-Dialog richten sich danach.
    let visibleModules = null;

    function currentPath() {
        return location.pathname.replace(/\/+$/, '') || '/';
    }

    function isActive(href) {
        const cur = currentPath();
        const h = href.replace(/\/+$/, '') || '/';
        if (h === '/') return cur === '/';
        return cur === h || cur.startsWith(h + '/');
    }

    async function build() {
        const navbar = document.querySelector('.navbar');
        if (!navbar) return;
        // Vermeide Doppel-Injection
        if (navbar.querySelector('.nav-switcher')) return;

        // Login-Status bestimmen
        let loggedIn = false, isAdmin = false;
        try {
            if (typeof isLoggedIn === 'function') loggedIn = isLoggedIn();
            if (loggedIn && typeof fetchMe === 'function') {
                // fetchMe(true) cached; kein extra Request nötig wenn schon geholt
                const me = await fetchMe(true);
                isAdmin = !!me.is_admin;
            }
        } catch (e) { /* nicht eingeloggter Zustand */ }

        const visible = MODULES.filter(m => {
            if (m.hideForAdmin && loggedIn && isAdmin) return false;
            if (m.public) return true;
            if (!loggedIn) return false;
            if (m.admin) return isAdmin;
            return true;
        });

        visibleModules = visible;
        if (!visible.length) return;

        const wrapper = document.createElement('div');
        wrapper.className = 'nav-switcher';

        const btn = document.createElement('button');
        btn.className = 'nav-switcher-btn';
        btn.type = 'button';
        btn.title = 'Module wechseln';
        btn.setAttribute('aria-label', 'Module wechseln');
        btn.setAttribute('aria-haspopup', 'true');
        btn.setAttribute('aria-expanded', 'false');
        // v1.36.1: Icon-only-Button (9-Punkte-Grid, Apple-style App-Switcher).
        // Kein Emoji + Label mehr -- der Button ist auf jeder Unterseite
        // gleich schlicht und wirkt wie ein "App-Grid"-Symbol.
        btn.innerHTML = `
            <svg class="nav-switcher-ico" viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
                <circle cx="4" cy="4" r="1.6"/><circle cx="10" cy="4" r="1.6"/><circle cx="16" cy="4" r="1.6"/>
                <circle cx="4" cy="10" r="1.6"/><circle cx="10" cy="10" r="1.6"/><circle cx="16" cy="10" r="1.6"/>
                <circle cx="4" cy="16" r="1.6"/><circle cx="10" cy="16" r="1.6"/><circle cx="16" cy="16" r="1.6"/>
            </svg>`;

        const menu = document.createElement('div');
        menu.className = 'nav-switcher-menu';
        menu.setAttribute('role', 'menu');
        menu.innerHTML = `<div class="nav-switcher-head">Module</div>` + visible.map(m => {
            const cls = isActive(m.href) ? 'active' : '';
            // Label ist "<Emoji> Text" -- wir splitten in Icon + Text
            const parts = m.label.split(' ');
            const icon = parts.shift() || '';
            const text = parts.join(' ');
            return `<a href="${m.href}" class="nav-switcher-item ${cls}" role="menuitem">
                <span class="nsi-icon">${icon}</span>
                <span class="nsi-text">${text}</span>
                ${cls ? '<span class="nsi-dot" aria-hidden="true"></span>' : ''}
            </a>`;
        }).join('') + `<button type="button" class="nav-switcher-item nav-switcher-cfg" role="menuitem">
                <span class="nsi-icon">⚙️</span>
                <span class="nsi-text">Tab-Leiste anpassen</span>
            </button>`;

        wrapper.appendChild(btn);
        wrapper.appendChild(menu);
        navbar.appendChild(wrapper);

        await buildModuleRow(navbar, visible);
        buildSettingsLink(navbar);

        const cfgBtn = menu.querySelector('.nav-switcher-cfg');
        if (cfgBtn) cfgBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            menu.classList.remove('open');
            menu.style.display = '';
            btn.setAttribute('aria-expanded', 'false');
            openNavSettings();
        });

        const closeMenu = () => {
            menu.classList.remove('open');
            menu.style.display = '';
            btn.setAttribute('aria-expanded', 'false');
        };
        // Toggle
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const open = menu.classList.toggle('open');
            if (open) { menu.style.display = 'flex'; btn.setAttribute('aria-expanded', 'true'); }
            else closeMenu();
        });
        // Außen-Klick schließt
        document.addEventListener('click', (e) => {
            if (!wrapper.contains(e.target)) closeMenu();
        });
        // ESC schließt
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeMenu();
        });
    }

    // ---------------------------------------------------------------------
    // v1.59.0 — Offene Modul-Leiste am Rechner
    // ---------------------------------------------------------------------
    // Reihenfolge und Auswahl kommen aus der Einstellung ``ui_nav_desktop``;
    // ohne gespeicherte Einstellung stehen alle sichtbaren Module in der
    // Reihenfolge von MODULES. Der localStorage-Eintrag ist nur ein Cache,
    // damit die Leiste beim Seitenwechsel nicht erst umspringt.
    const DESKTOP_PREF = 'ui_nav_desktop';
    let moduleRow = null;

    function readDesktopCache() {
        const arr = VexPrefs.get(DESKTOP_PREF, null);
        return (Array.isArray(arr) && arr.length) ? arr : null;
    }

    /* Die Wunschreihenfolge auf das, was dieses Konto sehen darf. Module, die
       in der Einstellung fehlen, haengen hinten an: ein neu dazugekommenes
       Modul soll auftauchen, ohne dass man die Einstellung anfassen muss. */
    function desktopOrder(visible, wish) {
        const byHref = new Map(visible.map(m => [m.href, m]));
        const out = [];
        (wish || []).forEach(href => {
            const m = byHref.get(href);
            if (m && out.indexOf(m) === -1) out.push(m);
        });
        visible.forEach(m => { if (out.indexOf(m) === -1) out.push(m); });
        return out;
    }

    function moduleIconSvg(m) {
        const path = TAB_ICONS[m.icon];
        if (!path) return '';
        return '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" ' +
               'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" ' +
               'stroke-linejoin="round" aria-hidden="true">' + path + '</svg>';
    }

    function renderModuleRow(visible) {
        if (!moduleRow) return;
        const items = desktopOrder(visible, readDesktopCache());
        moduleRow.innerHTML = items.map(m => {
            const parts = m.label.split(' ');
            parts.shift();                       // Emoji weg, das Icon kommt als SVG
            const text = parts.join(' ');
            const active = isActive(m.href) ? ' active' : '';
            return '<a href="' + m.href + '" class="nav-mod' + active + '"' +
                   (active ? ' aria-current="page"' : '') + '>' +
                   moduleIconSvg(m) + '<span>' + text + '</span></a>';
        }).join('');
        fitModuleRow();
        // Beim ersten Zeichnen steht die Breite der Leiste noch nicht fest.
        requestAnimationFrame(fitModuleRow);
    }

    /* Vom Ende her ausblenden, bis die Zeile passt. Das aktive Modul bleibt
       immer stehen -- es ist die einzige Anzeige, wo man gerade ist. */
    function fitModuleRow() {
        if (!moduleRow) return;
        const links = Array.prototype.slice.call(moduleRow.children);
        links.forEach(el => { el.hidden = false; });
        if (!moduleRow.clientWidth) return;      // Leiste ist gerade ausgeblendet
        for (let i = links.length - 1; i >= 0; i--) {
            if (moduleRow.scrollWidth <= moduleRow.clientWidth + 1) break;
            if (links[i].classList.contains('active')) continue;
            links[i].hidden = true;
        }
        const hidden = links.some(el => el.hidden);
        // Der Punkte-Schalter ist am Rechner nur noch der Ueberlauf. Passt
        // alles hinein, waere er ein Knopf ohne Aufgabe.
        document.body.classList.toggle('nav-row-complete', !hidden);
    }

    async function buildModuleRow(navbar, visible) {
        if (navbar.querySelector('.nav-modules')) return;
        moduleRow = document.createElement('nav');
        moduleRow.className = 'nav-modules';
        moduleRow.setAttribute('aria-label', 'Module');
        // Die Leiste steht zwischen Titel und Konto. Sie am Titel
        // auszurichten reicht nicht -- nicht jede Seite hat einen; der Block
        // rechts ist der verlaessliche Anker.
        const right = navbar.querySelector('.nav-right');
        const title = navbar.querySelector('.nav-title');
        if (right && right.parentNode === navbar) navbar.insertBefore(moduleRow, right);
        else if (title && title.parentNode === navbar) title.after(moduleRow);
        else navbar.appendChild(moduleRow);
        renderModuleRow(visible);

        let t = null;
        window.addEventListener('resize', () => {
            clearTimeout(t);
            t = setTimeout(fitModuleRow, 120);
        });

        // Einmal pro Seite den Serverstand aller Einstellungen holen. Die
        // Leiste steht schon aus dem Cache; hier wird nur korrigiert, wenn er
        // veraltet ist. Bewusst abgewartet -- wer auf Einstellungen angewiesen
        // ist, wartet auf 'vexnav:ready' und findet den Cache dann gefuellt.
        try {
            if (typeof apiCall !== 'function') return;
            await VexPrefs.load();
            renderModuleRow(visible);
        } catch (e) { /* offline: der Cache steht */ }
    }

    // Der Zahnrad-Knopf steht links vom Konto -- auf jeder Seite an derselben
    // Stelle, damit man ihn nicht suchen muss.
    function buildSettingsLink(navbar) {
        const right = navbar.querySelector('.nav-right');
        if (!right || right.querySelector('.nav-settings')) return;
        if (isActive('/einstellungen/')) return;
        const a = document.createElement('a');
        a.className = 'nav-btn nav-settings';
        a.href = '/einstellungen/';
        a.title = 'Einstellungen';
        a.setAttribute('aria-label', 'Einstellungen');
        a.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" ' +
            'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" ' +
            'stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3.2"/>' +
            '<path d="M12 3.6v2M12 18.4v2M3.6 12h2M18.4 12h2' +
            'M6.05 6.05l1.45 1.45M16.5 16.5l1.45 1.45' +
            'M17.95 6.05L16.5 7.5M7.5 16.5l-1.45 1.45"/></svg>';
        right.insertBefore(a, right.firstChild);
    }

    // v1.36.0 — Navbar bekommt beim Scrollen eine dezente Schatten-Kante,
    // damit sich die Glass-Bar sauber vom Content abhebt.
    function attachScrollShadow() {
        const nav = document.querySelector('.navbar');
        if (!nav) return;
        let ticking = false;
        const update = () => {
            nav.classList.toggle('scrolled', window.scrollY > 4);
            ticking = false;
        };
        window.addEventListener('scroll', () => {
            if (!ticking) { requestAnimationFrame(update); ticking = true; }
        }, { passive: true });
        update();
    }

    // v1.37.0 — Mobile Bottom Tab-Bar (nur < 720px).
    // Kein HTML-Touch pro Seite: wir injizieren die Bar hier auf ALLEN
    // Seiten, die eine .navbar haben (== eingeloggte Modul-Seiten). Der
    // Modul-Switcher oben rechts bleibt fuer den vollstaendigen Zugriff.
    //
    // v1.51.0 — Die Belegung ist einstellbar: zwei bis sechs Module in
    // selbst gewaehlter Reihenfolge, gespeichert am Konto (/api/ui/nav-tabs)
    // statt pro Geraet. Der localStorage-Eintrag ist nur ein Cache, damit die
    // Leiste beim Seitenwechsel sofort in der richtigen Belegung steht statt
    // erst nach der Antwort des Servers umzuspringen.
    const NAV_TABS_DEFAULT = ['/', '/sparziel/', '/ausgaben/', '/notizen/'];
    const NAV_TABS_CACHE = 'vexbob_nav_tabs';
    const NAV_TABS_MIN = 2, NAV_TABS_MAX = 6;

    const TAB_ICONS = {
        // Schlichte, konsistente Line-Icons (24er-Grid).
        home:   '<path d="M4 11.5 12 4l8 7.5V20a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1v-8.5Z"/>',
        coin:   '<circle cx="12" cy="12" r="8"/><path d="M12 7v10M9 9.5c0-1 1.2-1.7 3-1.7s3 .7 3 1.9-1.2 1.6-3 1.8-3 .7-3 1.9 1.2 1.9 3 1.9 3-.8 3-1.8"/>',
        wallet: '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H19a2 2 0 0 1 2 2v2H5.5A2.5 2.5 0 0 1 3 6.5Z"/><path d="M3 8v9a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-3h-4a2 2 0 1 1 0-4h4V9"/>',
        note:   '<path d="M6 3h9l5 5v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z"/><path d="M14 3v6h6M8 13h8M8 17h5"/>',
        pulse:  '<path d="M3 12h4l2.5-6 4 12L16 12h5"/>',
        news:   '<path d="M4 5h11a1 1 0 0 1 1 1v13H5a1 1 0 0 1-1-1V5Z"/><path d="M16 9h3a1 1 0 0 1 1 1v7a2 2 0 0 1-2 2M7 8.5h5M7 12h5M7 15.5h3"/>',
        users:  '<circle cx="9" cy="8" r="3"/><path d="M3.5 20a5.5 5.5 0 0 1 11 0"/><path d="M16 5.5a3 3 0 0 1 0 5M15.5 14.8A5.5 5.5 0 0 1 20.5 20"/>',
    };

    function moduleFor(href) {
        for (const m of MODULES) if (m.href === href) return m;
        return null;
    }
    function readTabCache() {
        try {
            const arr = JSON.parse(localStorage.getItem(NAV_TABS_CACHE) || 'null');
            return (Array.isArray(arr) && arr.length) ? arr : null;
        } catch (e) { return null; }
    }
    function writeTabCache(tabs) {
        try { localStorage.setItem(NAV_TABS_CACHE, JSON.stringify(tabs)); } catch (e) {}
    }

    function renderTabBar(hrefs) {
        // Nur auf geschuetzten Seiten und nur eingeloggt.
        if (!document.querySelector('.navbar')) return;
        try { if (typeof isLoggedIn === 'function' && !isLoggedIn()) return; } catch (e) { return; }

        // Ziele, die dieses Konto nicht (mehr) sehen darf, fliegen raus: die
        // gespeicherte Auswahl kann aus einer Zeit stammen, in der es sie noch
        // gab (Admin-Rechte entzogen).
        const allowed = visibleModules ? new Set(visibleModules.map(m => m.href)) : null;
        const items = (hrefs && hrefs.length ? hrefs : NAV_TABS_DEFAULT)
            .map(moduleFor)
            .filter(m => m && TAB_ICONS[m.icon] && (!allowed || allowed.has(m.href)))
            .slice(0, NAV_TABS_MAX);

        let bar = document.querySelector('.mobile-tabbar');
        if (!items.length) {
            if (bar) bar.remove();
            document.body.classList.remove('has-mobile-tabbar');
            return;
        }
        if (!bar) {
            bar = document.createElement('nav');
            bar.className = 'mobile-tabbar';
            bar.setAttribute('aria-label', 'Hauptnavigation');
            document.body.appendChild(bar);
        }
        // Anzahl steuert die Schriftgroesse der Label (CSS) -- bei sechs
        // Tabs auf einem schmalen iPhone waere die normale zu breit.
        bar.dataset.count = String(items.length);
        bar.innerHTML = items.map(m => {
            const active = isActive(m.href) ? ' active' : '';
            const svg = '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + TAB_ICONS[m.icon] + '</svg>';
            return '<a href="' + m.href + '" class="mtab' + active + '">' + svg +
                   '<span class="mtab-lbl">' + m.short + '</span></a>';
        }).join('');
        document.body.classList.add('has-mobile-tabbar');
    }

    async function startTabBar() {
        // Auf oeffentlichen Seiten (Blog ohne Navbar) gibt es keine Leiste --
        // dann auch keinen Request dafuer.
        if (!document.querySelector('.navbar')) return;
        renderTabBar(readTabCache());
        try {
            if (typeof apiCall !== 'function') return;
            if (typeof isLoggedIn !== 'function' || !isLoggedIn()) return;
            const res = await apiCall('/api/ui/nav-tabs');
            const tabs = (res && Array.isArray(res.tabs) && res.tabs.length)
                ? res.tabs : NAV_TABS_DEFAULT;
            writeTabCache(tabs);
            renderTabBar(tabs);
        } catch (e) {
            // Offline oder Server weg: die Leiste aus dem Cache steht schon.
        }
    }

    // ---------------------------------------------------------------------
    // v1.51.0 — Einstell-Dialog fuer die Tab-Leiste
    // ---------------------------------------------------------------------
    // Bewusst mit Hoch/Runter-Knoepfen statt Drag & Drop: die Liste ist kurz,
    // der Dialog wird zu 99 % auf dem Handy geoeffnet, und ein Tipp-Ziel von
    // 44 Pixeln trifft dort jeder -- ein Ziehen mit gedruecktem Finger neben
    // einer scrollenden Modal-Flaeche nicht.
    function openNavSettings() {
        const choices = (visibleModules && visibleModules.length ? visibleModules : MODULES)
            .filter(m => TAB_ICONS[m.icon]);
        const known = new Set(choices.map(m => m.href));
        let sel = (readTabCache() || NAV_TABS_DEFAULT).filter(h => known.has(h));
        if (!sel.length) sel = NAV_TABS_DEFAULT.filter(h => known.has(h));

        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay navcfg-overlay';
        overlay.innerHTML =
            '<div class="modal-box navcfg-box" role="dialog" aria-modal="true" aria-label="Tab-Leiste anpassen">' +
                '<div class="modal-head">' +
                    '<h3>Tab-Leiste anpassen</h3>' +
                    '<button type="button" class="modal-close" data-act="close" aria-label="Schließen">✕</button>' +
                '</div>' +
                '<div class="modal-body">' +
                    '<p class="navcfg-hint">Die Leiste am unteren Rand auf dem Handy. ' +
                        NAV_TABS_MIN + ' bis ' + NAV_TABS_MAX + ' Module, angezeigt in der ' +
                        'Reihenfolge dieser Liste.</p>' +
                    '<div class="navcfg-list navcfg-sel"></div>' +
                    '<div class="navcfg-sub">Nicht in der Leiste</div>' +
                    '<div class="navcfg-list navcfg-avail"></div>' +
                '</div>' +
                '<div class="navcfg-actions">' +
                    '<button type="button" class="navcfg-btn" data-act="reset">Standard</button>' +
                    '<button type="button" class="navcfg-btn navcfg-save" data-act="save">Speichern</button>' +
                '</div>' +
            '</div>';
        document.body.appendChild(overlay);

        const box = overlay.querySelector('.navcfg-box');
        const selBox = overlay.querySelector('.navcfg-sel');
        const availBox = overlay.querySelector('.navcfg-avail');
        const subLbl = overlay.querySelector('.navcfg-sub');
        const saveBtn = overlay.querySelector('.navcfg-save');

        const iconSvg = (m) => '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + TAB_ICONS[m.icon] + '</svg>';
        const rowHtml = (m, buttons) =>
            '<div class="navcfg-row">' +
                '<span class="navcfg-ico">' + iconSvg(m) + '</span>' +
                '<span class="navcfg-name">' + m.short + '</span>' +
                '<span class="navcfg-btns">' + buttons + '</span>' +
            '</div>';

        function render() {
            selBox.innerHTML = sel.map((href, i) => {
                const m = moduleFor(href);
                if (!m) return '';
                const up = '<button type="button" class="navcfg-mini" data-act="up" data-href="' + href + '"' +
                    (i === 0 ? ' disabled' : '') + ' aria-label="Nach oben">↑</button>';
                const down = '<button type="button" class="navcfg-mini" data-act="down" data-href="' + href + '"' +
                    (i === sel.length - 1 ? ' disabled' : '') + ' aria-label="Nach unten">↓</button>';
                const rm = '<button type="button" class="navcfg-mini navcfg-rm" data-act="remove" data-href="' + href + '"' +
                    (sel.length <= NAV_TABS_MIN ? ' disabled' : '') + ' aria-label="Entfernen">✕</button>';
                return rowHtml(m, up + down + rm);
            }).join('');

            const rest = choices.filter(m => sel.indexOf(m.href) === -1);
            const full = sel.length >= NAV_TABS_MAX;
            subLbl.style.display = rest.length ? '' : 'none';
            availBox.innerHTML = rest.map(m => rowHtml(m,
                '<button type="button" class="navcfg-mini navcfg-add" data-act="add" data-href="' + m.href + '"' +
                (full ? ' disabled' : '') + ' aria-label="Hinzufügen">+</button>')).join('');
            saveBtn.disabled = sel.length < NAV_TABS_MIN;
            saveBtn.textContent = 'Speichern (' + sel.length + '/' + NAV_TABS_MAX + ')';
        }

        const close = () => {
            overlay.classList.remove('show');
            document.removeEventListener('keydown', onKey);
            setTimeout(() => overlay.remove(), 180);
        };
        const onKey = (e) => { if (e.key === 'Escape') close(); };
        document.addEventListener('keydown', onKey);
        overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });

        box.addEventListener('click', async (e) => {
            const btn = e.target.closest('button');
            if (!btn) return;
            const act = btn.dataset.act;
            const href = btn.dataset.href;
            const i = sel.indexOf(href);
            if (act === 'close') return close();
            if (act === 'add' && sel.length < NAV_TABS_MAX) { sel.push(href); render(); return; }
            if (act === 'remove' && sel.length > NAV_TABS_MIN) { sel.splice(i, 1); render(); return; }
            if (act === 'up' && i > 0) { sel.splice(i - 1, 0, sel.splice(i, 1)[0]); render(); return; }
            if (act === 'down' && i >= 0 && i < sel.length - 1) { sel.splice(i + 1, 0, sel.splice(i, 1)[0]); render(); return; }
            if (act === 'reset') {
                btn.disabled = true;
                try {
                    await apiCall('/api/ui/nav-tabs', { method: 'DELETE' });
                    sel = NAV_TABS_DEFAULT.filter(h => known.has(h));
                    writeTabCache(NAV_TABS_DEFAULT);
                    renderTabBar(NAV_TABS_DEFAULT);
                    render();
                    if (window.Toast) Toast.success('Standardbelegung wiederhergestellt');
                } catch (err) {
                    if (window.Toast) Toast.error(err.message);
                } finally { btn.disabled = false; }
                return;
            }
            if (act === 'save') {
                btn.disabled = true;
                try {
                    const res = await apiCall('/api/ui/nav-tabs', { method: 'PUT', body: { tabs: sel } });
                    const tabs = (res && Array.isArray(res.tabs) && res.tabs.length) ? res.tabs : sel;
                    writeTabCache(tabs);
                    renderTabBar(tabs);
                    if (window.Toast) Toast.success('Tab-Leiste gespeichert');
                    close();
                } catch (err) {
                    btn.disabled = false;
                    if (window.Toast) Toast.error(err.message); else alert(err.message);
                }
            }
        });

        render();
        requestAnimationFrame(() => overlay.classList.add('show'));
    }

    // v1.37.0 — UI-Utilities (Toast, Confirm) lazy nachladen.
    // Kein HTML-Touch pro Seite noetig; jede Modul-Seite bekommt Toast/Confirm.
    function loadUIUtils() {
        if (!window.__vexbobUI && !document.querySelector('script[data-vexbob-ui]')) {
            const s = document.createElement('script');
            s.src = '/js/ui.js'; s.defer = true;
            s.setAttribute('data-vexbob-ui', '1');
            document.head.appendChild(s);
        }
        // v1.38.0: Versions-Zeitstrahl-Handler pro Seite nachladen (idempotent).
        if (!window.__vexbobVersionTimeline && !document.querySelector('script[data-vexbob-vtl]')) {
            const s2 = document.createElement('script');
            s2.src = '/js/version-timeline.js'; s2.defer = true;
            s2.setAttribute('data-vexbob-vtl', '1');
            document.head.appendChild(s2);
        }
    }

    // Die Einstellungsseite baut ihre Bedienung aus denselben Daten -- deshalb
    // liegen Modul-Liste, Icons und der Tab-Leisten-Dialog hier offen statt in
    // einer zweiten Liste, die mit der Zeit auseinanderlaeuft.
    window.VexNav = {
        modules: () => (visibleModules || MODULES).filter(m => TAB_ICONS[m.icon]),
        iconSvg: moduleIconSvg,
        openTabBarSettings: openNavSettings,
        readDesktopOrder: readDesktopCache,
        // Der Cache haengt an VexPrefs.set() -- hier wird nur neu gezeichnet.
        redrawDesktop: () => { if (visibleModules) renderModuleRow(visibleModules); },
        DESKTOP_PREF: DESKTOP_PREF,
    };

    async function boot() {
        // build() ermittelt nebenbei, welche Module dieses Konto sehen darf --
        // die Tab-Leiste braucht das, also erst danach.
        await build();
        attachScrollShadow();
        startTabBar();
        loadUIUtils();
        // Wer auf die Modul-Liste angewiesen ist (die Einstellungsseite),
        // wartet auf dieses Signal statt zu pollen.
        document.dispatchEvent(new CustomEvent('vexnav:ready'));
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
