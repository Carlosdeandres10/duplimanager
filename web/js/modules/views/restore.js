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

