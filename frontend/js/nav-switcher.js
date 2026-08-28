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
        const active = visible.find(m => isActive(m.href));
        btn.innerHTML = `<span class="nav-switcher-ico">⊞</span><span class="nav-switcher-lbl">${active ? active.label.split(' ').slice(1).join(' ') : 'Module'}</span><span class="nav-switcher-arrow">▾</span>`;

        const menu = document.createElement('div');
        menu.className = 'nav-switcher-menu';
        menu.innerHTML = visible.map(m => {
            const cls = isActive(m.href) ? 'active' : '';
            return `<a href="${m.href}" class="nav-switcher-item ${cls}">${m.label}</a>`;
        }).join('');

        wrapper.appendChild(btn);
        wrapper.appendChild(menu);
        navbar.appendChild(wrapper);

        // Toggle
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const open = menu.classList.toggle('open');
            if (open) menu.style.display = 'flex';
            else menu.style.display = '';
        });
        // Außen-Klick schließt
        document.addEventListener('click', (e) => {
            if (!wrapper.contains(e.target)) {
                menu.classList.remove('open');
                menu.style.display = '';
            }
        });
        // ESC schließt
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                menu.classList.remove('open');
                menu.style.display = '';
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', build);
    } else {
        build();
    }
})();
