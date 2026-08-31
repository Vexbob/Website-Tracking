/* nav-switcher.js — v1.37.0
 * Injiziert einen Modul-Switcher (Dropdown) in jede .navbar.
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
    const MODULES = [
        { href: '/',            label: '🏠 Dashboard',      public: false },
        { href: '/sparziel/',   label: '💰 Sparziel',       public: false },
        { href: '/ausgaben/',   label: '💶 Ausgaben',       public: false },
        { href: '/notizen/',    label: '📝 Notizen',        public: false },
        { href: '/health/',     label: '🏋️ Gesundheit',     public: false },
        { href: '/blog/',       label: '📰 Blog',           public: true, hideForAdmin: true },
        { href: '/blog/admin/', label: '📰 Blog',           public: false, admin: true },
        { href: '/admin/',      label: '👥 User-Verwaltung', public: false, admin: true },
    ];

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
        }).join('');

        wrapper.appendChild(btn);
        wrapper.appendChild(menu);
        navbar.appendChild(wrapper);

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
    // Seiten, die eine .navbar haben (== eingeloggte Modul-Seiten).
    // Zeigt die 4 wichtigsten Alltags-Module. Der Modul-Switcher-Button
    // oben rechts bleibt fuer den vollstaendigen Zugriff (Admin, Blog etc.).
    const TAB_BAR = [
        { href: '/',          label: 'Home',     icon: 'home' },
        { href: '/sparziel/', label: 'Sparen',   icon: 'coin' },
        { href: '/ausgaben/', label: 'Ausgaben', icon: 'wallet' },
        { href: '/notizen/',  label: 'Notizen',  icon: 'note' },
    ];
    const TAB_ICONS = {
        // Schlichte, konsistente Line-Icons (24er-Grid).
        home:   '<path d="M4 11.5 12 4l8 7.5V20a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1v-8.5Z"/>',
        coin:   '<circle cx="12" cy="12" r="8"/><path d="M12 7v10M9 9.5c0-1 1.2-1.7 3-1.7s3 .7 3 1.9-1.2 1.6-3 1.8-3 .7-3 1.9 1.2 1.9 3 1.9 3-.8 3-1.8"/>',
        wallet: '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H19a2 2 0 0 1 2 2v2H5.5A2.5 2.5 0 0 1 3 6.5Z"/><path d="M3 8v9a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-3h-4a2 2 0 1 1 0-4h4V9"/>',
        note:   '<path d="M6 3h9l5 5v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z"/><path d="M14 3v6h6M8 13h8M8 17h5"/>',
    };
    function buildTabBar() {
        // Nur einfuegen, wenn wir eine navbar haben (= geschuetzte Seite),
        // eingeloggt sind, und noch keine Tabbar existiert.
        if (!document.querySelector('.navbar')) return;
        if (document.querySelector('.mobile-tabbar')) return;
        try { if (typeof isLoggedIn === 'function' && !isLoggedIn()) return; } catch (e) { return; }

        const bar = document.createElement('nav');
        bar.className = 'mobile-tabbar';
        bar.setAttribute('aria-label', 'Hauptnavigation');
        bar.innerHTML = TAB_BAR.map(t => {
            const active = isActive(t.href) ? ' active' : '';
            const svg = '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (TAB_ICONS[t.icon] || '') + '</svg>';
            return '<a href="' + t.href + '" class="mtab' + active + '">' + svg + '<span class="mtab-lbl">' + t.label + '</span></a>';
        }).join('');
        document.body.appendChild(bar);
        // Body bekommt Padding, damit Content nicht hinter der Bar verschwindet
        document.body.classList.add('has-mobile-tabbar');
    }

    // v1.37.0 — Theme-Toggle-Button: Emoji 🌓 durch sauberes SVG ersetzen
    // (nur wenn der Button noch das Emoji enthaelt -- respektiert individuelle
    // Anpassungen). Aktualisiert das Icon zusaetzlich passend zum aktiven Theme.
    function upgradeThemeToggle() {
        const btn = document.getElementById('themeBtn');
        if (!btn) return;
        const raw = (btn.textContent || '').trim();
        // Nur ersetzen, wenn wirklich nur das Emoji drinsteht.
        if (raw !== '🌓' && raw !== '') return;
        const render = () => {
            const dark = document.documentElement.getAttribute('data-theme') === 'dark';
            const icon = dark
                ? '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M3 12h2M19 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>'
                : '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg>';
            btn.innerHTML = icon;
            btn.setAttribute('aria-label', dark ? 'Zu hellem Design' : 'Zu dunklem Design');
        };
        render();
        // Beobachte Theme-Wechsel (data-theme aendert sich via toggleTheme in api.js).
        try {
            new MutationObserver(render).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
        } catch (e) {}
    }

    // v1.37.0 — UI-Utilities (Toast, Confirm) lazy nachladen.
    // Kein HTML-Touch pro Seite noetig; jede Modul-Seite bekommt Toast/Confirm.
    function loadUIUtils() {
        if (window.__vexbobUI) return;
        if (document.querySelector('script[data-vexbob-ui]')) return;
        const s = document.createElement('script');
        s.src = '/js/ui.js';
        s.defer = true;
        s.setAttribute('data-vexbob-ui', '1');
        document.head.appendChild(s);
    }

    function boot() {
        build();
        attachScrollShadow();
        buildTabBar();
        upgradeThemeToggle();
        loadUIUtils();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
