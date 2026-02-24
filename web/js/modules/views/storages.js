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

