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
    
    // Rellenar visualmente el destino (solo lectura)
    const storageDisplay = document.getElementById('edit-repo-storage-display');
    if (storageDisplay) {
        const label = primary ? (primary.label || primary.name || 'default') : 'legacy';
        const url = (primary && primary.url) || repo.storageUrl || '—';
        storageDisplay.innerHTML = `
            <div style="display:flex; align-items:center; gap:8px;">
                <span style="font-size:16px;">${primary?.type === 'wasabi' ? '☁️' : '📁'}</span>
                <div>
                   <div style="font-weight:700;">${escapeHtml(label)}</div>
                   <code style="font-size:10px; color:var(--text-muted);">${escapeHtml(url)}</code>
                </div>
            </div>
        `;
    }

    form.repoId.value = repo.id;
    form.repoPath.value = repo.path || '';
    form.snapshotId.value = repo.snapshotId || '';
    applyRepoNotificationsToForm(form, repo.notifications || null);
    const notifyTestStatus = document.getElementById('edit-repo-notify-test-status');
    if (notifyTestStatus) {
        notifyTestStatus.textContent = 'Prueba el envío real a Healthchecks y/o correo con esta configuración.';
        notifyTestStatus.style.color = '';
    }
    applyScheduleToEditForm(repo.schedule || null);
    editRepoContentState = {
        rootPath: repo.path || '',
        selection: Array.isArray(repo.contentSelection) ? repo.contentSelection.slice() : [],
    };
    updateRepoContentSelectionSummary('edit');

    toggleEditScheduleFields();
    document.getElementById('modal-edit-repo').classList.add('show');
}


function closeEditRepoModal() {
    document.getElementById('modal-edit-repo').classList.remove('show');
}

// Eliminada función redundante toggleEditDestinationFields


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

function buildRepoNotificationsPayloadFromForm(form) {
    if (!form) return undefined;

    const hcEnabled = !!form.notifyHcEnabled?.checked;
    const hcUrl = (form.notifyHcUrl?.value || '').trim();
    const hcKeyword = (form.notifyHcKeyword?.value || '').trim();
    const hcSendLog = !!form.notifyHcSendLog?.checked;

    const emailEnabled = !!form.notifyEmailEnabled?.checked;
    const emailTo = (form.notifyEmailTo?.value || '').trim();
    const emailSubjectPrefix = (form.notifyEmailSubjectPrefix?.value || '').trim();
    const emailSendLog = !!form.notifyEmailSendLog?.checked;

    const hasHcOverride = hcEnabled || !!hcUrl || !!hcKeyword;
    const hasEmailOverride = emailEnabled || !!emailTo || !!emailSubjectPrefix;
    const anyBackupNotifConfig = hasHcOverride || hasEmailOverride;

    if (!anyBackupNotifConfig) {
        return undefined;
    }

    // Cuando se configuran notificaciones por backup, enviamos ambos canales con enabled explícito.
    // Así evitamos heredar un canal global no deseado (p.ej. email) y generar falsos positivos.
    return {
        healthchecks: {
            enabled: hcEnabled,
            url: hcUrl,
            successKeyword: hcKeyword,
            sendLog: hcSendLog,
        },
        email: {
            enabled: emailEnabled,
            to: emailTo,
            subjectPrefix: emailSubjectPrefix,
            sendLog: emailSendLog,
        },
    };
}

function applyRepoNotificationsToForm(form, notifications) {
    if (!form) return;
    const n = notifications || {};
    const hc = n.healthchecks || {};
    const mail = n.email || {};
    if (form.notifyHcEnabled) form.notifyHcEnabled.checked = !!hc.enabled;
    if (form.notifyHcUrl) form.notifyHcUrl.value = hc.url || '';
    if (form.notifyHcKeyword) form.notifyHcKeyword.value = hc.successKeyword || '';
    if (form.notifyHcSendLog) form.notifyHcSendLog.checked = hc.sendLog !== false;
    if (form.notifyEmailEnabled) form.notifyEmailEnabled.checked = !!mail.enabled;
    if (form.notifyEmailTo) form.notifyEmailTo.value = mail.to || '';
    if (form.notifyEmailSubjectPrefix) form.notifyEmailSubjectPrefix.value = mail.subjectPrefix || '';
    if (form.notifyEmailSendLog) form.notifyEmailSendLog.checked = mail.sendLog !== false;
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

async function testEditRepoNotifications() {
    const form = document.getElementById('edit-repo-form');
    if (!form || !form.repoId?.value) return;
    const btn = document.getElementById('btn-test-repo-notifications');
    const status = document.getElementById('edit-repo-notify-test-status');
    const payload = {
        notifications: buildRepoNotificationsPayloadFromForm(form) || {},
    };

    try {
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner"></span> Probando...';
        }
        if (status) {
            status.textContent = 'Probando envío a Healthchecks y/o correo...';
            status.style.color = '';
        }
        const result = await API.testRepoNotifications(form.repoId.value, payload);
        const ch = result.channels || {};
        const hcOk = ch.healthchecks?.ok;
        const mailOk = ch.email?.ok;
        const parts = [];
        if (hcOk) parts.push('Healthchecks OK');
        else if (ch.healthchecks?.skipped) parts.push('Healthchecks omitido');
        else if (ch.healthchecks?.error) parts.push(`Healthchecks ERROR: ${ch.healthchecks.error}`);
        if (mailOk) parts.push('Email OK');
        else if (ch.email?.skipped) parts.push('Email omitido');
        else if (ch.email?.error) parts.push(`Email ERROR: ${ch.email.error}`);

        const msg = parts.join(' · ') || 'Prueba completada';
        if (status) {
            status.textContent = msg;
            status.style.color = result.ok ? 'var(--accent-green)' : 'var(--accent-red)';
        }
        showToast((result.ok ? '✅ ' : '⚠️ ') + msg, result.ok ? 'success' : 'warning');
    } catch (err) {
        if (status) {
            status.textContent = 'Error en prueba: ' + err.message;
            status.style.color = 'var(--accent-red)';
        }
        showToast('❌ Error probando notificaciones: ' + err.message, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '🧪 Probar notificaciones';
        }
    }
}

async function submitEditRepo(e) {
    e.preventDefault();
    const form = e.target;
    const btn = form.querySelector('button[type="submit"]');
    const payload = {
        name: form.snapshotId.value, // El nombre visual sigue vinculado al ID por ahora
        contentSelection: resolveRepoContentSelectionForSubmit('edit', form.repoPath.value),
        schedule: buildSchedulePayloadFromEditForm(form),
    };
    const repoNotifications = buildRepoNotificationsPayloadFromForm(form);
    if (repoNotifications) payload.notifications = repoNotifications;

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
        const repoNotifications = buildRepoNotificationsPayloadFromForm(form);
        if (repoNotifications) data.notifications = repoNotifications;

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

// Eliminada función redundante pickEditRepoSourceFolder


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

