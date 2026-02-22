/**
 * DupliManager — Main SPA Application
 * Handles routing, view management, and UI orchestration
 */

// ─── STATE ──────────────────────────────────────────────
let currentView = 'dashboard';
let repos = [];
let selectedRepo = null;

// ─── INIT ───────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    navigateTo('dashboard');
    checkServerHealth();
});

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
        case 'backup':     loadBackupView(); break;
        case 'snapshots':  loadSnapshotsView(); break;
        case 'restore':    loadRestoreView(); break;
        case 'settings':   loadSettingsView(); break;
        case 'logs':       loadLogsView(); break;
    }
}

// ─── DASHBOARD ──────────────────────────────────────────
async function loadDashboard() {
    try {
        const data = await API.getRepos();
        repos = data.repos || [];
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
                <h3>Sin repositorios configurados</h3>
                <p>Crea tu primer repositorio de backup para empezar a proteger tus datos.</p>
                <button class="btn btn-primary" onclick="openNewRepoModal()">
                    <span>➕</span> Nuevo Repositorio
                </button>
            </div>
        `;
        return;
    }

    grid.innerHTML = repos.map(repo => `
        <div class="repo-card" data-id="${repo.id}">
            <div class="repo-header">
                <div>
                    <div class="repo-name">${escapeHtml(repo.name)}</div>
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
                    <span class="meta-label">Storage</span>
                    <span class="meta-value">${escapeHtml(repo.storageUrl || '—')}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">Snapshot ID</span>
                    <span class="meta-value">${escapeHtml(repo.snapshotId)}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">Cifrado</span>
                    <span class="meta-value">${repo.encrypted ? '🔒 Sí' : '🔓 No'}</span>
                </div>
            </div>
            <div class="repo-actions">
                <button class="btn btn-success btn-sm" onclick="runBackup('${repo.id}')">
                    ▶ Backup
                </button>
                <button class="btn btn-ghost btn-sm" onclick="viewSnapshots('${repo.id}')">
                    📋 Snapshots
                </button>
                <button class="btn btn-ghost btn-sm" onclick="confirmDeleteRepo('${repo.id}', '${escapeHtml(repo.name)}')">
                    🗑
                </button>
            </div>
        </div>
    `).join('');
}

function renderStatusBadge(status) {
    if (!status) return '<span class="badge badge-info">⏳ Pendiente</span>';
    if (status === 'success') return '<span class="badge badge-success">✅ OK</span>';
    if (status === 'error') return '<span class="badge badge-error">❌ Error</span>';
    return '<span class="badge badge-warning">⚠️ Desconocido</span>';
}

// ─── NEW REPO MODAL ─────────────────────────────────────
function openNewRepoModal() {
    document.getElementById('modal-new-repo').classList.add('show');
    document.getElementById('repo-form').reset();
}

function closeNewRepoModal() {
    document.getElementById('modal-new-repo').classList.remove('show');
}

async function submitNewRepo(e) {
    e.preventDefault();
    const form = e.target;
    const btn = form.querySelector('button[type="submit"]');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Inicializando...';

    try {
        const data = {
            name: form.repoName.value,
            path: form.repoPath.value,
            snapshotId: form.snapshotId.value,
            storageUrl: form.storageUrl.value,
            password: form.repoPassword.value || undefined,
            encrypt: form.repoPassword.value ? true : false
        };

        await API.createRepo(data);
        showToast('✅ Repositorio creado exitosamente', 'success');
        closeNewRepoModal();
        loadDashboard();

    } catch (err) {
        showToast('❌ Error: ' + err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '🚀 Crear Repositorio';
    }
}

// ─── BACKUP ─────────────────────────────────────────────
async function loadBackupView() {
    try {
        const data = await API.getRepos();
        repos = data.repos || [];
        const select = document.getElementById('backup-repo-select');
        select.innerHTML = '<option value="">-- Seleccionar repositorio --</option>' +
            repos.map(r => `<option value="${r.id}">${escapeHtml(r.name)} — ${escapeHtml(r.path)}</option>`).join('');
    } catch (err) {
        showToast('Error cargando repos', 'error');
    }
}

async function runBackup(repoId) {
    if (!repoId) {
        // If called from backup view, get selected repo
        repoId = document.getElementById('backup-repo-select')?.value;
        if (!repoId) return showToast('Selecciona un repositorio', 'warning');
    }

    const logOutput = document.getElementById('backup-log');
    const progressBar = document.getElementById('backup-progress-fill');
    const statusText = document.getElementById('backup-status');

    // Navigate to backup view if not there
    if (currentView !== 'backup') navigateTo('backup');

    if (logOutput) logOutput.textContent = 'Iniciando backup...\n';
    if (progressBar) progressBar.style.width = '0%';
    if (statusText) statusText.textContent = 'Ejecutando backup...';

    // Listen for progress via SSE
    const evtSource = API.subscribeProgress(repoId, (data) => {
        if (data.done) {
            if (logOutput) logOutput.textContent += '\n✅ Backup completado.\n';
            if (progressBar) progressBar.style.width = '100%';
            if (statusText) statusText.textContent = 'Backup completado';
            loadDashboard();
            return;
        }
        if (data.output && logOutput) {
            logOutput.textContent += data.output + '\n';
            logOutput.scrollTop = logOutput.scrollHeight;
        }
    });

    try {
        await API.startBackup(repoId);
        showToast('✅ Backup completado', 'success');
    } catch (err) {
        showToast('❌ Backup falló: ' + err.message, 'error');
        if (logOutput) logOutput.textContent += '\n❌ Error: ' + err.message + '\n';
        if (statusText) statusText.textContent = 'Error en backup';
    }
}

// ─── SNAPSHOTS ──────────────────────────────────────────
async function loadSnapshotsView() {
    try {
        const data = await API.getRepos();
        repos = data.repos || [];
        const select = document.getElementById('snapshots-repo-select');
        if (select) {
            select.innerHTML = '<option value="">-- Seleccionar repositorio --</option>' +
                repos.map(r => `<option value="${r.id}">${escapeHtml(r.name)}</option>`).join('');
        }
    } catch (err) {
        showToast('Error', 'error');
    }
}

function viewSnapshots(repoId) {
    navigateTo('snapshots');
    setTimeout(() => {
        const select = document.getElementById('snapshots-repo-select');
        if (select) {
            select.value = repoId;
            loadSnapshots();
        }
    }, 100);
}

async function loadSnapshots() {
    const repoId = document.getElementById('snapshots-repo-select')?.value;
    const container = document.getElementById('snapshots-list');
    if (!repoId || !container) return;

    container.innerHTML = '<div class="empty-state"><div class="spinner"></div><p>Cargando snapshots...</p></div>';

    try {
        const data = await API.getSnapshots(repoId);
        const snapshots = data.snapshots || [];

        if (snapshots.length === 0) {
            container.innerHTML = '<div class="empty-state"><div class="empty-icon">📭</div><h3>Sin snapshots</h3><p>Este repositorio aún no tiene backups realizados.</p></div>';
            return;
        }

        container.innerHTML = `
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>Revisión</th>
                            <th>Snapshot ID</th>
                            <th>Fecha de Creación</th>
                            <th>Acciones</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${snapshots.map(s => `
                            <tr>
                                <td><strong>#${s.revision}</strong></td>
                                <td>${escapeHtml(s.id)}</td>
                                <td>${escapeHtml(s.createdAt)}</td>
                                <td>
                                    <button class="btn btn-ghost btn-sm" onclick="restoreFromSnapshot('${repoId}', ${s.revision})">
                                        🔄 Restaurar
                                    </button>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;
    } catch (err) {
        container.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><h3>Error</h3><p>${escapeHtml(err.message)}</p></div>`;
    }
}

// ─── RESTORE ────────────────────────────────────────────
async function loadRestoreView() {
    await loadSnapshotsView(); // Reuse repo loading
    const select = document.getElementById('restore-repo-select');
    if (select) {
        select.innerHTML = '<option value="">-- Seleccionar repositorio --</option>' +
            repos.map(r => `<option value="${r.id}">${escapeHtml(r.name)}</option>`).join('');
    }
}

async function restoreFromSnapshot(repoId, revision) {
    if (!confirm(`¿Restaurar revisión #${revision}? Esto sobrescribirá los archivos actuales.`)) return;

    navigateTo('restore');

    const logOutput = document.getElementById('restore-log');
    const statusText = document.getElementById('restore-status');

    if (logOutput) logOutput.textContent = `Restaurando revisión #${revision}...\n`;
    if (statusText) statusText.textContent = 'Restaurando...';

    try {
        const result = await API.restore(repoId, revision, true);
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
    const repoId = document.getElementById('restore-repo-select').value;
    const revision = parseInt(document.getElementById('restore-revision').value, 10);
    if (!repoId || !revision) return showToast('Completa los campos', 'warning');
    await restoreFromSnapshot(repoId, revision);
}

// ─── SETTINGS ───────────────────────────────────────────
async function loadSettingsView() {
    try {
        const data = await API.getSettings();
        const s = data.settings;
        document.getElementById('setting-duplicacy-path').value = s.duplicacyPath || '';
        document.getElementById('setting-port').value = s.port || 8500;
        document.getElementById('setting-language').value = s.language || 'es';
    } catch (err) {
        showToast('Error cargando settings', 'error');
    }
}

async function saveSettings(e) {
    e.preventDefault();
    try {
        await API.updateSettings({
            duplicacyPath: document.getElementById('setting-duplicacy-path').value,
            port: parseInt(document.getElementById('setting-port').value, 10),
            language: document.getElementById('setting-language').value
        });
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
        if (viewer) {
            viewer.textContent = data.content || 'Archivo vacío';
            viewer.style.display = 'block';
        }
    } catch (err) {
        showToast('Error leyendo log', 'error');
    }
}

// ─── DELETE REPO ────────────────────────────────────────
async function confirmDeleteRepo(id, name) {
    if (!confirm(`¿Eliminar repositorio "${name}" de la configuración?\n\n⚠️ Esto NO borra los datos de backup, solo elimina la configuración de DupliManager.`)) return;

    try {
        await API.deleteRepo(id);
        showToast('🗑 Repositorio eliminado de la configuración', 'success');
        loadDashboard();
    } catch (err) {
        showToast('Error: ' + err.message, 'error');
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
function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function formatDate(isoString) {
    if (!isoString) return '—';
    const d = new Date(isoString);
    return d.toLocaleString('es-ES', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit'
    });
}
