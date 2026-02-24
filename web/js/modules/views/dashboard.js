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

