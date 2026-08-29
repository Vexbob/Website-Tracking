/* nav-switcher.js — v1.18.1
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

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => { build(); attachScrollShadow(); });
    } else {
        build(); attachScrollShadow();
    }
})();
