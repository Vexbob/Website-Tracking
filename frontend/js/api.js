const API_BASE = 'https://vexbob-production.up.railway.app';

function getToken() { return localStorage.getItem('token'); }
function setToken(token) { localStorage.setItem('token', token); }
function clearToken() { localStorage.removeItem('token'); localStorage.removeItem('me'); }
function isLoggedIn() { return !!getToken(); }

async function apiCall(path, options = {}) {
    const token = getToken();
    const headers = { ...(options.headers || {}) };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    // v1.33.0: Content-Type + Body-Serialisierung intelligent ableiten.
    // Alt: Body wurde immer als form-urlencoded verschickt, egal was drinsteht
    // -- neue Aufrufe mit Plain-Objekten landeten still in 422-Fehlern.
    // Neu:
    //   - FormData / Blob / URLSearchParams / string -> unveraendert lassen
    //     (Browser setzt Content-Type mit Boundary etc. selbst korrekt),
    //   - Plain-Object -> JSON.stringify + application/json,
    //   - Content-Type vom Aufrufer wird IMMER respektiert.
    let body = options.body;
    if (body != null && !headers['Content-Type']) {
        const isFormData = typeof FormData !== 'undefined' && body instanceof FormData;
        const isBlob = typeof Blob !== 'undefined' && body instanceof Blob;
        const isUsp = typeof URLSearchParams !== 'undefined' && body instanceof URLSearchParams;
        const isString = typeof body === 'string';
        if (isFormData || isBlob) {
            // Browser setzt Content-Type selbst -> nichts tun.
        } else if (isUsp) {
            headers['Content-Type'] = 'application/x-www-form-urlencoded';
        } else if (isString) {
            headers['Content-Type'] = 'application/x-www-form-urlencoded';
        } else if (typeof body === 'object') {
            body = JSON.stringify(body);
            headers['Content-Type'] = 'application/json';
        }
    }

    let res;
    try {
        res = await fetch(`${API_BASE}${path}`, { ...options, body, headers });
    } catch (e) {
        throw new Error('Netzwerkfehler');
    }
    if (res.status === 401) {
        clearToken();
        if (!location.pathname.endsWith('/login.html')) {
            location.href = '/private/login.html';
        }
        throw new Error('Nicht eingeloggt');
    }
    if (options.raw) return res;
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);
    return data;
}

async function login(username, password) {
    const body = new URLSearchParams({ username, password });
    const data = await apiCall('/token', { method: 'POST', body });
    setToken(data.access_token);
    return data;
}

// Cached user info (id, username, is_admin)
async function fetchMe(force = false) {
    if (!force) {
        const cached = localStorage.getItem('me');
        if (cached) {
            try { return JSON.parse(cached); } catch (e) {}
        }
    }
    const me = await apiCall('/api/me');
    localStorage.setItem('me', JSON.stringify(me));
    return me;
}

function isAdmin() {
    try {
        const me = JSON.parse(localStorage.getItem('me') || 'null');
        return !!(me && me.is_admin);
    } catch (e) { return false; }
}

// Theme
function applyTheme(t) {
    document.documentElement.setAttribute('data-theme', t);
    localStorage.setItem('theme', t);
}
function currentTheme() {
    // v1.36.0: Standard ist jetzt Dark-Mode (auch wenn OS auf hell steht).
    // Nutzer koennen ueber den Theme-Toggle weiterhin manuell wechseln;
    // die Praeferenz wird in localStorage persistiert.
    return localStorage.getItem('theme') || 'dark';
}
function toggleTheme() {
    applyTheme(currentTheme() === 'dark' ? 'light' : 'dark');
}
applyTheme(currentTheme());

// German locale helpers
const _eurFmt = new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', minimumFractionDigits: 2, maximumFractionDigits: 2 });
const _numFmt = new Intl.NumberFormat('de-DE', { maximumFractionDigits: 2 });
function fmtEur(n) { return _eurFmt.format(Number(n) || 0); }
function fmtNum(n, digits) {
    if (digits != null) return new Intl.NumberFormat('de-DE', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(Number(n) || 0);
    return _numFmt.format(Number(n) || 0);
}

// Haptic Feedback (nur wenn vom Gerät unterstützt)
function haptic(pattern) {
    try {
        if (!('vibrate' in navigator)) return;
        // pattern: 'tap' | 'success' | 'error' | Array<number>
        if (pattern === 'tap') navigator.vibrate(15);
        else if (pattern === 'success') navigator.vibrate([25, 40, 25]);
        else if (pattern === 'error') navigator.vibrate([50, 60, 50, 60, 100]);
        else if (Array.isArray(pattern)) navigator.vibrate(pattern);
    } catch(e) {}
}

// Auto-inject APP_VERSION into all .version-tag elements
document.addEventListener('DOMContentLoaded', () => {
    const v = typeof APP_VERSION !== 'undefined' ? APP_VERSION : '';
    document.querySelectorAll('.version-tag').forEach(el => { el.textContent = v; });
});