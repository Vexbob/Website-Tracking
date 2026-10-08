/* bon.js — v2.21.0
 *
 * Der Bon als Kassenzettel. Bis v2.20.0 war diese Seite ein Formular: Typ,
 * Datum, Laden, Betrag und Notiz als Felder, darunter die Positionen als
 * Eingabezeilen mit 📊, 🚫 und ✕. Angesehen wird ein Bon aber viel öfter,
 * als er geändert wird -- jetzt steht er da wie auf Papier (kassenzettelHTML
 * in ausgaben.js, dieselbe Gestalt wie im Blatt der Übersicht), und Ändern
 * und Positionen stehen je in einem Dialog (DESIGN 6d).
 *
 * Jeder Aufruf an den Server ist derselbe geblieben.
 */
let stores = [], categories = [];
let currentExpense = null;
let imgBlobUrl = null;

function getId() {
    const p = new URLSearchParams(location.search);
    return +p.get('id') || null;
}
function escapeHtml(s) { if (s == null) return ''; return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function escapeAttr(s) { return escapeHtml(s); }
function ikon(name, groesse) { return window.VexIkon ? VexIkon.svg(name, groesse || 18) : ''; }

async function init() {
    const me = await ensureLoggedIn(); if (!me) return;
    renderSubnav();
    const id = getId();
    if (!id) { location.href = '/ausgaben/'; return; }
    try {
        [stores, categories, currentExpense] = await Promise.all([
            AUSGABEN_API.stores(), AUSGABEN_API.categories(), AUSGABEN_API.getExpense(id)
        ]);
    } catch (e) {
        document.getElementById('content').innerHTML = `<div class="empty is-error"><p class="empty-text">Dieser Bon konnte nicht geladen werden: ${escapeHtml(e.message)}</p>
            <a class="v-btn v-btn--sm" href="/ausgaben/">Zur Übersicht</a></div>`;
        return;
    }
    await loadExpenseTypes();
    document.getElementById('eEdit').onclick = dlgBearbeiten;
    document.getElementById('ePositionen').onclick = dlgPositionen;
    await render();
}

async function render() {
    const e = currentExpense;
    document.title = (e.store_name || expenseTypeLabel(e.expense_type)) + ' — Vexbob';
    const titel = document.querySelector('.navbar .nav-title');
    if (titel) titel.textContent = 'Bon';
    // Das Foto steht neben dem Zettel, nicht darin: hier ist Platz für die
    // ganze Aufnahme, und der Zettel bleibt so lang wie der Bon.
    document.getElementById('content').innerHTML = kassenzettelHTML(e, null);
    document.getElementById('azBonSeite').hidden = false;
    const foto = document.getElementById('azBonFoto');
    if (e.receipt_image_id) {
        try {
            if (imgBlobUrl) URL.revokeObjectURL(imgBlobUrl);
            imgBlobUrl = await fetchImageAsBlobUrl(AUSGABEN_API.receiptImageUrl(e.receipt_image_id));
            foto.innerHTML = `<img src="${imgBlobUrl}" class="az-bon-foto" alt="Foto des Bons">`;
            foto.querySelector('img').onclick = () => openImageFullscreen(imgBlobUrl);
        } catch (err) {
            foto.innerHTML = '<p class="az-bon-hinweis">Das Foto konnte nicht geladen werden.</p>';
        }
    } else {
        foto.innerHTML = '';
    }
}

// ---------- Bearbeiten: die Angaben des Bons ----------
function dlgBearbeiten() {
    const e = currentExpense;
    const storeOpts = '<option value="">Kein Laden</option>' +
        stores.map(s => `<option value="${s.id}"${e.store_id == s.id ? ' selected' : ''}>${s.icon || ''} ${escapeHtml(s.name)}</option>`).join('');
    // Typen kommen vom Server (eingebaute + eigene, die der KI-Parser vergeben hat).
    const typeOpts = expenseTypeOptions(e.expense_type || 'receipt');
    const d = openModal('Bon bearbeiten', `<form data-form>
        <label for="eType">Typ</label><select id="eType">${typeOpts}</select>
        <div class="az-felder">
            <div><label for="eDate">Datum</label><input type="date" id="eDate" value="${escapeAttr(e.purchase_date || '')}"></div>
            <div><label for="eTotal">Summe (€)</label><input type="number" step="0.01" inputmode="decimal" id="eTotal" value="${e.total_amount != null ? escapeAttr(e.total_amount) : ''}"></div>
        </div>
        <label for="eStore">Laden</label><select id="eStore">${storeOpts}</select>
        <label for="eNote">Notiz</label><textarea id="eNote" rows="3">${escapeHtml(e.note || '')}</textarea>
        <div class="modal-fuss">
            <button type="button" class="v-btn v-btn--danger" data-weg>${ikon('muell', 16)} Löschen</button>
            <button type="submit" class="v-btn v-btn--primary" id="eSave">Speichern</button>
        </div>
    </form>`);
    d.root.querySelector('[data-form]').addEventListener('submit', (ev) => { ev.preventDefault(); saveExpense(d); });
    d.root.querySelector('[data-weg]').addEventListener('click', () => deleteExpense(d));
}

async function saveExpense(d) {
    const btn = document.getElementById('eSave'); if (btn) btn.disabled = true;
    try {
        const body = {
            store_id: +document.getElementById('eStore').value || null,
            purchase_date: document.getElementById('eDate').value,
            total_amount: +document.getElementById('eTotal').value || 0,
            is_recurring: false,
            expense_type: document.getElementById('eType').value || 'receipt',
            note: document.getElementById('eNote').value || null,
        };
        await AUSGABEN_API.updateExpense(currentExpense.id, body);
        // Die Antwort auf das Speichern traegt keine Positionen; der Zettel
        // braucht sie -- also frisch holen statt den Rest zu erraten.
        currentExpense = await AUSGABEN_API.getExpense(currentExpense.id);
        if (d) d.close();
        showToast('Gespeichert', 'success');
        await render();
    } catch (e) { showToast('Speichern fehlgeschlagen: ' + e.message, 'error'); }
    finally { if (btn && btn.isConnected) btn.disabled = false; }
}

async function deleteExpense(d) {
    if (!await askConfirm({ title: 'Diesen Bon löschen?',
        text: 'Bon, Positionen und das hinterlegte Foto werden entfernt. Das lässt sich nicht rückgängig machen.',
        ok: 'Löschen', danger: true })) return;
    try {
        await AUSGABEN_API.deleteExpense(currentExpense.id);
        if (d) d.close();
        showToast('Gelöscht', 'success');
        setTimeout(() => location.href = '/ausgaben/', 500);
    } catch (e) { showToast('Löschen fehlgeschlagen: ' + e.message, 'error'); }
}

// ---------- Positionen ----------
/* Die Positionen in einem bildschirmfüllenden Dialog: jede Zeile speichert
   beim Verlassen eines Feldes (wie bisher), der Zettel wird beim Schließen
   aus dem Server neu gezeichnet. */
function dlgPositionen() {
    const d = openModal('Positionen', `
        <div id="itemList" class="az-posliste"></div>
        <button type="button" class="v-btn v-btn--ghost" id="addItemBtn">${ikon('plus', 16)} Position hinzufügen</button>
        <div class="modal-fuss"><button type="button" class="v-btn v-btn--primary" data-fertig>Fertig</button></div>`,
        { voll: true, breit: true, beimSchliessen: async () => {
            try { currentExpense = await AUSGABEN_API.getExpense(currentExpense.id); await render(); }
            catch (e) { showToast('Neu laden fehlgeschlagen: ' + e.message, 'error'); }
        } });
    d.root.querySelector('[data-fertig]').addEventListener('click', () => d.close());
    d.root.querySelector('#addItemBtn').addEventListener('click', () => addNewItem());
    renderItems();
}

function renderItems() {
    const c = document.getElementById('itemList');
    c.innerHTML = '';
    if (!currentExpense.items || currentExpense.items.length === 0) {
        c.innerHTML = '<p class="az-bon-hinweis">Keine Positionen. Für schnelle Ausgaben ohne Details ist das in Ordnung.</p>';
        return;
    }
    currentExpense.items.forEach(it => renderItemRow(it));
}

function renderItemRow(item) {
    const c = document.getElementById('itemList');
    const row = document.createElement('div');
    row.className = 'item-row';
    row.dataset.id = item.id || '';
    // Aus der Produktliste ausgeblendet: sichtbar abheben
    const comparable = item.price_comparable !== false;
    if (!comparable) row.classList.add('not-comparable');
    const catOpts = '<option value="">Keine Kategorie</option>' +
        categories.map(cat => `<option value="${cat.id}"${item.category_id == cat.id ? ' selected' : ''}>${cat.icon || ''} ${escapeHtml(cat.name)}</option>`).join('');
    const cmpTitle = comparable
        ? 'Aus dem Preisvergleich nehmen (z. B. Einmalkauf)'
        : 'Wieder in den Preisvergleich aufnehmen';
    const qty = itemPieceCount(item);
    row.innerHTML = `
        <input type="text" class="d-desc" value="${escapeAttr(item.description || '')}" placeholder="Beschreibung" aria-label="Beschreibung">
        <label class="az-feld az-feld--menge"><input type="number" min="1" step="1" class="d-qty" value="${qty || ''}" placeholder="1" inputmode="numeric" aria-label="Stückzahl" title="Stückzahl — nur ausfüllen, wenn der Artikel mehrfach gekauft wurde"><span aria-hidden="true">×</span></label>
        <label class="az-feld az-feld--preis"><input type="number" step="0.01" class="d-price" value="${item.total_price != null ? escapeAttr(item.total_price) : ''}" placeholder="0,00" inputmode="decimal" aria-label="Preis in Euro"><span aria-hidden="true">€</span></label>
        <select class="d-cat" aria-label="Kategorie">${catOpts}</select>
        <button type="button" class="v-btn v-btn--ghost v-btn--icon cmp" title="${cmpTitle}" aria-label="${cmpTitle}">${ikon(comparable ? 'statistik' : 'augezu', 17)}</button>
        <button type="button" class="v-btn v-btn--ghost v-btn--icon del" title="Position löschen" aria-label="Position löschen">${ikon('muell', 17)}</button>
        ${item.is_reduced ? `<span class="az-reduziert d-red" title="${item.original_price ? 'Vorher: ' + escapeAttr(item.original_price) + ' €' : 'Reduziert'}">reduziert</span>` : ''}
    `;
    c.appendChild(row);
    const save = async () => {
        const desc = row.querySelector('.d-desc').value.trim();
        const price = parseFloat(row.querySelector('.d-price').value);
        const cat = row.querySelector('.d-cat').value;
        if (!desc || isNaN(price)) return;
        // Menge ist eine Stückzahl: leeres Feld heißt 1.
        let q = Math.round(parseFloat((row.querySelector('.d-qty')?.value || '').replace(',', '.')));
        if (!Number.isFinite(q) || q < 1) q = 1;
        item.quantity = q;
        try {
            if (item.id) {
                await AUSGABEN_API.updateItem(item.id, {
                    description: desc, total_price: price,
                    quantity: q,
                    category_id: cat ? +cat : null,
                    price_comparable: item.price_comparable !== false,
                });
            } else {
                const created = await AUSGABEN_API.addItem(currentExpense.id, {
                    description: desc, total_price: price, quantity: q,
                    category_id: cat ? +cat : null,
                });
                item.id = created.id;
                row.dataset.id = created.id;
            }
            showToast('Gespeichert', 'success', 1200);
        } catch (err) { showToast('Speichern fehlgeschlagen: ' + err.message, 'error'); }
    };
    row.querySelectorAll('input, select').forEach(el => { el.onchange = save; });
    // Preisvergleich an/aus
    row.querySelector('.cmp').onclick = async () => {
        if (!item.id) {
            showToast('Erst speichern, dann aus dem Preisvergleich nehmen', 'error');
            return;
        }
        const newVal = !(item.price_comparable !== false);
        try {
            await AUSGABEN_API.setItemComparable(item.id, newVal);
            item.price_comparable = newVal;
            row.classList.toggle('not-comparable', !newVal);
            const btn = row.querySelector('.cmp');
            btn.innerHTML = ikon(newVal ? 'statistik' : 'augezu', 17);
            const t = newVal ? 'Aus dem Preisvergleich nehmen (z. B. Einmalkauf)' : 'Wieder in den Preisvergleich aufnehmen';
            btn.title = t; btn.setAttribute('aria-label', t);
            showToast(newVal ? 'Wieder im Preisvergleich' : 'Aus dem Preisvergleich genommen', 'success', 1500);
        } catch (err) { showToast('Umstellen fehlgeschlagen: ' + err.message, 'error'); }
    };
    row.querySelector('.del').onclick = async () => {
        if (!item.id) { row.remove(); return; }
        if (!await askConfirm({ title: 'Position löschen?',
            text: 'Die Position verschwindet aus diesem Bon und aus der Produktliste.',
            ok: 'Löschen', danger: true })) return;
        try { await AUSGABEN_API.deleteItem(item.id); row.remove(); showToast('Gelöscht', 'success', 1200); }
        catch (err) { showToast('Löschen fehlgeschlagen: ' + err.message, 'error'); }
    };
}

function addNewItem() {
    const c = document.getElementById('itemList');
    const hinweis = c.querySelector('.az-bon-hinweis');
    if (hinweis) hinweis.remove();
    renderItemRow({ description: '', total_price: '', category_id: null, quantity: 1 });
    const letzte = c.lastElementChild && c.lastElementChild.querySelector('.d-desc');
    if (letzte && window.matchMedia('(min-width: 721px)').matches) letzte.focus();
}

init();
