/* html-sauber.js — v2.40.0
 *
 * Gespeichertes HTML (Blog) vor dem Einsetzen bereinigen: eine feste Liste
 * erlaubter Elemente und Attribute, alles andere faellt weg.
 *
 * Bis v2.39.0 stand eine eigene Fassung in blog/blog.js, und sie hatte ein
 * Loch: ein nicht erlaubtes Element wurde ausgepackt, sein Inhalt danach aber
 * nicht mehr geprueft -- ein <img onerror> in einem <form> kam samt onerror
 * durch. Deshalb wird hier ERST der Inhalt bereinigt und DANN entschieden,
 * was mit dem Element selbst geschieht. Der Blog liegt auf derselben Domain
 * wie die App; ein Skript dort saehe das Anmelde-Token im localStorage.
 *
 * Der Blog-Editor nimmt denselben Baustein: auch dort landete gespeichertes
 * HTML ungeprueft in der Seite.
 */
(function () {
    if (window.VexHtml) return;

    const ERLAUBT = new Set(['P', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'UL', 'OL', 'LI', 'BLOCKQUOTE',
        'PRE', 'CODE', 'STRONG', 'B', 'EM', 'I', 'U', 'S', 'A', 'BR', 'HR', 'IMG', 'DIV', 'SPAN']);
    // Ganz weg, samt Inhalt: ausgepackt hinterliessen sie Quelltext als Text
    // oder Inhalt aus einem anderen Namensraum (SVG, MathML), der beim
    // zweiten Einlesen anders gelesen wird als beim ersten.
    const WEG = new Set(['SCRIPT', 'STYLE', 'TEMPLATE', 'IFRAME', 'FRAME', 'FRAMESET', 'OBJECT', 'EMBED',
        'APPLET', 'SVG', 'MATH', 'NOSCRIPT', 'NOEMBED', 'NOFRAMES', 'XMP', 'PLAINTEXT', 'TEXTAREA',
        'SELECT', 'OPTION', 'BUTTON', 'INPUT', 'FORM', 'LINK', 'META', 'BASE', 'TITLE']);
    const ATTRIBUTE = {
        A: ['href', 'title'],
        IMG: ['src', 'alt', 'title'],
        DIV: ['class', 'data-done'],
        SPAN: ['class', 'contenteditable'],
    };
    // „//andere.seite“ waere ein fremder Link, der wie ein eigener aussieht.
    const LINK_OK = /^(https?:\/\/|mailto:|#|\/(?!\/))/i;
    const BILD_OK = /^(https?:\/\/|\/(?!\/)|data:image\/(png|jpe?g|gif|webp);base64,)/i;

    function reinigen(knoten) {
        Array.from(knoten.childNodes).forEach((kind) => {
            if (kind.nodeType === 3) return;                     // Text bleibt
            if (kind.nodeType !== 1) { kind.remove(); return; }   // Kommentare u. a.
            // In einem HTML-Dokument heisst <svg> „svg“, nicht „SVG“.
            const tag = kind.tagName.toUpperCase();
            if (WEG.has(tag)) { kind.remove(); return; }
            reinigen(kind);
            if (!ERLAUBT.has(tag)) { kind.replaceWith(...kind.childNodes); return; }
            const behalten = ATTRIBUTE[tag] || [];
            Array.from(kind.attributes).forEach((a) => {
                const name = a.name.toLowerCase();
                const wert = a.value.trim();
                if (!behalten.includes(name)
                    || (name === 'href' && !LINK_OK.test(wert))
                    || (name === 'src' && !BILD_OK.test(wert))
                    || (name === 'contenteditable' && wert !== 'false')) {
                    kind.removeAttribute(a.name);
                }
            });
            if (tag === 'A' && kind.hasAttribute('href')) {
                kind.setAttribute('target', '_blank');
                kind.setAttribute('rel', 'noopener noreferrer');
            }
        });
    }

    function sauber(html) {
        const doc = new DOMParser().parseFromString(String(html || ''), 'text/html');
        reinigen(doc.body);
        return doc.body.innerHTML;
    }

    window.VexHtml = { sauber };
})();
