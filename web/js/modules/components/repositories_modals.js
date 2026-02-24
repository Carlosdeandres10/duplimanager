// ─── NEW REPO MODAL ─────────────────────────────────────
function openNewRepoModal() {
    document.getElementById('modal-new-repo').classList.add('show');
    document.getElementById('repo-form').reset();
    const modeSelect = document.getElementById('new-repo-mode');
    if (modeSelect) modeSelect.value = 'create';
    newRepoContentState = { rootPath: '', selection: [] };
    updateRepoContentSelectionSummary('new');
    const testStatus = document.getElementById('wasabi-test-status');
    if (testStatus) testStatus.textContent = '';
    const detectedSelect = document.getElementById('detected-snapshot-select');
    if (detectedSelect) detectedSelect.innerHTML = '<option value="">-- Selecciona un ID --</option>';
    const detectBtn = document.getElementById('btn-detect-wasabi-snapshots');
    if (detectBtn) detectBtn.innerHTML = '🔎 Cargar IDs existentes';
    populateNewRepoStorageSelect();
    API.getStorages()
        .then(data => { storages = data.storages || []; populateNewRepoStorageSelect(); toggleNewRepoStorageSource(); })
        .catch(() => {});
    toggleNewRepoStorageSource();
    toggleNewRepoModeGuidance();
}

function populateNewRepoStorageSelect() {
    const select = document.getElementById('new-repo-storage-select');
    if (!select) return;
    select.innerHTML = '<option value="">-- Selecciona un storage guardado o configura uno manualmente --</option>' +
        (storages || []).map(s => {
            const typeLabel = s.type === 'wasabi' ? 'Wasabi' : 'Local';
            const src = s.source === 'legacy-repo' ? ' (legacy)' : '';
            return `<option value="${escapeHtml(s.id)}">${escapeHtml(s.name || s.label || 'Storage')} · ${typeLabel}${escapeHtml(src)}</option>`;
        }).join('');
}

// function applyNewBackupAdvancedVisibility() eliminated
// function toggleNewBackupAdvancedSection() eliminated

function getSelectedImportedStorage() {
    const select = document.getElementById('new-repo-storage-select');
    const storageId = (select?.value || '').trim();
    if (!storageId) return null;
    return (storages || []).find(s => s.id === storageId) || null;
}

function autoFillNewBackupName(form) {
    // Legacy function, no longer used for alias but kept for structure if needed.
    return;
}

function toggleNewRepoStorageSource() {
    const form = document.getElementById('repo-form');
    if (!form) return;
    const selectedStorage = getSelectedImportedStorage();
    const hasStorageRef = !!selectedStorage;
    const hint = document.getElementById('new-repo-storage-hint');
    const modeWrap = document.getElementById('new-repo-mode-wrap');
    const nameHint = document.getElementById('new-repo-name-hint');
    if (hint) {
        hint.textContent = hasStorageRef
            ? `Se usará el destino "${selectedStorage.name || selectedStorage.label || 'Storage'}".`
            : 'Selecciona un destino para continuar.';
    }
    toggleNewRepoModeGuidance();
}

// ─── DELETE REPO ────────────────────────────────────────
async function confirmDeleteRepo(id, name) {
    if (!confirm(`¿Eliminar la tarea de backup "${name}"?\n\nEsto solo borrará la configuración del backup en DupliManager. No se tocarán tus datos ni los snapshots ya subidos.`)) return;

    try {
        await API.deleteRepo(id);
        showToast('🗑 Backup eliminado', 'success');

        // Clear in-memory caches related to this repo to prevent it from showing up in Restore tab
        if (typeof restoreRevisionsCache !== 'undefined') delete restoreRevisionsCache[`repo:${id}`];
        if (typeof restoreFilesCache !== 'undefined') {
            Object.keys(restoreFilesCache).forEach(key => {
                if (key.startsWith(`repo:${id}:rev:`)) delete restoreFilesCache[key];
            });
        }

        if (currentView === 'repositories') {
            loadRepositoriesView();
        } else {
            loadDashboard();
        }
    } catch (err) {
        showToast('❌ Error: ' + err.message, 'error');
    }
}

