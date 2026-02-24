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


