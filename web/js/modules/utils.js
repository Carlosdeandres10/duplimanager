// ─── TOAST SYSTEM ───────────────────────────────────────
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `<span>${message}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// ─── UTILITIES ──────────────────────────────────────────
function formatRepoStorageSummary(repo) {
    if (Array.isArray(repo.storages) && repo.storages.length > 0) {
        const labels = repo.storages.map(s => s.label || s.name || s.type || 'Storage');
        return labels.join(' + ');
    }
    return repo.storageUrl || '—';
}

function getPrimaryStorage(repo) {
    if (!repo || !Array.isArray(repo.storages) || repo.storages.length === 0) return null;
    return repo.storages.find(s => s.isDefault) || repo.storages[0] || null;
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function escapeAttr(str) {
    return String(str || '')
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function formatDate(isoString) {
    if (!isoString) return '—';
    const d = new Date(isoString);
    return d.toLocaleString('es-ES', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit'
    });
}
