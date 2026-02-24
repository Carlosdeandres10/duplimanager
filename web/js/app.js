/**
 * DupliManager — Main SPA Application
 * Handles routing, view management, and UI orchestration
 */

// ─── STATE ──────────────────────────────────────────────
let currentView = 'dashboard';
let repos = [];
let storages = [];
let selectedRepo = null;
let currentTheme = 'dark';
let restoreFileEntries = [];
let restoreFilteredEntries = [];
let restoreSelectedPatterns = new Set();
let restoreBrowserPath = '';
let restoreStorageSnapshotsCache = {};
let restoreRevisionsCache = {};
let restoreFilesCache = {};
let newRepoContentState = { rootPath: '', selection: [] };
let editRepoContentState = { rootPath: '', selection: [] };
let backupIdPickerItems = [];
let backupIdPickerSelected = '';
let currentBackupRunRepoId = null;
let currentBackupEventSource = null;
let contentSelectorSession = {
    target: null, // 'new' | 'edit'
    rootPath: '',
    currentPath: '',
    items: [],
    filteredItems: [],
    selected: new Set(),
};

// ─── INIT ───────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initNavigation();
    navigateTo('dashboard');
    checkServerHealth();
});

function initTheme() {
    const stored = localStorage.getItem('duplimanager_theme');
    applyTheme(stored || 'dark');
}

function applyTheme(theme) {
    currentTheme = (theme === 'light') ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', currentTheme);
    document.body.setAttribute('data-theme', currentTheme);
    localStorage.setItem('duplimanager_theme', currentTheme);
}

function previewThemeFromSettings() {
    const select = document.getElementById('setting-theme');
    if (!select) return;
    applyTheme(select.value);
}

// ─── NAVIGATION ─────────────────────────────────────────
function initNavigation() {
    document.querySelectorAll('.nav-item[data-view]').forEach(item => {
        item.addEventListener('click', () => {
            navigateTo(item.dataset.view);
        });
    });
}

function navigateTo(view) {
    currentView = view;

    // Update nav active state
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    const activeNav = document.querySelector(`.nav-item[data-view="${view}"]`);
    if (activeNav) activeNav.classList.add('active');

    // Show/hide views
    document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
    const viewEl = document.getElementById(`view-${view}`);
    if (viewEl) viewEl.classList.add('active');

    // Load view data
    switch (view) {
        case 'dashboard':  loadDashboard(); break;
        case 'storages':   loadStoragesView(); break;
        case 'repositories': loadRepositoriesView(); break;
        case 'tasks':      loadTasksView(); break;
        case 'backup':     loadBackupView(); break;
        case 'restore':    loadRestoreView(); break;
        case 'settings':   loadSettingsView(); break;
        case 'logs':       loadLogsView(); break;
    }
}

// ─── DASHBOARD ──────────────────────────────────────────
async function loadDashboard() {
    try {
        const [reposData, storagesData] = await Promise.all([
            API.getRepos(),
            API.getStorages().catch(() => ({ storages: [] })),
        ]);
        repos = reposData.repos || [];
        storages = storagesData.storages || [];
        renderDashboard();
    } catch (err) {
        showToast('Error cargando repositorios: ' + err.message, 'error');
    }
}

function renderDashboard() {
    // Stats
    const totalRepos = repos.length;
    const successCount = repos.filter(r => r.lastBackupStatus === 'success').length;
    const errorCount = repos.filter(r => r.lastBackupStatus === 'error').length;
    const pendingCount = repos.filter(r => !r.lastBackup).length;

    document.getElementById('stat-repos').textContent = totalRepos;
    document.getElementById('stat-success').textContent = successCount;
    document.getElementById('stat-errors').textContent = errorCount;
    document.getElementById('stat-pending').textContent = pendingCount;

    // Repo cards
    const grid = document.getElementById('repos-grid');

    if (repos.length === 0) {
        grid.innerHTML = `
            <div class="empty-state" style="grid-column: 1 / -1;">
                <div class="empty-icon">📦</div>
                <h3>Sin backups configurados</h3>
                <p>Crea tu primer backup para empezar a proteger tus datos.</p>
                <button class="btn btn-primary" onclick="openNewRepoModal()">
                    <span>➕</span> Nuevo Backup
                </button>
            </div>
        `;
        return;
    }

    grid.innerHTML = repos.map(repo => `
        <div class="repo-card" data-id="${repo.id}">
            <div class="repo-header">
                <div>
                <div class="repo-name">${escapeHtml(repo.snapshotId)}</div>
                    <div class="repo-path">${escapeHtml(repo.path)}</div>
                </div>
                ${renderStatusBadge(repo.lastBackupStatus)}
            </div>
            <div class="repo-meta">
                <div class="meta-item">
                    <span class="meta-label">Último Backup</span>
                    <span class="meta-value">${repo.lastBackup ? formatDate(repo.lastBackup) : 'Nunca'}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">Repositorio</span>
                    <span class="meta-value">${escapeHtml(formatRepoStorageSummary(repo))}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">Cifrado</span>
                    <span class="meta-value">${repo.encrypted ? '🔒 Sí' : '🔓 No'}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">Próximo backup</span>
                    <span class="meta-value">${escapeHtml(formatNextScheduledRun(repo))}</span>
                </div>
            </div>
            ${renderLastBackupSummaryCard(repo)}
            <div class="repo-actions">
                <button class="btn btn-success btn-sm" onclick="runBackup('${repo.id}')">
                    ▶ Backup
                </button>
                <button class="btn btn-ghost btn-sm" onclick="confirmDeleteRepo('${repo.id}', '${escapeHtml(repo.name)}')">
                    🗑
                </button>
            </div>
        </div>
    `).join('');
}

function formatScheduleLabel(schedule) {
    if (!schedule || !schedule.enabled) return 'Desactivada';
    const type = schedule.type === 'weekly' ? 'Semanal' : 'Diaria';
    const time = schedule.time || '23:00';
    const dayMap = { mon: 'Lun', tue: 'Mar', wed: 'Mié', thu: 'Jue', fri: 'Vie', sat: 'Sáb', sun: 'Dom' };
    const dayText = schedule.type === 'weekly'
        ? ` (${(schedule.days || []).map(d => dayMap[d] || d).join(', ') || 'Lun'})`
        : '';
    return `${type} ${time}${dayText}`;
}

async function loadTasksView() {
    try {
        const data = await API.getRepos();
        repos = data.repos || [];
        renderTasksTable();
    } catch (err) {
        const wrap = document.getElementById('tasks-table-wrap');
        if (wrap) {
            wrap.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><h3>Error</h3><p>${escapeHtml(err.message)}</p></div>`;
        }
    }
}

function renderTasksTable() {
    const wrap = document.getElementById('tasks-table-wrap');
    if (!wrap) return;

    const rows = repos.filter(r => r.schedule && (r.schedule.enabled || r.schedule.lastRunAt || r.schedule.nextRunAt));
    if (!rows.length) {
        wrap.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">⏰</div>
                <h3>Sin tareas programadas</h3>
                <p>Activa una programación en un repositorio para verla aquí.</p>
                <button class="btn btn-primary" onclick="navigateTo('repositories')">🗂️ Ir a Repositorios</button>
            </div>
        `;
        return;
    }

    wrap.innerHTML = `
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Repositorio</th>
                        <th>Estado</th>
                        <th>Programación</th>
                        <th>Hilos</th>
                        <th>Próxima ejecución</th>
                        <th>Última ejecución</th>
                        <th>Resultado</th>
                        <th>Acciones</th>
                    </tr>
                </thead>
                <tbody>
                    ${rows.map(repo => {
                        const s = repo.schedule || {};
                        const enabled = !!s.enabled;
                        const lastResult = s.lastRunStatus || '—';
                        return `
                            <tr>
                                <td>
                                    <div><strong>${escapeHtml(repo.snapshotId || '—')}</strong></div>
                                    <div style="font-size:12px; color: var(--text-muted);">${escapeHtml(repo.path || '')}</div>
                                </td>
                                <td>${enabled ? '<span class="badge badge-success">✅ Activa</span>' : '<span class="badge badge-warning">⏸ Pausada</span>'}</td>
                                <td>${escapeHtml(formatScheduleLabel(s))}</td>
                                <td>${s.threads || 'Auto'}</td>
                                <td>${s.nextRunAt ? escapeHtml(formatDate(s.nextRunAt)) : '—'}</td>
                                <td>${s.lastRunAt ? escapeHtml(formatDate(s.lastRunAt)) : '—'}</td>
                                <td>${escapeHtml(lastResult)}</td>
                                <td>
                                    <div style="display:flex; gap:6px; flex-wrap:wrap;">
                                        <button class="btn btn-success btn-sm" onclick="runBackup('${repo.id}')">▶ Ahora</button>
                                        <button class="btn btn-ghost btn-sm" onclick="toggleTaskEnabled('${repo.id}', ${enabled ? 'false' : 'true'})">${enabled ? '⏸' : '▶️'} ${enabled ? 'Pausar' : 'Activar'}</button>
                                        <button class="btn btn-ghost btn-sm" onclick="openTaskScheduleEditor('${repo.id}')">✏️ Editar</button>
                                    </div>
                                    ${s.lastError ? `<div style="margin-top:6px; font-size:12px; color: var(--danger); max-width:360px;" title="${escapeHtml(s.lastError)}">${escapeHtml(s.lastError)}</div>` : ''}
                                </td>
                            </tr>
                        `;
                    }).join('')}
                </tbody>
            </table>
        </div>
    `;
}

async function toggleTaskEnabled(repoId, enabled) {
    const repo = repos.find(r => r.id === repoId);
    if (!repo) return showToast('Repositorio no encontrado', 'error');
    const current = repo.schedule || {};
    const patch = {
        schedule: {
            enabled: !!enabled,
            type: current.type || 'daily',
            time: current.time || '23:00',
            days: Array.isArray(current.days) ? current.days : [],
            threads: current.threads ?? undefined,
        }
    };
    try {
        await API.updateRepo(repoId, patch);
        showToast(enabled ? '✅ Tarea activada' : '⏸ Tarea pausada', 'success');
        if (currentView === 'tasks') loadTasksView();
        await loadDashboard();
    } catch (err) {
        showToast('❌ Error actualizando tarea: ' + err.message, 'error');
    }
}

function openTaskScheduleEditor(repoId) {
    openEditRepoModal(repoId);
    setTimeout(() => {
        const el = document.getElementById('edit-schedule-enabled');
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 80);
}

// ─── STORAGES ───────────────────────────────────────────
async function loadStoragesView() {
    try {
        const data = await API.getStorages();
        storages = data.storages || [];
        renderStoragesTable();
    } catch (err) {
        const wrap = document.getElementById('storages-table-wrap');
        if (wrap) {
            wrap.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><h3>Error</h3><p>${escapeHtml(err.message)}</p></div>`;
        }
    }
}

function renderStoragesTable() {
    const wrap = document.getElementById('storages-table-wrap');
    if (!wrap) return;
    if (!storages.length) {
        wrap.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">🗄️</div>
                <h3>Sin repositorios</h3>
                <p>Configura un repositorio Wasabi o local como destino para tus copias.</p>
            </div>
        `;
        return;
    }

    wrap.innerHTML = `
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Nombre</th>
                        <th>Tipo</th>
                        <th>URL / Ruta</th>
                        <th>Conexión</th>
                        <th>Acciones</th>
                    </tr>
                </thead>
                <tbody>
                    ${storages.map(s => {
                        return `
                        <tr>
                            <td>
                                <strong>${escapeHtml(s.name || s.label || '—')}</strong>
                            </td>
                            <td>${escapeHtml(s.type || '—')}</td>
                            <td title="${escapeHtml(s.url || s.localPath || '')}">${escapeHtml(s.url || s.localPath || '—')}</td>
                            <td>${s.type === 'wasabi' ? `${s.hasWasabiCredentials ? 'Wasabi ✓' : 'Wasabi ✗'} · ${s.hasDuplicacyPassword ? 'Contraseña Duplicacy ✓' : 'Contraseña Duplicacy —'}` : '—'}</td>
                            <td>
                                <div style="display:flex; gap:6px; flex-wrap:wrap;">
                                    ${s.type === 'wasabi' ? `<button class="btn btn-ghost btn-sm" onclick="detectSnapshotsFromStoredStorage('${s.id}')">🔎 IDs</button>` : ''}
                                    <button class="btn btn-ghost btn-sm" onclick="openEditStorageModal('${s.id}')">✏️ Editar</button>
                                    <button class="btn btn-ghost btn-sm" onclick="confirmDeleteStorage('${s.id}', '${escapeHtml(s.name || s.label || 'Storage')}')">🗑</button>
                                </div>
                            </td>
                        </tr>
                        `;
                    }).join('')}
                </tbody>
            </table>
        </div>
    `;
}

function setStorageModalMode(isEdit) {
    const form = document.getElementById('import-storage-form');
    if (!form) return;
    const title = document.getElementById('import-storage-modal-title');
    const submitBtn = document.getElementById('btn-submit-storage');
    const aliasHint = document.getElementById('import-storage-alias-hint');
    const typeHint = document.getElementById('import-storage-type-hint');
    const accessIdHint = document.getElementById('import-storage-accessid-hint');
    const accessKeyHint = document.getElementById('import-storage-accesskey-hint');
    const dupPwdHint = document.getElementById('import-storage-duppwd-hint');
    const isManagedEdit = !!isEdit;

    if (title) title.textContent = isManagedEdit ? '✏️ Editar Repositorio' : '🗄️ Nuevo Repositorio';
    if (submitBtn) submitBtn.innerHTML = isManagedEdit ? '💾 Guardar cambios' : '💾 Guardar Repositorio';
    if (aliasHint) aliasHint.textContent = isManagedEdit ? 'Alias local del repositorio en DupliManager.' : 'Nombre local del repositorio en DupliManager.';
    if (typeHint) typeHint.style.display = isManagedEdit ? 'block' : 'none';
    if (accessIdHint) accessIdHint.style.display = isManagedEdit ? 'block' : 'none';
    if (accessKeyHint) accessKeyHint.style.display = isManagedEdit ? 'block' : 'none';
    if (dupPwdHint) dupPwdHint.style.display = isManagedEdit ? 'block' : 'none';

    form.storageType.disabled = isManagedEdit;
}

function openImportStorageModal() {
    const modal = document.getElementById('modal-import-storage');
    const form = document.getElementById('import-storage-form');
    if (form) {
        form.reset();
        if (form.storageId) form.storageId.value = '';
        form.storageType.disabled = false;
    }
    setStorageModalMode(false);
    toggleImportStorageTypeFields();
    if (modal) modal.classList.add('show');
}

function openEditStorageModal(storageId) {
    const storage = (storages || []).find(s => s.id === storageId);
    if (!storage) return showToast('Repositorio no encontrado', 'error');
    if (storage.source !== 'managed') return showToast('Los storages legacy no se editan desde aquí', 'warning');

    const modal = document.getElementById('modal-import-storage');
    const form = document.getElementById('import-storage-form');
    if (!form || !modal) return;
    form.reset();
    form.storageId.value = storage.id;
    form.storageName.value = storage.name || storage.label || '';
    form.storageType.value = storage.type || 'wasabi';
    if ((storage.type || '').toLowerCase() === 'local') {
        form.localPath.value = storage.localPath || storage.url || '';
    } else {
        form.endpoint.value = storage.endpoint || '';
        form.region.value = storage.region || '';
        form.bucket.value = storage.bucket || '';
        form.directory.value = storage.directory || '';
        form.accessId.value = '';
        form.accessKey.value = '';
        form.duplicacyPassword.value = '';
    }
    setStorageModalMode(true);
    toggleImportStorageTypeFields();
    modal.classList.add('show');
}

function closeImportStorageModal() {
    const modal = document.getElementById('modal-import-storage');
    if (modal) modal.classList.remove('show');
}

function toggleImportStorageTypeFields() {
    const form = document.getElementById('import-storage-form');
    if (!form) return;
    const type = form.storageType.value || 'wasabi';
    const localBox = document.getElementById('import-storage-local-fields');
    const wasabiBox = document.getElementById('import-storage-wasabi-fields');
    if (localBox) localBox.style.display = type === 'local' ? 'block' : 'none';
    if (wasabiBox) wasabiBox.style.display = type === 'wasabi' ? 'block' : 'none';
}

async function pickImportStorageLocalFolder() {
    const form = document.getElementById('import-storage-form');
    if (!form) return;
    await pickFolderIntoInput(form.localPath);
}

async function submitImportStorage(e) {
    e.preventDefault();
    const form = e.target;
    const btn = form.querySelector('button[type="submit"]');
    const type = (form.storageType.value || 'wasabi');
    const storageId = (form.storageId?.value || '').trim();
    const isEdit = !!storageId;
    const payload = {
        name: form.storageName.value,
        type,
        localPath: type === 'local' ? (form.localPath.value || '').trim() : undefined,
        endpoint: type === 'wasabi' ? (form.endpoint.value || '').trim() : undefined,
        region: type === 'wasabi' ? (form.region.value || '').trim() : undefined,
        bucket: type === 'wasabi' ? (form.bucket.value || '').trim() : undefined,
        directory: type === 'wasabi' ? (form.directory.value || '').trim() : undefined,
        accessId: type === 'wasabi' ? (form.accessId.value || '').trim() : undefined,
        accessKey: type === 'wasabi' ? (form.accessKey.value || '') : undefined,
        duplicacyPassword: type === 'wasabi' ? (form.duplicacyPassword.value || '') : undefined,
    };
    try {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span> Guardando...';
        const result = await (isEdit ? API.updateStorage(storageId, payload) : API.createStorage(payload));
        showToast(isEdit ? '✅ Repositorio actualizado' : '✅ Repositorio guardado', 'success');
        if (result?.warning) showToast('⚠️ ' + result.warning, 'warning');
        closeImportStorageModal();
        await loadStoragesView();
        if (currentView === 'dashboard') await loadDashboard();
    } catch (err) {
        showToast(`❌ Error ${isEdit ? 'actualizando' : 'guardando'} storage: ` + err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = isEdit ? '💾 Guardar cambios' : '💾 Guardar Storage';
    }
}

function startNewBackupWithStorage(storageId) {
    openNewRepoModal();
    setTimeout(() => {
        const select = document.getElementById('new-repo-storage-select');
        if (select) {
            select.value = storageId;
            toggleNewRepoStorageSource();
        }
        navigateTo('repositories');
    }, 50);
}

async function detectSnapshotsFromStoredStorage(storageId) {
    try {
        const result = await API.getStorageSnapshots(storageId);
        const snaps = result.snapshots || [];
        restoreStorageSnapshotsCache[storageId] = snaps;
        if (!snaps.length) return showToast('No se encontraron Snapshot IDs', 'warning');
        const lines = snaps.map(s => `${s.snapshotId} (${s.revisions || 0} rev, última #${s.latestRevision ?? '—'})`).join('\n');
        showToast(`✅ ${snaps.length} Snapshot IDs detectados`, 'success');
        alert(`Snapshot IDs detectados:\n\n${lines}`);
    } catch (err) {
        showToast('❌ Error detectando Snapshot IDs: ' + err.message, 'error');
    }
}

async function confirmDeleteStorage(storageId, name) {
    if (!confirm(`¿Eliminar el repositorio "${name}"?\n\nSolo se eliminará la conexión en DupliManager. Los datos en el destino no se tocarán.`)) return;

    try {
        await API.deleteStorage(storageId);
        showToast('🗑 Repositorio eliminado', 'success');
        await loadStoragesView();
    } catch (err) {
        showToast('❌ Error eliminando storage: ' + err.message, 'error');
    }
}

function formatNextScheduledRun(repo) {
    const s = repo?.schedule;
    if (!s || !s.enabled) return 'Desactivado';
    if (s.nextRunAt) return formatDate(s.nextRunAt);
    return 'Pendiente calcular';
}

function renderLastBackupSummaryCard(repo) {
    const s = repo?.lastBackupSummary;
    if (!s || repo?.lastBackupStatus !== 'success') return '';

    if (s.message) {
        return `
            <div class="repo-backup-summary">
                <div class="repo-backup-summary-title">Resumen último backup</div>
                <div class="repo-backup-summary-line">${escapeHtml(s.message)}</div>
            </div>
        `;
    }

    const parts = [];
    if (s.createdRevision != null) parts.push(`Rev #${s.createdRevision}`);
    if (s.fileCount != null) parts.push(`${s.fileCount} ficheros`);
    const headline = parts.join(' · ');
    const counts = `Nuevos ${s.new || 0} · Cambiados ${s.changed || 0} · Eliminados ${s.deleted || 0}`;
    const samples = [];
    const sampleObj = s.samples || {};
    if (Array.isArray(sampleObj.new) && sampleObj.new.length) samples.push(`+ ${sampleObj.new.slice(0, 3).join(', ')}`);
    if (Array.isArray(sampleObj.changed) && sampleObj.changed.length) samples.push(`~ ${sampleObj.changed.slice(0, 3).join(', ')}`);
    if (Array.isArray(sampleObj.deleted) && sampleObj.deleted.length) samples.push(`- ${sampleObj.deleted.slice(0, 3).join(', ')}`);

    return `
        <div class="repo-backup-summary">
            <div class="repo-backup-summary-title">Resumen último backup</div>
            ${headline ? `<div class="repo-backup-summary-line">${escapeHtml(headline)}</div>` : ''}
            <div class="repo-backup-summary-line">${escapeHtml(counts)}</div>
            ${samples.map(line => `<div class="repo-backup-summary-sample" title="${escapeHtml(line)}">${escapeHtml(line)}</div>`).join('')}
        </div>
    `;
}

function renderStatusBadge(status) {
    if (!status) return '<span class="badge badge-info">⏳ Pendiente</span>';
    if (status === 'success') return '<span class="badge badge-success">✅ OK</span>';
    if (status === 'error') return '<span class="badge badge-error">❌ Error</span>';
    if (status === 'cancelled') return '<span class="badge badge-warning">⏹ Cancelado</span>';
    return '<span class="badge badge-warning">⚠️ Desconocido</span>';
}

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

// ─── REPOSITORIES MANAGEMENT ───────────────────────────
async function loadRepositoriesView() {
    try {
        const [reposData, storagesData] = await Promise.all([
            API.getRepos(),
            API.getStorages().catch(() => ({ storages: [] })),
        ]);
        repos = reposData.repos || [];
        storages = storagesData.storages || [];
        renderRepositoriesTable();
    } catch (err) {
        const wrap = document.getElementById('repositories-table-wrap');
        if (wrap) {
            wrap.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><h3>Error</h3><p>${escapeHtml(err.message)}</p></div>`;
        }
    }
}

function renderRepositoriesTable() {
    const wrap = document.getElementById('repositories-table-wrap');
    if (!wrap) return;

    if (!repos.length) {
        wrap.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📦</div>
                <h3>Sin backups configurados</h3>
                <p>Añade un nuevo backup para empezar.</p>
            </div>
        `;
        return;
    }

    wrap.innerHTML = `
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Backup ID</th>
                        <th>Origen</th>
                        <th>Destino</th>
                        <th>Tipo</th>
                        <th>Estado</th>
                        <th>Acciones</th>
                    </tr>
                </thead>
                <tbody>
                    ${repos.map(repo => {
                        const primary = getPrimaryStorage(repo);
                        return `
                            <tr>
                                <td><strong>${escapeHtml(repo.snapshotId)}</strong></td>
                                <td title="${escapeHtml(repo.path)}"><code style="font-size:11px;">${escapeHtml(repo.path)}</code></td>
                                <td title="${escapeHtml((primary && primary.url) || repo.storageUrl || '')}">${escapeHtml((primary && primary.url) || repo.storageUrl || '—')}</td>
                                <td>${escapeHtml(primary ? (primary.label || primary.type || '—') : '—')}</td>
                                <td>${renderStatusBadge(repo.lastBackupStatus)}</td>
                                <td>
                                    <div style="display:flex; gap:6px; flex-wrap:wrap;">
                                        <button class="btn btn-ghost btn-sm" onclick="openEditRepoModal('${repo.id}')">✏️</button>
                                        <button class="btn btn-success btn-sm" onclick="runBackup('${repo.id}')">▶ Backup</button>
                                        <button class="btn btn-ghost btn-sm" onclick="confirmDeleteRepo('${repo.id}', '${escapeHtml(repo.snapshotId)}')">🗑</button>
                                    </div>
                                </td>
                            </tr>
                        `;
                    }).join('')}
                </tbody>
            </table>
        </div>
`;
}

async function checkNewRepoConfig() {
    const form = document.getElementById('repo-form');
    if (!form) return;

    const btn = document.getElementById('btn-validate-new-repo');
    const status = document.getElementById('new-repo-validation-status');

    const snapshotId = (form.snapshotId.value || '').trim();
    if (!snapshotId) {
        showToast('El Snapshot ID es obligatorio para validar', 'warning');
        form.snapshotId.focus();
        return;
    }

    const data = {
        name: snapshotId,
        path: form.repoPath.value,
        snapshotId,
        importExisting: (form.repoMode?.value || 'create') === 'import',
        storageId: (form.storageId?.value || '').trim() || undefined,
        contentSelection: resolveRepoContentSelectionForSubmit('new', form.repoPath.value),
    };

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span> Validando...';
    }
    if (status) {
        status.style.display = 'block';
        status.style.background = 'rgba(0,0,0,0.05)';
        status.textContent = 'Validando configuración con Duplicacy...';
    }

    try {
        const result = await API.validateRepo(data);
        if (result.ok) {
            if (status) {
                status.style.background = 'var(--accent-green-glow)';
                status.style.color = 'var(--accent-green)';
                status.textContent = '✅ ' + (result.message || 'Configuración válida');
            }
            showToast('✅ Configuración válida', 'success');
        } else {
            if (status) {
                status.style.background = 'var(--accent-red-glow)';
                status.style.color = 'var(--accent-red)';
                status.textContent = '❌ Error: ' + (result.detail || 'Fallo desconocido');
            }
            showToast('❌ Error de validación: ' + (result.detail || 'Fallo'), 'error');
        }
    } catch (err) {
        if (status) {
            status.style.background = 'var(--accent-red-glow)';
            status.style.color = 'var(--accent-red)';
            status.textContent = '❌ Error: ' + err.message;
        }
        showToast('❌ Error: ' + err.message, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '🔍 Verificar Configuración';
        }
    }
}

function closeNewRepoModal() {
    document.getElementById('modal-new-repo').classList.remove('show');
    const status = document.getElementById('new-repo-validation-status');
    if (status) {
        status.style.display = 'none';
        status.textContent = '';
    }
}

function openEditRepoModal(repoId) {
    const repo = repos.find(r => r.id === repoId);
    if (!repo) return showToast('Backup no encontrado', 'error');

    const form = document.getElementById('edit-repo-form');
    const primary = getPrimaryStorage(repo);
    const isWasabi = primary && primary.type === 'wasabi';

    form.repoId.value = repo.id;
    form.repoPath.value = repo.path || '';
    form.snapshotId.value = repo.snapshotId || '';
    form.destinationType.value = isWasabi ? 'wasabi' : 'local';
    form.localStoragePath.value = !isWasabi ? ((primary && primary.url) || repo.storageUrl || '') : '';
    form.wasabiEndpoint.value = isWasabi ? (primary.endpoint || '') : '';
    form.wasabiRegion.value = isWasabi ? (primary.region || '') : '';
    form.wasabiBucket.value = isWasabi ? (primary.bucket || '') : '';
    form.wasabiDirectory.value = isWasabi ? (primary.directory || '') : '';
    form.wasabiAccessId.value = '';
    form.wasabiAccessKey.value = '';
    applyScheduleToEditForm(repo.schedule || null);
    editRepoContentState = {
        rootPath: repo.path || '',
        selection: Array.isArray(repo.contentSelection) ? repo.contentSelection.slice() : [],
    };
    updateRepoContentSelectionSummary('edit');

    toggleEditDestinationFields();
    toggleEditScheduleFields();
    document.getElementById('modal-edit-repo').classList.add('show');
}

function closeEditRepoModal() {
    document.getElementById('modal-edit-repo').classList.remove('show');
}

function toggleEditDestinationFields() {
    const form = document.getElementById('edit-repo-form');
    if (!form) return;
    const isWasabi = form.destinationType.value === 'wasabi';
    const local = document.getElementById('edit-local-destination-fields');
    const wasabi = document.getElementById('edit-wasabi-fields');
    if (local) local.style.display = isWasabi ? 'none' : 'block';
    if (wasabi) wasabi.style.display = isWasabi ? 'block' : 'none';
}

function applyScheduleToEditForm(schedule) {
    const form = document.getElementById('edit-repo-form');
    if (!form) return;
    const s = schedule || {};
    form.scheduleEnabled.checked = !!s.enabled;
    form.scheduleType.value = (s.type === 'weekly') ? 'weekly' : 'daily';
    form.scheduleTime.value = s.time || '23:00';
    form.scheduleThreads.value = (s.threads ?? '') === null ? '' : (s.threads ?? '');
    form.querySelectorAll('input[name="scheduleDays"]').forEach(cb => {
        cb.checked = Array.isArray(s.days) && s.days.includes(cb.value);
    });
    updateEditScheduleSummary();
}

function buildSchedulePayloadFromEditForm(form) {
    const enabled = !!form.scheduleEnabled.checked;
    const type = (form.scheduleType.value || 'daily');
    const time = form.scheduleTime.value || '23:00';
    const days = Array.from(form.querySelectorAll('input[name="scheduleDays"]:checked')).map(x => x.value);
    const threadsRaw = (form.scheduleThreads.value || '').trim();
    const threads = threadsRaw ? parseInt(threadsRaw, 10) : undefined;
    return {
        enabled,
        type,
        time,
        days,
        threads: Number.isFinite(threads) ? threads : undefined,
    };
}

function updateEditScheduleSummary() {
    const form = document.getElementById('edit-repo-form');
    const el = document.getElementById('edit-schedule-summary');
    if (!form || !el) return;
    if (!form.scheduleEnabled.checked) {
        el.textContent = 'Desactivado.';
        return;
    }
    const type = form.scheduleType.value || 'daily';
    const time = form.scheduleTime.value || '23:00';
    const days = Array.from(form.querySelectorAll('input[name="scheduleDays"]:checked')).map(x => x.value);
    const dayLabels = { mon: 'Lun', tue: 'Mar', wed: 'Mié', thu: 'Jue', fri: 'Vie', sat: 'Sáb', sun: 'Dom' };
    const dayText = type === 'weekly'
        ? ` · ${days.length ? days.map(d => dayLabels[d] || d).join(', ') : 'sin días (se usará Lun)'}`
        : '';
    const threads = (form.scheduleThreads.value || '').trim();
    el.textContent = `${type === 'weekly' ? 'Semanal' : 'Diario'} a las ${time}${dayText}${threads ? ` · ${threads} hilo(s)` : ''}`;
}

function toggleEditScheduleFields() {
    const form = document.getElementById('edit-repo-form');
    if (!form) return;
    const enabled = !!form.scheduleEnabled.checked;
    const weekly = enabled && form.scheduleType.value === 'weekly';
    const weeklyBox = document.getElementById('edit-schedule-weekly-days');
    if (weeklyBox) weeklyBox.style.display = weekly ? 'block' : 'none';
    ['scheduleType', 'scheduleTime', 'scheduleThreads'].forEach(name => {
        const input = form[name];
        if (input) input.disabled = !enabled;
    });
    form.querySelectorAll('input[name="scheduleDays"]').forEach(cb => cb.disabled = !enabled || !weekly);
    updateEditScheduleSummary();
}

async function submitEditRepo(e) {
    e.preventDefault();
    const form = e.target;
    const btn = form.querySelector('button[type="submit"]');
    const destinationType = form.destinationType.value || 'local';
    const isWasabi = destinationType === 'wasabi';

    const payload = {
        name: form.snapshotId.value,
        path: form.repoPath.value,
        snapshotId: form.snapshotId.value,
        destinationType,
        localStoragePath: isWasabi ? undefined : form.localStoragePath.value,
        wasabiEndpoint: isWasabi ? form.wasabiEndpoint.value : undefined,
        wasabiRegion: isWasabi ? form.wasabiRegion.value : undefined,
        wasabiBucket: isWasabi ? form.wasabiBucket.value : undefined,
        wasabiDirectory: isWasabi ? form.wasabiDirectory.value : undefined,
        wasabiAccessId: isWasabi && form.wasabiAccessId.value ? form.wasabiAccessId.value : undefined,
        wasabiAccessKey: isWasabi && form.wasabiAccessKey.value ? form.wasabiAccessKey.value : undefined,
        contentSelection: resolveRepoContentSelectionForSubmit('edit', form.repoPath.value),
        schedule: buildSchedulePayloadFromEditForm(form),
    };

    try {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span> Guardando...';
        const result = await API.updateRepo(form.repoId.value, payload);
        showToast('✅ Backup actualizado', 'success');
        if (result.warning) showToast('⚠️ ' + result.warning, 'warning');
        closeEditRepoModal();
        if (currentView === 'repositories') {
            await loadRepositoriesView();
        }
        if (currentView === 'dashboard') {
            await loadDashboard();
        }
        if (currentView === 'tasks') loadTasksView();
    } catch (err) {
        showToast('❌ Error: ' + err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '💾 Guardar cambios';
    }
}

async function submitNewRepo(e) {
    e.preventDefault();
    const form = e.target;
    const btn = form.querySelector('button[type="submit"]');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Inicializando...';

    try {
        const repoMode = (form.repoMode?.value || 'create');
        const importExisting = repoMode === 'import';
        const snapshotId = (form.snapshotId.value || '').trim();
        if (!snapshotId) {
            const msg = importExisting
                ? 'Detecta o escribe un Snapshot ID antes de continuar'
                : 'El Snapshot ID es obligatorio';
            showToast(msg, 'warning');
            form.snapshotId.focus();
            return;
        }
        const data = {
            name: snapshotId,
            path: form.repoPath.value,
            snapshotId,
            importExisting,
            storageId: (form.storageId?.value || '').trim() || undefined,
            contentSelection: resolveRepoContentSelectionForSubmit('new', form.repoPath.value),
        };

        await API.createRepo(data);
        showToast(importExisting ? '✅ Backup vinculado exitosamente' : '✅ Backup creado exitosamente', 'success');
        closeNewRepoModal();
        loadDashboard();

    } catch (err) {
        showToast('❌ Error: ' + err.message, 'error');
    } finally {
        btn.disabled = false;
        const isImport = (form.repoMode?.value || 'create') === 'import';
        btn.innerHTML = isImport ? '🚀 Vincular Backup' : '🚀 Crear Backup';
    }
}



function toggleNewRepoModeGuidance() {
    const form = document.getElementById('repo-form');
    if (!form) return;
    const mode = form.repoMode?.value || 'create';
    const isImport = mode === 'import';
    const selectedStorage = getSelectedImportedStorage();
    const isWasabi = selectedStorage ? (selectedStorage.type === 'wasabi') : false;
    const hint = document.getElementById('new-repo-mode-hint');
    const submitBtn = document.getElementById('btn-submit-new-repo');
    const detectWrap = document.getElementById('detect-snapshot-wrap');
    const snapshotInput = form.snapshotId;

    if (hint) {
        if (isImport) {
            hint.textContent = 'Se usará un ID existente en el storage para continuar el historial.';
        } else {
            hint.textContent = 'Se creará un identificador nuevo para este backup.';
        }
    }
    if (submitBtn) {
        submitBtn.innerHTML = isImport ? '🚀 Vincular Backup' : '🚀 Crear Backup';
    }
    if (detectWrap) {
        detectWrap.style.display = (isImport && isWasabi) ? 'block' : 'none';
    }
    if (snapshotInput) {
        snapshotInput.placeholder = isImport ? 'Escribe o busca el ID' : 'Ej: mi-pc-docs';
    }
}



async function pickRepoSourceFolder() {
    const input = document.querySelector('#repo-form input[name="repoPath"]');
    const before = (input?.value || '').trim();
    await pickFolderIntoInput(input);
    const after = (input?.value || '').trim();
    if (after && after !== before) {
        newRepoContentState = { rootPath: '', selection: [] };
        updateRepoContentSelectionSummary('new');
    }
}

async function pickEditRepoSourceFolder() {
    const input = document.querySelector('#edit-repo-form input[name="repoPath"]');
    const before = (input?.value || '').trim();
    await pickFolderIntoInput(input);
    const after = (input?.value || '').trim();
    if (after && after !== before) {
        editRepoContentState = { rootPath: '', selection: [] };
        updateRepoContentSelectionSummary('edit');
    }
}

async function pickFolderIntoInput(input) {
    if (!input) return;
    try {
        const result = await API.pickFolder(input.value || undefined);
        if (result.cancelled) return;
        if (result.path) input.value = result.path;
    } catch (err) {
        showToast('No se pudo abrir el selector de carpetas: ' + err.message, 'error');
    }
}

function getRepoContentState(target) {
    return target === 'edit' ? editRepoContentState : newRepoContentState;
}

function setRepoContentState(target, state) {
    if (target === 'edit') {
        editRepoContentState = state;
    } else {
        newRepoContentState = state;
    }
    updateRepoContentSelectionSummary(target);
}

function getRepoFormByTarget(target) {
    return target === 'edit'
        ? document.getElementById('edit-repo-form')
        : document.getElementById('repo-form');
}

function getRepoSourcePathForTarget(target) {
    const form = getRepoFormByTarget(target);
    if (!form) return '';
    return (form.querySelector('input[name="repoPath"]')?.value || '').trim();
}

function updateRepoContentSelectionSummary(target) {
    const el = document.getElementById(target === 'edit' ? 'edit-content-selection-summary' : 'new-content-selection-summary');
    if (!el) return;
    const state = getRepoContentState(target);
    const selection = Array.isArray(state.selection) ? state.selection : [];
    if (!selection.length) {
        el.textContent = 'Se respaldará todo el contenido de la carpeta origen.';
        return;
    }
    const dirs = selection.filter(p => String(p || '').endsWith('/')).length;
    const files = selection.length - dirs;
    el.textContent = `Selección parcial guardada: ${selection.length} elemento(s) (${dirs} carpetas, ${files} ficheros). Puedes modificarla cuando quieras.`;
}

function resolveRepoContentSelectionForSubmit(target, repoPathValue) {
    const state = getRepoContentState(target);
    const repoPath = String(repoPathValue || '').trim();
    const selection = Array.isArray(state.selection) ? state.selection.slice() : [];
    if (!selection.length) return [];
    if (!repoPath) return [];
    if ((state.rootPath || '').trim() === repoPath) return selection;

    // La carpeta raíz cambió después de seleccionar contenido.
    setRepoContentState(target, { rootPath: repoPath, selection: [] });
    showToast('La carpeta origen cambió: se limpió la selección parcial de contenido', 'warning');
    return [];
}

function resetRepoContentSelection(target) {
    const rootPath = getRepoSourcePathForTarget(target);
    setRepoContentState(target, {
        rootPath: rootPath || '',
        selection: [],
    });
    showToast('Se respaldará todo el origen para este backup', 'info');
}

function normalizeSelectionPath(path, isDir = false) {
    let value = String(path || '').replace(/\\/g, '/').trim().replace(/^\/+/, '');
    value = value.replace(/\/{2,}/g, '/');
    if (!value) return '';
    value = value.replace(/\/+$/, '');
    if (!value) return '';
    return isDir ? `${value}/` : value;
}

function normalizeSelectionArray(paths) {
    const out = [];
    const seen = new Set();
    for (const raw of (paths || [])) {
        const isDir = String(raw || '').endsWith('/');
        const v = normalizeSelectionPath(raw, isDir);
        if (!v || seen.has(v)) continue;
        seen.add(v);
        out.push(v);
    }
    return out;
}

async function openRepoContentSelector(target) {
    const rootPath = getRepoSourcePathForTarget(target);
    if (!rootPath) {
        showToast('Selecciona primero la carpeta origen del backup', 'warning');
        return;
    }

    const state = getRepoContentState(target);
    const rootChanged = !!state.rootPath && state.rootPath !== rootPath;
    contentSelectorSession = {
        target,
        rootPath,
        currentPath: '',
        items: [],
        filteredItems: [],
        selected: new Set(rootChanged ? [] : normalizeSelectionArray(state.selection)),
    };
    if (rootChanged) {
        showToast('La carpeta origen cambió: se limpió la selección anterior', 'warning');
    }

    const rootInput = document.getElementById('content-selector-root');
    if (rootInput) rootInput.value = rootPath;
    const filterInput = document.getElementById('content-selector-filter');
    if (filterInput) filterInput.value = '';

    document.getElementById('modal-content-selector')?.classList.add('show');
    renderContentSelectorChrome();
    await loadContentSelectorFolder('');
}

function closeContentSelectorModal() {
    document.getElementById('modal-content-selector')?.classList.remove('show');
}

function renderContentSelectorChrome() {
    const session = contentSelectorSession;
    const upBtn = document.getElementById('btn-content-up');
    const rootBtn = document.getElementById('btn-content-root');
    if (upBtn) upBtn.disabled = !session.currentPath;
    if (rootBtn) rootBtn.disabled = !session.currentPath;

    const breadcrumbs = document.getElementById('content-selector-breadcrumbs');
    if (breadcrumbs) {
        const parts = (session.currentPath || '').replace(/\/+$/, '').split('/').filter(Boolean);
        if (!parts.length) {
            breadcrumbs.innerHTML = '<span class="restore-breadcrumb-current">Raíz</span>';
        } else {
            let acc = '';
            const chunks = ['<button type="button" class="restore-breadcrumb-link" data-content-breadcrumb="">Raíz</button>'];
            parts.forEach((part, i) => {
                acc = acc ? `${acc}/${part}` : part;
                const isLast = i === parts.length - 1;
                chunks.push('<span class="restore-breadcrumb-sep">/</span>');
                if (isLast) {
                    chunks.push(`<span class="restore-breadcrumb-current">${escapeHtml(part)}</span>`);
                } else {
                    chunks.push(`<button type="button" class="restore-breadcrumb-link" data-content-breadcrumb="${encodeURIComponent(acc + '/')}">${escapeHtml(part)}</button>`);
                }
            });
            breadcrumbs.innerHTML = chunks.join('');
            breadcrumbs.querySelectorAll('[data-content-breadcrumb]').forEach(btn => {
                btn.addEventListener('click', () => {
                    const rel = decodeURIComponent(btn.getAttribute('data-content-breadcrumb') || '');
                    loadContentSelectorFolder(rel);
                });
            });
        }
    }
    updateContentSelectorStatus();
}

async function loadContentSelectorFolder(relativePath) {
    const session = contentSelectorSession;
    if (!session.rootPath) return;
    const list = document.getElementById('content-selector-list');
    if (list) {
        list.innerHTML = '<div class="restore-check-empty"><span class="spinner"></span> Cargando contenido...</div>';
    }
    try {
        const data = await API.listLocalItems(session.rootPath, relativePath || '');
        session.currentPath = data.currentPath || '';
        session.items = (data.items || []).map(item => ({
            ...item,
            relativePath: normalizeSelectionPath(item.relativePath, !!item.isDir),
            name: item.name || '',
            isDir: !!item.isDir,
        }));
        contentSelectorSession = session;
        renderContentSelectorChrome();
        filterContentSelectorItems();
    } catch (err) {
        if (list) list.innerHTML = `<div class="restore-check-empty">Error: ${escapeHtml(err.message)}</div>`;
        showToast('No se pudo cargar la carpeta: ' + err.message, 'error');
    }
}

function reloadContentSelectorFolder() {
    loadContentSelectorFolder(contentSelectorSession.currentPath || '');
}

function goToContentSelectorRoot() {
    loadContentSelectorFolder('');
}

function goUpContentSelectorFolder() {
    const current = contentSelectorSession.currentPath || '';
    if (!current) return;
    const trimmed = current.replace(/\/+$/, '');
    const idx = trimmed.lastIndexOf('/');
    const parent = idx >= 0 ? `${trimmed.slice(0, idx + 1)}` : '';
    loadContentSelectorFolder(parent);
}

function filterContentSelectorItems() {
    const q = (document.getElementById('content-selector-filter')?.value || '').trim().toLowerCase();
    const items = contentSelectorSession.items || [];
    contentSelectorSession.filteredItems = !q
        ? items.slice()
        : items.filter(item =>
            (item.name || '').toLowerCase().includes(q) ||
            (item.relativePath || '').toLowerCase().includes(q)
        );
    renderContentSelectorList(contentSelectorSession.filteredItems);
}

function renderContentSelectorList(items) {
    const list = document.getElementById('content-selector-list');
    if (!list) return;
    if (!items.length) {
        list.innerHTML = '<div class="restore-check-empty">Carpeta vacía o sin coincidencias.</div>';
        updateContentSelectorStatus();
        return;
    }

    list.innerHTML = items.map(item => {
        const key = encodeURIComponent(item.relativePath || '');
        const checked = contentSelectorSession.selected.has(item.relativePath) ? 'checked' : '';
        const icon = item.isDir ? '📁' : '📄';
        const parent = (contentSelectorSession.currentPath || '').replace(/\/+$/, '') || 'Raíz';
        return `
          <div class="restore-check-item" data-content-item="${key}" title="${escapeAttr(item.relativePath || '')}">
            <input type="checkbox" data-content-key="${key}" ${checked} />
            <span class="restore-check-icon">${icon}</span>
            <div class="restore-check-main">
              <div class="restore-check-row">
                ${item.isDir
                    ? `<button type="button" class="restore-check-label restore-folder-link" data-content-open="${key}">${escapeHtml(item.name)}</button>`
                    : `<span class="restore-check-label">${escapeHtml(item.name)}</span>`}
                ${item.isDir ? `<button type="button" class="restore-entry-open" data-content-open="${key}">Abrir</button>` : ''}
              </div>
              <span class="restore-check-path">${escapeHtml(parent)}</span>
            </div>
          </div>
        `;
    }).join('');

    list.querySelectorAll('[data-content-key]').forEach(cb => {
        cb.addEventListener('change', () => {
            const path = decodeURIComponent(cb.getAttribute('data-content-key') || '');
            if (!path) return;
            if (cb.checked) contentSelectorSession.selected.add(path);
            else contentSelectorSession.selected.delete(path);
            updateContentSelectorStatus();
        });
    });

    list.querySelectorAll('[data-content-open]').forEach(btn => {
        btn.addEventListener('click', () => {
            const rel = decodeURIComponent(btn.getAttribute('data-content-open') || '');
            loadContentSelectorFolder(rel);
        });
    });

    list.querySelectorAll('.restore-check-item').forEach(row => {
        row.addEventListener('dblclick', (ev) => {
            const openEl = row.querySelector('[data-content-open]');
            if (!openEl) return;
            if (ev.target && ev.target.closest('input[type="checkbox"]')) return;
            const rel = decodeURIComponent(openEl.getAttribute('data-content-open') || '');
            loadContentSelectorFolder(rel);
        });
    });

    updateContentSelectorStatus();
}

function selectVisibleContentItems() {
    for (const item of (contentSelectorSession.filteredItems || [])) {
        if (item?.relativePath) contentSelectorSession.selected.add(item.relativePath);
    }
    renderContentSelectorList(contentSelectorSession.filteredItems || []);
}

function clearContentSelectorSelection() {
    contentSelectorSession.selected.clear();
    renderContentSelectorList(contentSelectorSession.filteredItems || []);
}

function updateContentSelectorStatus() {
    const el = document.getElementById('content-selector-status');
    if (!el) return;
    const selected = contentSelectorSession.selected?.size || 0;
    const folder = contentSelectorSession.currentPath || 'raíz';
    if (!selected) {
        el.textContent = `Sin selección (carpeta actual: ${folder}): se respaldará todo el origen.`;
        return;
    }
    const all = Array.from(contentSelectorSession.selected);
    const dirs = all.filter(x => x.endsWith('/')).length;
    const files = all.length - dirs;
    el.textContent = `Marcados ${all.length} elemento(s) (${dirs} carpetas, ${files} ficheros). Carpeta actual: ${folder}.`;
}

function saveContentSelectorSelection() {
    const target = contentSelectorSession.target;
    if (!target) return;
    setRepoContentState(target, {
        rootPath: contentSelectorSession.rootPath || '',
        selection: normalizeSelectionArray(Array.from(contentSelectorSession.selected || [])),
    });
    closeContentSelectorModal();
    showToast('Selección de contenido guardada', 'success');
}

function getWasabiFormPayload() {
    const form = document.getElementById('repo-form');
    if (!form) return { form: null, payload: null };
    
    const payload = {
        endpoint: (form.wasabiEndpoint?.value || '').trim(),
        region: (form.wasabiRegion?.value || '').trim(),
        bucket: (form.wasabiBucket?.value || '').trim(),
        directory: (form.wasabiDirectory?.value || '').trim(),
        accessId: (form.wasabiAccessId?.value || '').trim(),
        accessKey: form.wasabiAccessKey?.value || ''
    };
    return { form, payload };
}

function applyDetectedSnapshotId() {
    const form = document.getElementById('repo-form');
    const select = document.getElementById('detected-snapshot-select');
    if (!form || !select || !select.value) return;
    form.snapshotId.value = select.value;
    if (form.repoMode) form.repoMode.value = 'import';
    
    toggleNewRepoModeGuidance();
}

function closeBackupIdPickerModal() {
    document.getElementById('modal-backup-id-picker')?.classList.remove('show');
}

function openBackupIdPickerModal(items, hintText) {
    backupIdPickerItems = Array.isArray(items) ? items.slice() : [];
    backupIdPickerSelected = '';
    const filter = document.getElementById('backup-id-picker-filter');
    if (filter) filter.value = '';
    const hint = document.getElementById('backup-id-picker-hint');
    if (hint) {
        hint.textContent = hintText || (backupIdPickerItems.length
            ? `Se detectaron ${backupIdPickerItems.length} Snapshot IDs.`
            : 'No hay Snapshot IDs para mostrar.');
    }
    document.getElementById('modal-backup-id-picker')?.classList.add('show');
    renderBackupIdPickerList();
}

function renderBackupIdPickerList() {
    const list = document.getElementById('backup-id-picker-list');
    const filterVal = (document.getElementById('backup-id-picker-filter')?.value || '').trim().toLowerCase();
    const applyBtn = document.getElementById('btn-apply-backup-id-picker');
    if (!list) return;

    const rows = (backupIdPickerItems || []).filter(item => {
        const sid = String(item?.snapshotId || '').toLowerCase();
        return !filterVal || sid.includes(filterVal);
    });

    if (!rows.length) {
        list.innerHTML = '<div class="restore-check-empty">No hay Backup IDs que coincidan.</div>';
        if (applyBtn) applyBtn.disabled = !backupIdPickerSelected;
        return;
    }

    list.innerHTML = rows.map(item => {
        const sid = String(item.snapshotId || '');
        const selected = sid === backupIdPickerSelected;
        const key = encodeURIComponent(sid);
        return `
          <div class="restore-check-item ${selected ? 'selected' : ''}" data-backup-id-row="${key}" title="${escapeAttr(sid)}">
            <input type="radio" name="backup-id-picker-radio" data-backup-id-radio="${key}" ${selected ? 'checked' : ''} />
            <span class="restore-check-icon">📁</span>
            <div class="restore-check-main">
              <div class="restore-check-row">
                <span class="restore-check-label">${escapeHtml(sid)}</span>
              </div>
              <span class="restore-check-path">${escapeHtml((item.revisions || 0) + ' revisiones')} · última #${escapeHtml(String(item.latestRevision ?? '—'))}</span>
            </div>
          </div>
        `;
    }).join('');

    list.querySelectorAll('[data-backup-id-radio]').forEach(radio => {
        radio.addEventListener('change', () => {
            backupIdPickerSelected = decodeURIComponent(radio.getAttribute('data-backup-id-radio') || '');
            renderBackupIdPickerList();
        });
    });
    list.querySelectorAll('[data-backup-id-row]').forEach(row => {
        row.addEventListener('click', () => {
            backupIdPickerSelected = decodeURIComponent(row.getAttribute('data-backup-id-row') || '');
            renderBackupIdPickerList();
        });
        row.addEventListener('dblclick', () => {
            backupIdPickerSelected = decodeURIComponent(row.getAttribute('data-backup-id-row') || '');
            applyBackupIdFromPicker();
        });
    });

    if (applyBtn) applyBtn.disabled = !backupIdPickerSelected;
}

function applyBackupIdFromPicker() {
    if (!backupIdPickerSelected) return;
    const form = document.getElementById('repo-form');
    const select = document.getElementById('detected-snapshot-select');
    if (form?.snapshotId) form.snapshotId.value = backupIdPickerSelected;
    if (select) select.value = backupIdPickerSelected;
    if (form?.repoMode) form.repoMode.value = 'import';
    
    toggleNewRepoModeGuidance();
    closeBackupIdPickerModal();
    showToast(`✅ Snapshot ID seleccionado: ${backupIdPickerSelected}`, 'success');
}

async function openBackupIdPickerFromNewBackup() {
    const form = document.getElementById('repo-form');
    if (!form) return;
    if (form.repoMode) form.repoMode.value = 'import';
    toggleNewRepoModeGuidance();

    const select = document.getElementById('detected-snapshot-select');
    const current = Array.from(select?.options || [])
        .map(o => ({ value: o.value, text: o.textContent || '' }))
        .filter(o => o.value);
    if (current.length) {
        const items = current.map(o => {
            const m = o.text.match(/\((\d+)\s+rev,\s+última\s+#([^)]+)\)/i);
            return {
                snapshotId: o.value,
                revisions: m ? parseInt(m[1], 10) : 0,
                latestRevision: m ? m[2] : null,
            };
        });
        openBackupIdPickerModal(items, `IDs ya cargados (${items.length}).`);
        return;
    }
    await detectWasabiSnapshotIds(true);
}

async function detectWasabiSnapshotIds(openPickerIfMultiple = false) {
    const form = document.getElementById('repo-form');
    if (!form) return;
    const isImport = (form.repoMode?.value || 'create') === 'import';
    const selectedStorage = getSelectedImportedStorage();
    const isWasabi = selectedStorage ? selectedStorage.type === 'wasabi' : ((form.destinationType?.value || 'local') === 'wasabi');
    if (!isImport) {
        return showToast('Usa modo "Usar Snapshot ID existente" para cargar Snapshot IDs', 'warning');
    }
    if (!selectedStorage && !isWasabi) {
        return showToast('Selecciona un storage guardado o usa destino Wasabi para detectar Snapshot IDs', 'warning');
    }

    const btn = document.getElementById('btn-detect-wasabi-snapshots');
    const select = document.getElementById('detected-snapshot-select');
    const hint = document.getElementById('detected-snapshot-hint');
    if (selectedStorage) {
        if (form.repoMode) form.repoMode.value = 'import';
        toggleNewRepoModeGuidance();
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner"></span> Cargando IDs...';
        }
        if (hint) hint.textContent = 'Cargando Backup IDs del storage guardado...';
        try {
            const result = await API.getStorageSnapshots(selectedStorage.id);
            const snapshots = Array.isArray(result.snapshots) ? result.snapshots : [];
            if (select) {
                select.innerHTML = '<option value="">-- Selecciona un Snapshot ID detectado --</option>' +
                    snapshots.map(s => {
                        const label = `${s.snapshotId} (${s.revisions || 0} rev, última #${s.latestRevision ?? '—'})`;
                        return `<option value="${escapeHtml(s.snapshotId)}">${escapeHtml(label)}</option>`;
                    }).join('');
            }
            if (!snapshots.length) {
                if (hint) hint.textContent = 'No se encontraron Backup IDs en ese storage.';
                showToast('No se encontraron Backup IDs', 'warning');
                return;
            }
            if (snapshots.length === 1) {
                form.snapshotId.value = snapshots[0].snapshotId;
                autoFillNewBackupName(form);
                if (hint) hint.textContent = `Detectado 1 Backup ID y aplicado automáticamente: ${snapshots[0].snapshotId}`;
                showToast(`✅ Backup ID detectado: ${snapshots[0].snapshotId}`, 'success');
            } else {
                if (hint) hint.textContent = `Se detectaron ${snapshots.length} Backup IDs. Elige uno de la lista.`;
                showToast(`✅ Detectados ${snapshots.length} Backup IDs`, 'success');
                if (openPickerIfMultiple) {
                    openBackupIdPickerModal(snapshots, `Selecciona un Backup ID del storage guardado (${snapshots.length} encontrados).`);
                }
            }
        } catch (err) {
            if (hint) hint.textContent = `Error cargando Backup IDs: ${err.message}`;
            showToast('❌ Error cargando Backup IDs: ' + err.message, 'error');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '🔎 Cargar Backup IDs del storage';
            }
        }
        return;
    }

    const { payload } = getWasabiFormPayload();
    if (!payload) return;
    if (form.repoMode) form.repoMode.value = 'import';
    toggleNewRepoModeGuidance();

    const detectPayload = {
        ...payload,
        directory: (form.wasabiDirectory?.value || '').trim(),
        password: '', // Password is no longer in this form
    };
    const required = ['endpoint', 'region', 'bucket', 'accessId', 'accessKey'];
    const missing = required.filter(k => !detectPayload[k]);
    if (missing.length) {
        const msg = `Completa antes: ${missing.join(', ')}`;
        if (hint) hint.textContent = msg;
        showToast(msg, 'warning');
        return;
    }

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span> Detectando...';
    }
    if (hint) hint.textContent = 'Detectando Backup IDs (Snapshot IDs) en el storage remoto...';

    try {
        const result = await API.detectWasabiSnapshots(detectPayload);
        const snapshots = Array.isArray(result.snapshots) ? result.snapshots : [];
        if (select) {
            select.innerHTML = '<option value="">-- Selecciona un Snapshot ID detectado --</option>' +
                snapshots.map(s => {
                    const label = `${s.snapshotId} (${s.revisions || 0} rev, última #${s.latestRevision ?? '—'})`;
                    return `<option value="${escapeHtml(s.snapshotId)}">${escapeHtml(label)}</option>`;
                }).join('');
        }
        if (!snapshots.length) {
            if (hint) hint.textContent = 'No se encontraron Snapshot IDs en ese bucket/directorio.';
            showToast('No se encontraron Snapshot IDs', 'warning');
            return;
        }
        if (snapshots.length === 1) {
            form.snapshotId.value = snapshots[0].snapshotId;
            autoFillNewBackupName(form);
            if (hint) hint.textContent = `Detectado 1 Snapshot ID y aplicado automáticamente: ${snapshots[0].snapshotId}`;
            showToast(`✅ Snapshot ID detectado: ${snapshots[0].snapshotId}`, 'success');
        } else {
            if (hint) hint.textContent = `Se detectaron ${snapshots.length} Snapshot IDs. Elige uno de la lista.`;
            showToast(`✅ Detectados ${snapshots.length} Snapshot IDs`, 'success');
            if (openPickerIfMultiple) {
                openBackupIdPickerModal(snapshots, `Selecciona un Backup ID en Wasabi (${snapshots.length} encontrados).`);
            }
        }
    } catch (err) {
        if (hint) hint.textContent = `Error detectando Snapshot IDs: ${err.message}`;
        showToast('❌ Error detectando Snapshot IDs: ' + err.message, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '🔎 Detectar Snapshot IDs en Wasabi';
        }
    }
}

async function testWasabiConnection() {
    const { form, payload } = getWasabiFormPayload();
    if (!form || !payload) return;

    const btn = document.getElementById('btn-test-wasabi');
    const status = document.getElementById('wasabi-test-status');

    const missing = Object.entries(payload).filter(([, v]) => !v).map(([k]) => k);
    if (missing.length) {
        const msg = `Completa antes: ${missing.join(', ')}`;
        if (status) status.textContent = msg;
        showToast(msg, 'warning');
        return;
    }

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span> Probando...';
    }
    if (status) status.textContent = 'Probando conexión con Wasabi...';

    try {
        const result = await API.testWasabiConnection(payload);
        const msg = `Conexión OK (HTTP ${result.status || 200})`;
        if (status) status.textContent = msg;
        showToast('✅ ' + msg, 'success');
    } catch (err) {
        if (status) status.textContent = `Error: ${err.message}`;
        showToast('❌ Error Wasabi: ' + err.message, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '🔌 Probar conexión Wasabi';
        }
    }
}

async function testWasabiWriteConnection() {
    const { form, payload } = getWasabiFormPayload();
    if (!form || !payload) return;

    const btn = document.getElementById('btn-test-wasabi-write');
    const status = document.getElementById('wasabi-test-status');

    const missing = Object.entries(payload).filter(([, v]) => !v).map(([k]) => k);
    if (missing.length) {
        const msg = `Completa antes: ${missing.join(', ')}`;
        if (status) status.textContent = msg;
        showToast(msg, 'warning');
        return;
    }

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span> Probando escritura...';
    }
    if (status) status.textContent = 'Probando escritura y borrado en Wasabi...';

    try {
        const result = await API.testWasabiWrite(payload);
        const msg = `Escritura OK (PUT ${result.putStatus || 200}, DELETE ${result.deleteStatus || 204})`;
        if (status) status.textContent = msg;
        showToast('✅ ' + msg, 'success');
    } catch (err) {
        if (status) status.textContent = `Error: ${err.message}`;
        showToast('❌ Error escritura Wasabi: ' + err.message, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '🧪 Probar escritura Wasabi';
        }
    }
}

// ─── BACKUP ─────────────────────────────────────────────
async function loadBackupView() {
    try {
        const data = await API.getRepos();
        repos = data.repos || [];
        const select = document.getElementById('backup-repo-select');
        const threadsInput = document.getElementById('backup-threads');
        select.innerHTML = '<option value="">-- Seleccionar backup --</option>' +
            repos.map(r => `<option value="${r.id}">${escapeHtml(r.name)} — ${escapeHtml(r.path)}</option>`).join('');
        if (!select.value) select.value = '';
        if (threadsInput) {
            threadsInput.value = '16';
            threadsInput.disabled = true;
        }
        updateBackupRunButtonState();
    } catch (err) {
        showToast('Error cargando backups', 'error');
    }
}

function updateBackupRunButtonState(isRunning = false) {
    const select = document.getElementById('backup-repo-select');
    const btn = document.getElementById('btn-start-backup');
    const cancelBtn = document.getElementById('btn-cancel-backup');
    if (!btn) return;
    const hasRepo = !!(select?.value || '').trim();
    btn.disabled = isRunning || !hasRepo;
    btn.title = hasRepo ? '' : 'Selecciona un backup para iniciar el backup';
    if (cancelBtn) {
        cancelBtn.disabled = !isRunning || !currentBackupRunRepoId;
        cancelBtn.title = (!isRunning || !currentBackupRunRepoId) ? 'No hay backup en ejecución' : '';
    }
}

async function cancelBackupRun() {
    const repoId = currentBackupRunRepoId || document.getElementById('backup-repo-select')?.value;
    if (!repoId) return showToast('No hay backup en ejecución', 'warning');

    const logOutput = document.getElementById('backup-log');
    const statusText = document.getElementById('backup-status');
    try {
        await API.cancelBackup(repoId);
        if (statusText) statusText.textContent = 'Cancelando backup...';
        if (logOutput) {
            logOutput.textContent += '\n⏹ Cancelación solicitada...\n';
            logOutput.scrollTop = logOutput.scrollHeight;
        }
        showToast('⏹ Cancelación solicitada', 'info');
        updateBackupRunButtonState(true);
    } catch (err) {
        showToast('❌ No se pudo cancelar: ' + err.message, 'error');
    }
}

async function runBackup(repoId) {
    if (!repoId) {
        // If called from backup view, get selected repo
        repoId = document.getElementById('backup-repo-select')?.value;
        if (!repoId) return showToast('Selecciona un backup', 'warning');
    }

    const logOutput = document.getElementById('backup-log');
    const progressBar = document.getElementById('backup-progress-fill');
    const statusText = document.getElementById('backup-status');
    const threads = 16;
    const repo = repos.find(r => r.id === repoId) || null;
    const primaryStorage = repo ? getPrimaryStorage(repo) : null;
    let streamDisconnected = false;
    let seenDuplicacyOutput = false;
    let silentHintShown = false;
    const backupStartedAtMs = Date.now();

    // Navigate to backup view if not there
    if (currentView !== 'backup') navigateTo('backup');

    if (logOutput) logOutput.textContent = 'Iniciando backup...\n';
    if (logOutput && repo) {
        logOutput.textContent += `Backup: ${repo.name || repoId}\n`;
        logOutput.textContent += `Origen: ${repo.path || '—'}\n`;
        logOutput.textContent += `Destino: ${(primaryStorage && primaryStorage.url) || repo.storageUrl || '—'}\n`;
        if (Array.isArray(repo.contentSelection) && repo.contentSelection.length) {
            logOutput.textContent += `Selección parcial guardada: ${repo.contentSelection.length} elemento(s)\n`;
        } else {
            logOutput.textContent += 'Selección: todo el contenido del origen\n';
        }
    }
    if (logOutput && threads) logOutput.textContent += `Usando ${threads} hilo(s)\n`;
    if (progressBar) progressBar.style.width = '0%';
    if (statusText) statusText.textContent = 'Ejecutando backup...';
    currentBackupRunRepoId = repoId;
    updateBackupRunButtonState(true);

    let evtSource = null;
    const handleProgressEvent = (data) => {
        if (data.error) {
            streamDisconnected = true;
            if (statusText) statusText.textContent = 'Backup en curso (seguimiento desconectado)';
            if (logOutput) {
                logOutput.textContent += '\n⚠️ Se perdió la conexión de progreso. El backup puede seguir ejecutándose en el servidor.\n';
                logOutput.scrollTop = logOutput.scrollHeight;
            }
            updateBackupRunButtonState(true);
            return;
        }

        if (data.done) {
            if (currentBackupEventSource) {
                currentBackupEventSource.close();
                currentBackupEventSource = null;
            }
            if (logOutput && data.backupSummary && !data.canceled) {
                const s = data.backupSummary;
                logOutput.textContent += '\n--- Resumen del backup ---\n';
                if (s.message) {
                    logOutput.textContent += `${s.message}\n`;
                } else {
                    if (s.createdRevision != null) {
                        logOutput.textContent += `Revisión creada: #${s.createdRevision}`;
                        if (s.previousRevision != null) logOutput.textContent += ` (anterior: #${s.previousRevision})`;
                        logOutput.textContent += '\n';
                    }
                    if (s.fileCount != null) logOutput.textContent += `Ficheros en snapshot: ${s.fileCount}\n`;
                    logOutput.textContent += `Nuevos: ${s.new || 0} | Cambiados: ${s.changed || 0} | Eliminados: ${s.deleted || 0}\n`;
                    const samples = s.samples || {};
                    const appendSample = (label, arr) => {
                        if (Array.isArray(arr) && arr.length) {
                            logOutput.textContent += `${label}: ${arr.slice(0, 8).join(', ')}${arr.length > 8 ? ' ...' : ''}\n`;
                        }
                    };
                    appendSample('Nuevos', samples.new);
                    appendSample('Cambiados', samples.changed);
                    appendSample('Eliminados', samples.deleted);
                }
            }
            if (logOutput && data.finalOutput) {
                const finalText = String(data.finalOutput || '').trim();
                if (finalText) {
                    logOutput.textContent += '\n--- Salida final Duplicacy ---\n' + finalText + '\n';
                }
            }
            if (logOutput) {
                if (data.canceled) {
                    logOutput.textContent += '\n⏹ Backup cancelado por el usuario.\n';
                } else if (data.success === false) {
                    logOutput.textContent += '\n❌ Backup finalizado con error.\n';
                } else if (!streamDisconnected) {
                    logOutput.textContent += '\n✅ Backup completado.\n';
                }
                logOutput.scrollTop = logOutput.scrollHeight;
            }
            if (progressBar) progressBar.style.width = data.canceled ? '0%' : '100%';
            if (statusText) {
                if (data.canceled) statusText.textContent = 'Backup cancelado';
                else if (data.success === false) statusText.textContent = 'Error en backup';
                else if (!streamDisconnected) statusText.textContent = 'Backup completado';
            }
            currentBackupRunRepoId = null;
            updateBackupRunButtonState(false);
            loadDashboard();
            return;
        }
        if (data.running && !data.output) {
            const elapsedSec = Math.max(1, Math.round((Date.now() - backupStartedAtMs) / 1000));
            if (statusText) {
                statusText.textContent = seenDuplicacyOutput
                    ? `Procesando backup... (${elapsedSec}s)`
                    : `Escaneando archivos (sin salida aún)... (${elapsedSec}s)`;
            }
            if (progressBar && !seenDuplicacyOutput) {
                progressBar.style.width = '12%';
            }
            if (!seenDuplicacyOutput && !silentHintShown && elapsedSec >= 5 && logOutput) {
                logOutput.textContent += 'ℹ️ Duplicacy puede tardar en mostrar salida mientras escanea archivos.\n';
                logOutput.scrollTop = logOutput.scrollHeight;
                silentHintShown = true;
            }
        }
        if (data.output && logOutput) {
            seenDuplicacyOutput = true;
            if (statusText) statusText.textContent = 'Recibiendo salida de Duplicacy...';
            if (progressBar && Number((progressBar.style.width || '0').replace('%', '')) < 35) {
                progressBar.style.width = '35%';
            }
            logOutput.textContent += data.output + '\n';
            logOutput.scrollTop = logOutput.scrollHeight;
        }
    };

    try {
        await API.startBackup(repoId, undefined, threads);
        // Conectar SSE después de iniciar el backup evita una carrera donde el
        // servidor cerraba la suscripción antes de que el job existiera.
        evtSource = API.subscribeProgress(repoId, handleProgressEvent);
        currentBackupEventSource = evtSource;
        showToast('⏳ Backup iniciado', 'info');
    } catch (err) {
        if (evtSource) evtSource.close();
        if (currentBackupEventSource === evtSource) currentBackupEventSource = null;
        showToast('❌ Backup falló: ' + err.message, 'error');
        if (logOutput) logOutput.textContent += '\n❌ Error: ' + err.message + '\n';
        if (statusText) statusText.textContent = 'Error en backup';
        currentBackupRunRepoId = null;
        updateBackupRunButtonState(false);
    }
}


// ─── RESTORE ────────────────────────────────────────────
async function loadRestoreView() {
    try {
        const [reposData, storagesData] = await Promise.all([
            API.getRepos(),
            API.getStorages().catch(() => ({ storages: [] })),
        ]);
        repos = reposData.repos || [];
        storages = storagesData.storages || [];
    } catch (err) {
        showToast('Error cargando datos de restauración: ' + err.message, 'error');
    }
    populateRestoreStorageSelect();
    populateRestoreBackupSelect();
    const select = document.getElementById('restore-repo-select');
    if (select && !select.value) populateRestoreBackupSelect();
    const revisionList = document.getElementById('restore-revision-list');
    if (revisionList) {
        revisionList.innerHTML = '<option value="">-- Selecciona una revisión --</option>';
    }
    const hint = document.getElementById('restore-revision-hint');
    if (hint) hint.textContent = 'Selecciona primero un repositorio de destino y un backup.';
    restoreFileEntries = [];
    restoreFilteredEntries = [];
    restoreSelectedPatterns = new Set();
    restoreBrowserPath = '';
    renderRestoreBrowserChrome();
    renderRestorePathList([]);
    const pathFilter = document.getElementById('restore-path-filter');
    if (pathFilter) pathFilter.value = '';
    const restoreAll = document.getElementById('restore-all-toggle');
    if (restoreAll) restoreAll.checked = true;
    toggleRestoreAllMode();
}

function normalizeStorageComparableUrl(value) {
    return String(value || '').trim().replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();
}

function getSelectedRestoreStorage() {
    const storageId = document.getElementById('restore-storage-select')?.value || '';
    return (storages || []).find(s => s.id === storageId) || null;
}

function getRestoreSelectionContext() {
    const storage = getSelectedRestoreStorage();
    const raw = (document.getElementById('restore-repo-select')?.value || '').trim();
    if (!raw) return { kind: null, storage, storageId: storage?.id || '' };
    if (raw.startsWith('repo:')) {
        const repoId = raw.slice(5);
        const repo = repos.find(r => r.id === repoId) || null;
        return { kind: 'repo', storage, storageId: storage?.id || '', repoId, repo, snapshotId: repo?.snapshotId || null };
    }
    if (raw.startsWith('remote:')) {
        const snapshotId = raw.slice(7);
        return { kind: 'remote', storage, storageId: storage?.id || '', snapshotId };
    }
    // compat valores antiguos (repoId directo)
    const repo = repos.find(r => r.id === raw) || null;
    if (repo) return { kind: 'repo', storage, storageId: storage?.id || '', repoId: raw, repo, snapshotId: repo.snapshotId || null };
    return { kind: null, storage, storageId: storage?.id || '' };
}

function repoMatchesRestoreStorage(repo, storage) {
    if (!repo || !storage) return false;
    if (repo.storageRefId && storage.id && repo.storageRefId === storage.id) return true;
    const primary = getPrimaryStorage(repo);
    const repoUrl = normalizeStorageComparableUrl((primary && primary.url) || repo.storageUrl || '');
    const storageUrl = normalizeStorageComparableUrl(storage.url || storage.localPath || '');
    return !!repoUrl && !!storageUrl && repoUrl === storageUrl;
}

function populateRestoreStorageSelect() {
    const select = document.getElementById('restore-storage-select');
    if (!select) return;
    const prev = select.value || '';
    const options = (storages || []).map(s => {
        const typeLabel = (s.type || '').toLowerCase() === 'wasabi' ? 'Wasabi' : 'Local';
        const label = `${s.name || s.label || 'Repositorio'} (${typeLabel})`;
        return `<option value="${escapeHtml(s.id)}">${escapeHtml(label)}</option>`;
    });
    select.innerHTML = '<option value="">-- Seleccionar destino --</option>' + options.join('');
    if (prev && (storages || []).some(s => s.id === prev)) {
        select.value = prev;
    }
}

function populateRestoreBackupSelect() {
    const storageId = document.getElementById('restore-storage-select')?.value || '';
    const select = document.getElementById('restore-repo-select');
    if (!select) return;
    const prev = select.value || '';
    if (!storageId) {
        select.innerHTML = '<option value="">-- Selecciona un destino primero --</option>';
        return;
    }
    const storage = (storages || []).find(s => s.id === storageId);
    const filtered = storage ? repos.filter(r => repoMatchesRestoreStorage(r, storage)) : [];
    const remoteSnapshots = Array.isArray(restoreStorageSnapshotsCache[storageId]) ? restoreStorageSnapshotsCache[storageId] : [];
    const localSnapshotIds = new Set(filtered.map(r => String(r.snapshotId || '').trim()).filter(Boolean));
    const remoteOnly = remoteSnapshots.filter(s => !localSnapshotIds.has(String(s.snapshotId || '').trim()));
    if (!filtered.length && !remoteOnly.length) {
        select.innerHTML = '<option value="">-- No hay backups para este destino --</option>';
        return;
    }
    const localOpts = filtered.map(r => {
            const label = `${r.name} · ${r.snapshotId || 'sin Backup ID'} · ${r.path || 'sin ruta'}`;
            return `<option value="repo:${escapeAttr(r.id)}">${escapeHtml(label)}</option>`;
        });
    const remoteOpts = remoteOnly.map(s => {
        const label = `${s.snapshotId} · remoto (${s.revisions || 0} rev)`;
        return `<option value="remote:${escapeAttr(s.snapshotId)}">${escapeHtml(label)}</option>`;
    });
    select.innerHTML = '<option value="">-- Seleccionar backup --</option>' + [...localOpts, ...remoteOpts].join('');
    const canRestorePrev = (filtered.some(r => `repo:${r.id}` === prev) || remoteOnly.some(s => `remote:${s.snapshotId}` === prev));
    if (prev && canRestorePrev) {
        select.value = prev;
    }

    const wrap = document.getElementById('restore-repo-wrap');
    if (wrap) {
        wrap.style.display = (localOpts.length || remoteOpts.length) ? 'block' : 'none';
    }
}

async function onRestoreStorageChange() {
    const storageId = document.getElementById('restore-storage-select')?.value || '';
    const backupSelect = document.getElementById('restore-repo-select');
    const revisionHint = document.getElementById('restore-revision-hint');
    if (backupSelect) {
        backupSelect.innerHTML = storageId
            ? '<option value="">-- Cargando backups del destino... --</option>'
            : '<option value="">-- Selecciona un destino primero --</option>';
    }
    if (revisionHint && storageId) {
        revisionHint.textContent = 'Cargando Backup IDs del destino... (en storages grandes puede tardar)';
    }
    if (storageId && Array.isArray(restoreStorageSnapshotsCache[storageId])) {
        // Reuse cached IDs for this session to avoid long waits on every reselect.
    } else if (storageId) {
        try {
            const result = await API.getStorageSnapshots(storageId);
            restoreStorageSnapshotsCache[storageId] = result.snapshots || [];
            const count = (result.snapshots || []).length;
            showToast(count ? `✅ ${count} Backup ID(s) cargado(s)` : 'No se encontraron Backup IDs', count ? 'success' : 'warning');
        } catch (err) {
            restoreStorageSnapshotsCache[storageId] = [];
            showToast('Error cargando Backup IDs del destino: ' + err.message, 'warning');
        }
    }
    populateRestoreBackupSelect();
    
    let autoSelected = false;
    if (backupSelect) {
        const realOptions = Array.from(backupSelect.options).filter(o => o.value);
        if (realOptions.length === 1) {
            backupSelect.value = realOptions[0].value;
            autoSelected = true;
            onRestoreRepoChange();
        }
    }
    const targetInput = document.getElementById('restore-target-path');
    if (targetInput) targetInput.value = '';
    
    if (!autoSelected) {
        const revisionList = document.getElementById('restore-revision-list');
        if (revisionList) revisionList.innerHTML = '<option value="">-- Selecciona un backup primero --</option>';
        const hint = document.getElementById('restore-revision-hint');
        if (hint) hint.textContent = 'Selecciona un backup del destino elegido para consultar revisiones.';
        resetRestorePartialSelection();
    }
}

function onRestoreRepoChange() {
    prefillRestorePathFromRepo();
    resetRestorePartialSelection();
    loadRestoreRevisions();
}

function prefillRestorePathFromRepo() {
    const ctx = getRestoreSelectionContext();
    const input = document.getElementById('restore-target-path');
    if (!input) return;
    if (ctx.kind !== 'repo') return;
    const repo = ctx.repo;
    if (!repo) return;
    if (!input.value.trim()) {
        input.value = repo.path || '';
    }
}

async function pickRestoreTargetFolder() {
    const input = document.getElementById('restore-target-path');
    await pickFolderIntoInput(input);
}

async function loadRestoreRevisions() {
    const ctx = getRestoreSelectionContext();
    const list = document.getElementById('restore-revision-list');
    const hint = document.getElementById('restore-revision-hint');
    if (!list) return;

    if (!ctx.kind) {
        list.innerHTML = '<option value="">-- Selecciona un backup primero --</option>';
        if (hint) hint.textContent = 'Selecciona un backup para consultar sus revisiones.';
        resetRestorePartialSelection();
        return;
    }

    list.innerHTML = '<option value="">Cargando revisiones...</option>';
    if (hint) hint.textContent = 'Consultando revisiones del backup...';

    try {
        const cacheKey = ctx.kind === 'repo'
            ? `repo:${ctx.repoId}`
            : `storage:${ctx.storageId}:${ctx.snapshotId}`;
        let data;
        if (restoreRevisionsCache[cacheKey]) {
            data = restoreRevisionsCache[cacheKey];
        } else {
            data = ctx.kind === 'repo'
                ? await API.getSnapshots(ctx.repoId)
                : await API.getStorageSnapshotRevisions(ctx.storageId, ctx.snapshotId);
            restoreRevisionsCache[cacheKey] = data;
        }
        const snapshots = (data.snapshots || []).sort((a, b) => b.revision - a.revision);
        if (!snapshots.length) {
            list.innerHTML = '<option value="">Sin revisiones disponibles</option>';
            if (hint) hint.textContent = 'Este backup aún no tiene revisiones.';
            resetRestorePartialSelection();
            return;
        }

        list.innerHTML = '<option value="">-- Selecciona una revisión --</option>' +
            snapshots.map(s => `<option value="${s.revision}">#${s.revision} · ${escapeHtml(s.createdAt || '')}</option>`).join('');
        if (hint) hint.textContent = `Se encontraron ${snapshots.length} revisiones. Elige una o escríbela manualmente.`;
        if (!list.value && snapshots[0]) {
            list.value = String(snapshots[0].revision);
            onRestoreRevisionChange();
        }
    } catch (err) {
        list.innerHTML = '<option value="">Error cargando revisiones</option>';
        if (hint) hint.textContent = `Error al consultar revisiones: ${err.message}`;
    }
}

function onRestoreRevisionChange() {
    resetRestorePartialSelection();
    const hint = document.getElementById('restore-path-hint');
    if (hint) {
        hint.textContent = 'Revisión seleccionada. Pulsa "Cargar ficheros/carpetas" solo si quieres restauración parcial.';
    }
}

async function loadRestoreFilesForSelectedRevision() {
    const ctx = getRestoreSelectionContext();
    const list = document.getElementById('restore-revision-list');
    const revision = parseInt(list?.value || '', 10);
    const pathHint = document.getElementById('restore-path-hint');

    console.log('[Restore] Loading files for:', { ctx, revision });

    if (!ctx.kind || !revision) {
        resetRestorePartialSelection();
        if (pathHint) pathHint.textContent = 'Selecciona una revisión para cargar archivos y carpetas.';
        showToast('Debes seleccionar un origen de destino y una revisión antes de cargar las rutas.', 'warning');
        return;
    }

    if (pathHint) pathHint.textContent = 'Consultando archivos y carpetas del snapshot...';
    try {
        const cacheKey = ctx.kind === 'repo'
            ? `repo:${ctx.repoId}:rev:${revision}`
            : `storage:${ctx.storageId}:${ctx.snapshotId}:rev:${revision}`;
        let data;
        if (restoreFilesCache[cacheKey]) {
            data = restoreFilesCache[cacheKey];
        } else {
            data = ctx.kind === 'repo'
                ? await API.getSnapshotFiles(ctx.repoId, revision)
                : await API.getStorageSnapshotFiles(ctx.storageId, ctx.snapshotId, revision);
            restoreFilesCache[cacheKey] = data;
        }
        const parsedFiles = (data.files || []).filter(f => (f.path || '').trim());
        restoreFileEntries = buildRestoreSelectableEntries(parsedFiles);
        restoreSelectedPatterns = new Set();
        restoreBrowserPath = '';
        const pathFilter = document.getElementById('restore-path-filter');
        if (pathFilter) pathFilter.value = '';
        filterRestorePaths();
        toggleRestoreAllMode();
    } catch (err) {
        resetRestorePartialSelection();
        if (pathHint) pathHint.textContent = `Error cargando rutas: ${err.message}`;
        showToast('Error cargando ficheros de la revisión: ' + err.message, 'error');
    }
}

function resetRestorePartialSelection() {
    restoreFileEntries = [];
    restoreFilteredEntries = [];
    restoreSelectedPatterns = new Set();
    restoreBrowserPath = '';
    const pathFilter = document.getElementById('restore-path-filter');
    if (pathFilter) pathFilter.value = '';
    renderRestoreBrowserChrome();
    renderRestorePathList([]);
    toggleRestoreAllMode();
    document.getElementById('restore-all-toggle').checked = true;
}

function openRestoreSelectorModal() {
    const isAllMode = document.getElementById('restore-all-toggle')?.checked;
    if (isAllMode) {
        document.getElementById('restore-all-toggle').checked = false;
        toggleRestoreAllMode();
    }
    const modal = document.getElementById('modal-restore-selector');
    if (modal) modal.classList.add('show');
}

function closeRestoreSelectorModal() {
    const modal = document.getElementById('modal-restore-selector');
    if (modal) modal.classList.remove('show');
    updateRestorePartialSummary();
}

function saveRestoreSelectorSelection() {
    closeRestoreSelectorModal();
}

function updateRestorePartialSummary() {
    const pathHint = document.getElementById('restore-path-hint');
    if (!pathHint) return;

    if (restoreSelectedPatterns.size === 0) {
        pathHint.textContent = "Has desmarcado 'Restaurar todo' pero no has elegido ningún archivo/carpeta. Se restaurará todo por defecto.";
    } else {
        pathHint.innerHTML = `Se restaurarán <strong>${restoreSelectedPatterns.size}</strong> archivos/carpetas directamente seleccionados.`;
    }
}

function normalizeRestoreBrowserPath(path) {
    const normalized = String(path || '').replace(/\\/g, '/').replace(/^\/+/, '');
    if (!normalized) return '';
    return normalized.endsWith('/') ? normalized : `${normalized}/`;
}

function goToRestoreRootFolder() {
    restoreBrowserPath = '';
    renderRestoreBrowserChrome();
    filterRestorePaths();
}

function goUpRestoreFolder() {
    if (!restoreBrowserPath) return;
    const trimmed = restoreBrowserPath.replace(/\/+$/, '');
    const parent = getPathParent(trimmed, true);
    restoreBrowserPath = parent ? `${parent}/` : '';
    renderRestoreBrowserChrome();
    filterRestorePaths();
}

function openRestoreFolder(path) {
    restoreBrowserPath = normalizeRestoreBrowserPath(path);
    renderRestoreBrowserChrome();
    filterRestorePaths();
}

function openRestoreFolderFromBreadcrumb(encodedPath) {
    restoreBrowserPath = normalizeRestoreBrowserPath(decodeURIComponent(encodedPath || ''));
    renderRestoreBrowserChrome();
    filterRestorePaths();
}

function renderRestoreBrowserChrome() {
    const breadcrumbs = document.getElementById('restore-browser-breadcrumbs');
    const upBtn = document.getElementById('btn-restore-up');
    const rootBtn = document.getElementById('btn-restore-root');
    const allMode = isRestoreAllMode();

    if (upBtn) upBtn.disabled = allMode || !restoreBrowserPath;
    if (rootBtn) rootBtn.disabled = allMode || !restoreBrowserPath;

    if (!breadcrumbs) return;

    const parts = restoreBrowserPath.replace(/\/+$/, '').split('/').filter(Boolean);
    if (!parts.length) {
        breadcrumbs.innerHTML = '<span class="restore-breadcrumb-current">Raíz</span>';
        return;
    }

    let acc = '';
    const crumbs = [
        '<button type="button" class="restore-breadcrumb-link" data-restore-breadcrumb="">Raíz</button>'
    ];
    for (let i = 0; i < parts.length; i++) {
        const part = parts[i];
        acc = acc ? `${acc}/${part}` : part;
        const isLast = i === parts.length - 1;
        const encoded = encodeURIComponent(`${acc}/`);
        crumbs.push('<span class="restore-breadcrumb-sep">/</span>');
        if (isLast) {
            crumbs.push(`<span class="restore-breadcrumb-current">${escapeHtml(part)}</span>`);
        } else {
            crumbs.push(`<button type="button" class="restore-breadcrumb-link" data-restore-breadcrumb="${encoded}">${escapeHtml(part)}</button>`);
        }
    }
    breadcrumbs.innerHTML = crumbs.join('');

    breadcrumbs.querySelectorAll('[data-restore-breadcrumb]').forEach(btn => {
        btn.addEventListener('click', () => {
            const raw = btn.getAttribute('data-restore-breadcrumb') || '';
            openRestoreFolderFromBreadcrumb(raw);
        });
    });
}

function renderRestorePathList(entries) {
    const list = document.getElementById('restore-path-list');
    if (!list) return;

    renderRestoreBrowserChrome();
    restoreFilteredEntries = entries.slice();

    if (!entries.length) {
        const message = restoreFileEntries.length
            ? 'Carpeta vacía (o el filtro no coincide con nada en esta carpeta).'
            : '-- Sin rutas cargadas --';
        list.innerHTML = `<div class="restore-check-empty">${escapeHtml(message)}</div>`;
        updateRestoreSelectionUiState();
        return;
    }

    list.innerHTML = entries.map(item => {
        const icon = item.isDir ? '📁' : '📄';
        const path = item.path || '';
        const label = item.name || getPathBaseName(path, !!item.isDir);
        const title = item.path || item.raw || '';
        const key = encodeURIComponent(path);
        const checked = restoreSelectedPatterns.has(path) ? 'checked' : '';
        const parent = item.parentDisplay || getPathParent(path, !!item.isDir) || 'Raíz';
        const openBtn = item.isDir
            ? `<button type="button" class="restore-entry-open" data-restore-open="${key}" title="Abrir carpeta">Abrir</button>`
            : '';
        return `
            <div class="restore-check-item" title="${escapeAttr(title)}" ${item.isDir ? `data-restore-dir="${key}"` : ''}>
                <input type="checkbox" data-restore-key="${key}" ${checked} />
                <span class="restore-check-icon">${icon}</span>
                <div class="restore-check-main">
                    <div class="restore-check-row">
                        ${item.isDir
                            ? `<button type="button" class="restore-check-label restore-folder-link" data-restore-open="${key}">${escapeHtml(label)}</button>`
                            : `<span class="restore-check-label">${escapeHtml(label)}</span>`}
                        ${openBtn}
                    </div>
                    <span class="restore-check-path">${escapeHtml(parent)}</span>
                </div>
            </div>
        `;
    }).join('');

    list.querySelectorAll('input[type="checkbox"][data-restore-key]').forEach(cb => {
        cb.addEventListener('change', () => {
            const path = decodeURIComponent(cb.getAttribute('data-restore-key') || '');
            if (!path) return;
            if (cb.checked) {
                restoreSelectedPatterns.add(path);
            } else {
                restoreSelectedPatterns.delete(path);
            }
            updateRestoreSelectionUiState();
        });
    });

    list.querySelectorAll('[data-restore-open]').forEach(btn => {
        btn.addEventListener('click', () => {
            const encodedPath = btn.getAttribute('data-restore-open') || '';
            if (!encodedPath) return;
            openRestoreFolder(decodeURIComponent(encodedPath));
        });
    });

    list.querySelectorAll('[data-restore-dir]').forEach(row => {
        row.addEventListener('dblclick', (ev) => {
            if (ev.target && ev.target.closest('input[type="checkbox"]')) return;
            const encodedPath = row.getAttribute('data-restore-dir') || '';
            if (!encodedPath) return;
            openRestoreFolder(decodeURIComponent(encodedPath));
        });
    });

    updateRestoreSelectionUiState();
}

function filterRestorePaths() {
    const q = (document.getElementById('restore-path-filter')?.value || '').trim().toLowerCase();
    const currentFolder = restoreBrowserPath;
    const inCurrentFolder = restoreFileEntries.filter(item => (item.parentDirPath || '') === currentFolder);
    const filtered = !q
        ? inCurrentFolder
        : inCurrentFolder.filter(item =>
            (item.path || '').toLowerCase().includes(q) ||
            (item.name || '').toLowerCase().includes(q)
        );
    renderRestorePathList(filtered);
}

function clearRestorePathSelection() {
    restoreSelectedPatterns.clear();
    renderRestorePathList(restoreFilteredEntries);
}

function selectVisibleRestorePaths() {
    for (const entry of restoreFilteredEntries) {
        if (entry?.path) restoreSelectedPatterns.add(entry.path);
    }
    renderRestorePathList(restoreFilteredEntries);
}

function getSelectedRestorePatterns() {
    if (isRestoreAllMode()) return [];
    return expandRestoreSelectedPatterns();
}

function expandRestoreSelectedPatterns() {
    const allFiles = restoreFileEntries.filter(item => !item.isDir && item.path);
    const out = new Set();

    for (const selected of restoreSelectedPatterns) {
        if (!selected) continue;
        if (selected.endsWith('/')) {
            let matched = 0;
            for (const file of allFiles) {
                if ((file.path || '').startsWith(selected)) {
                    out.add(file.path);
                    matched += 1;
                }
            }
            if (matched === 0) out.add(selected);
        } else {
            out.add(selected);
        }
    }

    return Array.from(out);
}

function isRestoreAllMode() {
    return !!document.getElementById('restore-all-toggle')?.checked;
}

function toggleRestoreAllMode() {
    const all = isRestoreAllMode();
    const list = document.getElementById('restore-path-list');
    const filter = document.getElementById('restore-path-filter');
    const clearBtn = document.getElementById('btn-restore-clear-selection');
    const selectVisibleBtn = document.getElementById('btn-restore-select-visible');
    const toolbar = document.querySelector('.restore-browser-toolbar');
    const upBtn = document.getElementById('btn-restore-up');
    const rootBtn = document.getElementById('btn-restore-root');

    if (list) list.classList.toggle('disabled', all);
    if (filter) filter.disabled = all;
    if (clearBtn) clearBtn.disabled = all;
    if (selectVisibleBtn) selectVisibleBtn.disabled = all;
    if (toolbar) toolbar.classList.toggle('disabled', all);
    if (upBtn) upBtn.disabled = all || !restoreBrowserPath;
    if (rootBtn) rootBtn.disabled = all || !restoreBrowserPath;

    updateRestoreSelectionUiState();
}

function updateRestoreSelectionUiState() {
    const pathHint = document.getElementById('restore-path-hint');
    if (!pathHint) return;

    if (isRestoreAllMode()) {
        pathHint.textContent = 'Se restaurará todo el snapshot. Desmarca la opción para seleccionar ficheros/carpetas concretos.';
        return;
    }

    const selected = restoreSelectedPatterns.size;
    const total = restoreFileEntries.length;
    if (!total) {
        pathHint.textContent = 'Carga una revisión para poder marcar ficheros o carpetas.';
        return;
    }
    const currentLabel = restoreBrowserPath ? `Carpeta actual: ${restoreBrowserPath}` : 'Carpeta actual: raíz';
    pathHint.textContent = selected
        ? `Seleccionados ${selected} elemento(s). ${currentLabel}.`
        : `No hay elementos marcados. ${currentLabel}. Marca uno o varios, o activa "Restaurar todo".`;
}

function buildRestoreSelectableEntries(fileEntries) {
    const dirMap = new Map();
    const fileMap = new Map();

    for (const file of fileEntries) {
        const rawPath = String(file.path || '').trim().replace(/\\/g, '/');
        if (!rawPath) continue;
        const normalizedFilePath = rawPath.endsWith('/') ? rawPath.slice(0, -1) : rawPath;
        if (!normalizedFilePath) continue;

        if (!fileMap.has(normalizedFilePath)) {
            fileMap.set(normalizedFilePath, {
                path: normalizedFilePath,
                isDir: false,
                raw: file.raw || normalizedFilePath,
            });
        }

        const parts = normalizedFilePath.split('/').filter(Boolean);
        if (parts.length > 1) {
            let acc = '';
            for (let i = 0; i < parts.length - 1; i++) {
                acc = acc ? `${acc}/${parts[i]}` : parts[i];
                const dirPath = `${acc}/`;
                if (!dirMap.has(dirPath)) {
                    dirMap.set(dirPath, {
                        path: dirPath,
                        isDir: true,
                        raw: dirPath,
                    });
                }
            }
        }
    }

    return sortRestoreExplorerEntries([
        ...Array.from(dirMap.values()),
        ...Array.from(fileMap.values())
    ]).map(item => {
        const path = item.path || '';
        const parent = getPathParent(path, !!item.isDir);
        const parentDirPath = parent ? `${parent}/` : '';
        return {
            ...item,
            name: getPathBaseName(path, !!item.isDir),
            parentDirPath,
            parentDisplay: parent || 'Raíz'
        };
    });
}

function sortRestoreExplorerEntries(entries) {
    return entries.sort((a, b) => {
        if (!!a.isDir !== !!b.isDir) return a.isDir ? -1 : 1;
        const aName = getPathBaseName(a.path || '', !!a.isDir);
        const bName = getPathBaseName(b.path || '', !!b.isDir);
        const nameCmp = aName.localeCompare(bName, 'es', { sensitivity: 'base', numeric: true });
        if (nameCmp !== 0) return nameCmp;
        return (a.path || '').localeCompare(b.path || '', 'es', { sensitivity: 'base' });
    });
}

function getPathBaseName(path, isDir) {
    const normalized = String(path || '').replace(/\\/g, '/');
    const trimmed = isDir ? normalized.replace(/\/+$/, '') : normalized;
    if (!trimmed) return isDir ? '(carpeta raíz)' : '(archivo)';
    const parts = trimmed.split('/').filter(Boolean);
    return parts[parts.length - 1] || trimmed;
}

function getPathParent(path, isDir) {
    const normalized = String(path || '').replace(/\\/g, '/');
    const trimmed = isDir ? normalized.replace(/\/+$/, '') : normalized;
    const parts = trimmed.split('/').filter(Boolean);
    if (parts.length <= 1) return '';
    return parts.slice(0, -1).join('/');
}

async function restoreFromSnapshot(repoId, revision) {
    if (!confirm(`¿Restaurar revisión #${revision}? Esto sobrescribirá los archivos actuales.`)) return;

    navigateTo('restore');

    const logOutput = document.getElementById('restore-log');
    const statusText = document.getElementById('restore-status');

    if (logOutput) logOutput.textContent = `Restaurando revisión #${revision}...\n`;
    if (statusText) statusText.textContent = 'Restaurando...';
    const restorePath = (document.getElementById('restore-target-path')?.value || '').trim();
    const patterns = getSelectedRestorePatterns();
    if (logOutput && restorePath) {
        logOutput.textContent += `Ruta destino: ${restorePath}\n`;
    }
    if (logOutput && !isRestoreAllMode() && patterns.length) {
        logOutput.textContent += `Restauración parcial (${patterns.length} elementos seleccionados)\n`;
    }

    if (!isRestoreAllMode() && patterns.length === 0) {
        showToast('Marca al menos un fichero/carpeta o activa "Restaurar todo"', 'warning');
        if (statusText) statusText.textContent = 'Faltan elementos a restaurar';
        return;
    }

    try {
        const result = await API.restore(
            repoId,
            revision,
            true,
            undefined,
            restorePath || undefined,
            (!isRestoreAllMode() && patterns.length) ? patterns : undefined
        );
        if (logOutput) logOutput.textContent += '\n' + (result.output || 'Restauración completada') + '\n';
        if (statusText) statusText.textContent = 'Restauración completada';
        showToast('✅ Restauración completada', 'success');
    } catch (err) {
        if (logOutput) logOutput.textContent += '\n❌ Error: ' + err.message + '\n';
        if (statusText) statusText.textContent = 'Error en restauración';
        showToast('❌ Error: ' + err.message, 'error');
    }
}

async function submitRestore(e) {
    e.preventDefault();
    const ctx = getRestoreSelectionContext();
    const revision = parseInt(document.getElementById('restore-revision-list').value, 10);
    if (!ctx.kind || !revision) return showToast('Completa los campos', 'warning');

    if (ctx.kind === 'repo') {
        await restoreFromSnapshot(ctx.repoId, revision);
        return;
    }

    const logOutput = document.getElementById('restore-log');
    const statusText = document.getElementById('restore-status');
    const restorePath = (document.getElementById('restore-target-path')?.value || '').trim();
    const patterns = getSelectedRestorePatterns();
    if (!restorePath) {
        showToast('Para restaurar desde storage sin backup local debes indicar una ruta de restauración', 'warning');
        if (statusText) statusText.textContent = 'Falta ruta de restauración';
        return;
    }
    if (!isRestoreAllMode() && patterns.length === 0) {
        showToast('Marca al menos un fichero/carpeta o activa "Restaurar todo"', 'warning');
        if (statusText) statusText.textContent = 'Faltan elementos a restaurar';
        return;
    }

    if (!confirm(`¿Restaurar revisión #${revision} del Backup ID "${ctx.snapshotId}" en "${restorePath}"?`)) return;
    if (logOutput) {
        logOutput.textContent = `Restaurando desde storage...\nBackup ID: ${ctx.snapshotId}\nRevisión: #${revision}\nRuta destino: ${restorePath}\n`;
        if (!isRestoreAllMode() && patterns.length) {
            logOutput.textContent += `Restauración parcial (${patterns.length} elementos seleccionados)\n`;
        }
    }
    if (statusText) statusText.textContent = 'Restaurando desde storage...';

    try {
        const result = await API.restoreFromStorage(ctx.storageId, {
            storageId: ctx.storageId,
            snapshotId: ctx.snapshotId,
            revision,
            overwrite: true,
            restorePath,
            patterns: (!isRestoreAllMode() && patterns.length) ? patterns : undefined,
        });
        if (logOutput) logOutput.textContent += '\n' + (result.output || 'Restauración completada') + '\n';
        if (statusText) statusText.textContent = 'Restauración completada';
        showToast('✅ Restauración completada', 'success');
    } catch (err) {
        if (logOutput) logOutput.textContent += '\n❌ Error: ' + err.message + '\n';
        if (statusText) statusText.textContent = 'Error en restauración';
        showToast('❌ Error: ' + err.message, 'error');
    }
}

// ─── SETTINGS ───────────────────────────────────────────
async function loadSettingsView() {
    try {
        const data = await API.getSettings();
        const s = data.settings;
        document.getElementById('setting-duplicacy-path').value = s.duplicacy_path || s.duplicacyPath || '';
        document.getElementById('setting-port').value = s.port || 8500;
        document.getElementById('setting-language').value = s.language || 'es';
        document.getElementById('setting-theme').value = s.theme || currentTheme || 'dark';
        applyTheme(document.getElementById('setting-theme').value);
    } catch (err) {
        showToast('Error cargando settings', 'error');
    }
}

async function saveSettings(e) {
    e.preventDefault();
    try {
        await API.updateSettings({
            duplicacy_path: document.getElementById('setting-duplicacy-path').value,
            duplicacyPath: document.getElementById('setting-duplicacy-path').value,
            port: parseInt(document.getElementById('setting-port').value, 10),
            language: document.getElementById('setting-language').value,
            theme: document.getElementById('setting-theme').value
        });
        applyTheme(document.getElementById('setting-theme').value);
        showToast('✅ Configuración guardada', 'success');
    } catch (err) {
        showToast('❌ Error guardando', 'error');
    }
}

// ─── LOGS ───────────────────────────────────────────────
async function loadLogsView() {
    try {
        const data = await API.getLogFiles();
        const list = document.getElementById('log-files-list');
        if (!list) return;

        if (!data.files || data.files.length === 0) {
            list.innerHTML = '<div class="empty-state"><p>Sin archivos de log aún.</p></div>';
            return;
        }

        list.innerHTML = data.files.map(f => `
            <div class="card" style="cursor:pointer; margin-bottom:8px; padding:12px 16px;"
                 onclick="viewLogFile('${f}')">
                <span>📄 ${escapeHtml(f)}</span>
            </div>
        `).join('');
    } catch (err) {
        showToast('Error cargando logs', 'error');
    }
}

async function viewLogFile(filename) {
    try {
        const data = await API.readLogFile(filename);
        const viewer = document.getElementById('log-viewer');
        const placeholder = document.getElementById('log-placeholder');
        if (viewer) {
            viewer.innerHTML = renderStructuredLogContent(filename, data.content || '');
            viewer.style.display = 'block';
            viewer.classList.add('log-viewer-rich');
        }
        if (placeholder) {
            placeholder.style.display = 'none';
        }
    } catch (err) {
        showToast('Error leyendo log', 'error');
    }
}

function renderStructuredLogContent(filename, content) {
    const lines = String(content || '').split(/\r?\n/).filter(Boolean);
    if (!lines.length) {
        return '<div class="log-rich-empty">Archivo vacío</div>';
    }

    const parsed = lines.map(parseStructuredLogLine);
    const parsedNewestFirst = parsed.slice().reverse();
    const counts = { INFO: 0, WARNING: 0, ERROR: 0, DEBUG: 0, OTHER: 0 };
    for (const line of parsed) {
        const lvl = (line.level || 'OTHER').toUpperCase();
        counts[lvl] = (counts[lvl] || 0) + 1;
    }

    const statsHtml = `
      <div class="log-rich-header">
        <div class="log-rich-file">📄 ${escapeHtml(filename || '')}</div>
        <div class="log-rich-stats">
          <span class="log-chip info">INFO ${counts.INFO || 0}</span>
          <span class="log-chip warning">WARN ${counts.WARNING || 0}</span>
          <span class="log-chip error">ERROR ${counts.ERROR || 0}</span>
          <span class="log-chip debug">DEBUG ${counts.DEBUG || 0}</span>
          <span class="log-chip">Recientes arriba</span>
        </div>
      </div>`;

    const rowsHtml = parsedNewestFirst.map(line => {
        const level = (line.level || 'OTHER').toUpperCase();
        const levelClass = level === 'ERROR' ? 'error'
            : level === 'WARNING' ? 'warning'
            : level === 'INFO' ? 'info'
            : level === 'DEBUG' ? 'debug'
            : 'other';
        const opClass = line.opType ? ` log-row-op-${line.opType}` : '';
        const opBadge = line.opType
            ? `<span class="log-op-badge ${line.opType}">${line.opType === 'backup' ? 'BACKUP' : 'RESTORE'}</span>`
            : '';
        return `
          <div class="log-row${opClass}">
            <span class="log-col-time">${escapeHtml(line.time || '—')}</span>
            <span class="log-col-level ${levelClass}">${escapeHtml(level)}</span>
            <span class="log-col-source">${escapeHtml(line.source || 'Sistema')}</span>
            <span class="log-col-msg">${opBadge}${escapeHtml(line.message || line.raw || '')}</span>
          </div>
        `;
    }).join('');

    const rawEscaped = escapeHtml(content);
    return `
      ${statsHtml}
      <div class="log-rich-table">${rowsHtml}</div>
      <details class="log-raw-details">
        <summary>Ver texto raw</summary>
        <pre>${rawEscaped}</pre>
      </details>
    `;
}

function parseStructuredLogLine(rawLine) {
    const raw = String(rawLine || '');
    const m = raw.match(/^\[([^\]]+)\]\s+\[([^\]]+)\]\s+\[([^\]]+)\]\s*(.*)$/);
    if (!m) {
        return { raw, time: '', level: 'OTHER', source: '', message: raw, opType: null };
    }
    const message = m[4] || '';
    let opType = null;
    if (/\[Backup\]/i.test(message)) opType = 'backup';
    else if (/\[Restore\]/i.test(message)) opType = 'restore';
    return {
        raw,
        time: m[1] || '',
        level: (m[2] || '').toUpperCase(),
        source: m[3] || '',
        message,
        opType,
    };
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

// ─── SERVER HEALTH ──────────────────────────────────────
async function checkServerHealth() {
    try {
        const data = await API.health();
        const indicator = document.getElementById('server-status');
        if (indicator) {
            indicator.innerHTML = `<span class="badge badge-success">🟢 Servidor activo</span>`;
        }
    } catch {
        const indicator = document.getElementById('server-status');
        if (indicator) {
            indicator.innerHTML = `<span class="badge badge-error">🔴 Servidor offline</span>`;
        }
    }
}

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
