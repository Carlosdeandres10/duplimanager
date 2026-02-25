// ─── BACKUP ─────────────────────────────────────────────
let backupProgressTimer = null;
let backupProgressStartedAtMs = 0;

function setBackupFinishButtonVisible(show) {
    const btn = document.getElementById('btn-finish-backup');
    if (!btn) return;
    btn.style.display = show ? '' : 'none';
    const isRunning = !!currentBackupRunRepoId;
    btn.disabled = false;
    btn.textContent = isRunning ? '⏹ Terminar' : '✅ Finalizar';
    btn.title = isRunning ? 'Solicitar cancelación del backup en ejecución' : 'Limpiar log y estado de la ejecución';
}

function formatProgressElapsed(ms) {
    const totalSec = Math.max(0, Math.floor((ms || 0) / 1000));
    const min = Math.floor(totalSec / 60);
    const sec = totalSec % 60;
    return `${String(min).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
}

function setBackupProgressDetails(patch = {}) {
    const map = {
        phase: 'backup-progress-phase',
        elapsed: 'backup-progress-elapsed',
        snapshot: 'backup-progress-snapshot',
        target: 'backup-progress-target',
        lastline: 'backup-progress-lastline',
    };
    Object.entries(map).forEach(([key, id]) => {
        if (!(key in patch)) return;
        const el = document.getElementById(id);
        if (el) el.textContent = patch[key] ?? '—';
    });
}

function startBackupProgressTimer() {
    stopBackupProgressTimer();
    backupProgressStartedAtMs = Date.now();
    setBackupProgressDetails({ elapsed: '00:00' });
    backupProgressTimer = setInterval(() => {
        setBackupProgressDetails({ elapsed: formatProgressElapsed(Date.now() - backupProgressStartedAtMs) });
    }, 1000);
}

function stopBackupProgressTimer() {
    if (backupProgressTimer) {
        clearInterval(backupProgressTimer);
        backupProgressTimer = null;
    }
}

function finalizeBackupRunView() {
    if (currentBackupRunRepoId) {
        cancelBackupRun();
        return;
    }
    if (currentBackupEventSource) {
        currentBackupEventSource.close();
        currentBackupEventSource = null;
    }
    stopBackupProgressTimer();
    const progressBar = document.getElementById('backup-progress-fill');
    const statusText = document.getElementById('backup-status');
    const logOutput = document.getElementById('backup-log');
    if (progressBar) progressBar.style.width = '0%';
    if (statusText) statusText.textContent = 'Selecciona un repositorio para iniciar la copia de seguridad';
    if (logOutput) logOutput.textContent = 'Listo para iniciar...';
    setBackupProgressDetails({
        phase: 'Esperando',
        elapsed: '00:00',
        snapshot: '—',
        target: '—',
        lastline: 'Listo para iniciar',
    });
    setBackupFinishButtonVisible(false);
    updateBackupRunButtonState(false);
}

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
        setBackupProgressDetails({
            phase: 'Esperando',
            elapsed: '00:00',
            snapshot: '—',
            target: '—',
            lastline: 'Listo para iniciar',
        });
        if (!currentBackupRunRepoId) setBackupFinishButtonVisible(false);
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
    setBackupProgressDetails({
        phase: 'Inicializando',
        snapshot: repo?.snapshotId || '—',
        target: ((primaryStorage && primaryStorage.url) || repo?.storageUrl || '—'),
        lastline: 'Preparando ejecución...',
    });
    startBackupProgressTimer();
    if (progressBar) progressBar.style.width = '0%';
    if (statusText) statusText.textContent = 'Ejecutando backup...';
    currentBackupRunRepoId = repoId;
    setBackupFinishButtonVisible(true);
    updateBackupRunButtonState(true);

    let evtSource = null;
    const handleProgressEvent = (data) => {
        if (data.error) {
            streamDisconnected = true;
            if (statusText) statusText.textContent = 'Backup en curso (seguimiento desconectado)';
            setBackupProgressDetails({
                phase: 'Seguimiento desconectado',
                lastline: 'Se perdió la conexión de progreso. El backup puede seguir en ejecución.',
            });
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
            stopBackupProgressTimer();
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
            setBackupProgressDetails({
                phase: data.canceled ? 'Cancelado' : (data.success === false ? 'Error' : 'Completado'),
                elapsed: formatProgressElapsed(Date.now() - backupProgressStartedAtMs),
                lastline: data.canceled
                    ? 'Cancelado por el usuario'
                    : (data.success === false ? 'Finalizado con error' : 'Backup completado correctamente'),
            });
            currentBackupRunRepoId = null;
            setBackupFinishButtonVisible(true);
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
            setBackupProgressDetails({
                phase: seenDuplicacyOutput ? 'Procesando' : 'Escaneando',
                lastline: seenDuplicacyOutput ? 'Procesando bloques/archivos...' : 'Escaneando archivos (Duplicacy aún no muestra salida)...',
            });
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
            const lastLine = String(data.output || '').split(/\r?\n/).filter(Boolean).slice(-1)[0] || 'Salida de Duplicacy';
            setBackupProgressDetails({ phase: 'Ejecutando', lastline: lastLine });
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
        stopBackupProgressTimer();
        showToast('❌ Backup falló: ' + err.message, 'error');
        if (logOutput) logOutput.textContent += '\n❌ Error: ' + err.message + '\n';
        if (statusText) statusText.textContent = 'Error en backup';
        setBackupProgressDetails({
            phase: 'Error',
            elapsed: backupProgressStartedAtMs ? formatProgressElapsed(Date.now() - backupProgressStartedAtMs) : '00:00',
            lastline: err.message || 'Error iniciando backup',
        });
        currentBackupRunRepoId = null;
        setBackupFinishButtonVisible(true);
        updateBackupRunButtonState(false);
    }
}


