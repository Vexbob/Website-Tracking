/* bild.js — v1.99.0
 *
 * Bilder, die am Konto haengen: verkleinern, mit Anmeldung laden, im Vollbild
 * zeigen. Drei Dinge, die bisher ausschliesslich in
 * ``frontend/ausgaben/ausgaben.js`` standen -- obwohl das zugehoerige CSS
 * (`.img-fullscreen`, `.img-close`) laengst in css/style.css liegt. Mit dem
 * zweiten Modul, das Bilder zeigt (Gerichtsfotos), waeren daraus zwei
 * Fassungen geworden, und genau das schliesst das Designsystem aus.
 *
 *     VexBild.komprimieren(file)      -> File (JPEG, hoechstens 1600 px)
 *     await VexBild.alsBlobUrl(url)   -> Blob-URL (mit Bearer-Token geholt)
 *     VexBild.vollbild(src, alt)      -> Overlay, Escape/Klick schliesst
 *
 * Warum ``alsBlobUrl``: die Bild-Endpunkte verlangen eine Anmeldung, und ein
 * nacktes ``<img src>`` schickt keinen Authorization-Header. Das Bild wird
 * deshalb geholt und als Blob-URL eingehaengt.
 */
(function () {
    if (window.VexBild) return;

    /* Vor dem Hochladen verkleinern. Der Server rechnet danach noch einmal
       (1600 px, JPEG q82) -- das hier spart die Uebertragung, nicht die
       Verarbeitung: ein Handyfoto sind gern 5 MB, und davon kommt nach dem
       Verkleinern ein Zehntel an. */
    function komprimieren(file, maxDim, quality) {
        maxDim = maxDim || 1600;
        quality = quality == null ? 0.85 : quality;
        return new Promise((fertig, fehler) => {
            const img = new Image();
            const url = URL.createObjectURL(file);
            img.onload = () => {
                const w = img.naturalWidth, h = img.naturalHeight;
                const faktor = Math.min(1, maxDim / Math.max(w, h));
                const cw = Math.round(w * faktor), ch = Math.round(h * faktor);
                const canvas = document.createElement('canvas');
                canvas.width = cw; canvas.height = ch;
                canvas.getContext('2d').drawImage(img, 0, 0, cw, ch);
                URL.revokeObjectURL(url);
                canvas.toBlob((blob) => {
                    if (!blob) { fehler(new Error('Kompression fehlgeschlagen')); return; }
                    const name = (file.name || 'bild.jpg').replace(/\.[^.]+$/, '') + '.jpg';
                    fertig(new File([blob], name, { type: 'image/jpeg' }));
                }, 'image/jpeg', quality);
            };
            img.onerror = () => {
                URL.revokeObjectURL(url);
                fehler(new Error('Bild kann nicht geladen werden'));
            };
            img.src = url;
        });
    }

    async function alsBlobUrl(url) {
        const res = await fetch(url, {
            headers: { 'Authorization': 'Bearer ' + getToken() },
        });
        if (!res.ok) throw new Error('Bild laden fehlgeschlagen');
        return URL.createObjectURL(await res.blob());
    }

    /* Vollbild. Der Alternativtext ist ein Parameter und nicht fest "Bon":
       unter einem Gerichtsfoto stuende sonst das falsche Wort. */
    function vollbild(src, alt) {
        const overlay = document.createElement('div');
        overlay.className = 'img-fullscreen';
        overlay.innerHTML = '<button class="img-close" aria-label="Schließen">✕</button>'
            + '<img src="' + src + '" alt="' + String(alt || 'Bild').replace(/"/g, '&quot;') + '">';
        document.body.appendChild(overlay);
        requestAnimationFrame(() => overlay.classList.add('show'));
        const close = () => {
            overlay.classList.remove('show');
            setTimeout(() => overlay.remove(), 200);
            document.removeEventListener('keydown', onKey);
        };
        const onKey = (e) => { if (e.key === 'Escape') close(); };
        overlay.onclick = (e) => {
            if (e.target === overlay || e.target.classList.contains('img-close')) close();
        };
        document.addEventListener('keydown', onKey);
        return { close };
    }

    window.VexBild = { komprimieren, alsBlobUrl, vollbild };
})();
