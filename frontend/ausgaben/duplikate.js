async function init() {
    const me = await ensureLoggedIn(); if (!me) return;
    renderSubnav();
    await loadDuplicates();
    document.body.classList.add('ready');
    document.body.style.visibility = 'visible';
}

function escapeHtml(s) {
    if (!s) return '';
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function loadDuplicates() {
    const list = document.getElementById('duplicatesList');
    list.innerHTML = '<div class="muted">Laden …</div>';
    try {
        const data = await AUSGABEN_API.duplicateGroups();
        const groups = data.groups || [];
        if (!groups.length) {
            list.innerHTML = '<div class="empty"><div class="empty-icon">✅</div>Keine Duplikate gefunden.</div>';
            return;
        }
        list.innerHTML = groups.map((g, gi) => {
            const rows = g.items.map(it => `
                <div class="dup-row${it.id === g.keep_id ? ' dup-keep' : ''}">
                    <span class="dot"></span>
                    <span>${it.store_icon} <strong>${escapeHtml(it.store_name)}</strong></span>
                    <span>${fmtDate(it.purchase_date)}</span>
                    <span>${fmtEur(it.total_amount)}</span>
                    <span class="muted">${it.item_count} Positionen${it.has_image ? ' · 📷 Beleg' : ''}</span>
                    ${it.id === g.keep_id ? '<span class="muted">← wird behalten</span>' : ''}
                </div>`).join('');
            const allIds = g.items.map(it => it.id);
            const removeIds = allIds.filter(id => id !== g.keep_id);
            return `<div class="dup-group" data-idx="${gi}">
                <button type="button" class="dup-dismiss" data-ids="${allIds.join(',')}" title="Vorschlag ausblenden">✕</button>
                ${rows}
                <button class="btn-merge" data-keep="${g.keep_id}" data-remove="${removeIds.join(',')}">Zusammenführen</button>
            </div>`;
        }).join('');
        list.querySelectorAll('.btn-merge').forEach(btn => {
            btn.onclick = async () => {
                const keepId = parseInt(btn.dataset.keep, 10);
                const removeIds = btn.dataset.remove.split(',').filter(Boolean).map(Number);
                btn.disabled = true; btn.textContent = 'Führe zusammen …';
                try {
                    await AUSGABEN_API.mergeDuplicates(keepId, removeIds);
                    showToast('Duplikate zusammengeführt', 'success');
                    await loadDuplicates();
                } catch (e) {
                    showToast('Fehler: ' + e.message, 'error');
                    btn.disabled = false; btn.textContent = 'Zusammenführen';
                }
            };
        });
        list.querySelectorAll('.dup-dismiss').forEach(btn => {
            btn.onclick = async () => {
                const ids = btn.dataset.ids.split(',').filter(Boolean).map(Number);
                btn.disabled = true;
                try {
                    await AUSGABEN_API.dismissDuplicate(ids);
                    showToast('Vorschlag ausgeblendet', 'success', 1200);
                    await loadDuplicates();
                } catch (e) {
                    showToast('Fehler: ' + e.message, 'error');
                    btn.disabled = false;
                }
            };
        });
    } catch (e) { list.innerHTML = '<div class="muted">Fehler: ' + e.message + '</div>'; }
}

init();
