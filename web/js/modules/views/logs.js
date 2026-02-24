// ─── LOGS ───────────────────────────────────────────────
let currentLogFileName = '';
let currentLogPageRows = [];
let currentLogAllRowsFallback = null;
let currentLogUsingLegacyFallback = false;
let currentLogQuery = {
    offset: 0,
    limit: 200,
    level: '',
    op_type: '',
    text: '',
    date_from: '',
    date_to: '',
    reverse: true,
};
let currentLogTotal = 0;
let currentLogSummary = { levels: {}, types: {} };

async function loadLogsView() {
    try {
        const data = await API.getLogFiles();
        const select = document.getElementById('log-file-select');
        if (!select) return;

        if (!data.files || data.files.length === 0) {
            select.innerHTML = '<option value="">-- Sin archivos de log --</option>';
            const viewer = document.getElementById('log-viewer');
            const placeholder = document.getElementById('log-placeholder');
            if (viewer) {
                viewer.style.display = 'none';
                viewer.innerHTML = '';
            }
            if (placeholder) {
                placeholder.style.display = 'block';
                placeholder.innerHTML = '<p>Sin archivos de log aún.</p>';
            }
            return;
        }

        const previous = select.value || currentLogFileName || '';
        select.innerHTML =
            '<option value="">-- Selecciona un archivo --</option>' +
            data.files.map(f => `<option value="${escapeAttr(f)}">${escapeHtml(f)}</option>`).join('');

        if (!select.dataset.boundChange) {
            select.addEventListener('change', () => {
                const filename = select.value || '';
                if (!filename) return;
                viewLogFile(filename);
            });
            select.dataset.boundChange = '1';
        }

        const target = (previous && data.files.includes(previous)) ? previous : (data.files[0] || '');
        if (target) {
            select.value = target;
            if (target !== currentLogFileName || !document.getElementById('log-viewer')?.innerHTML) {
                await viewLogFile(target);
            }
        }
    } catch (err) {
        showToast('Error cargando logs', 'error');
    }
}

async function viewLogFile(filename) {
    currentLogFileName = filename;
    const select = document.getElementById('log-file-select');
    if (select && select.value !== filename) select.value = filename;
    currentLogQuery = {
        offset: 0,
        limit: 200,
        level: '',
        op_type: '',
        text: '',
        date_from: '',
        date_to: '',
        reverse: true,
    };
    renderLogViewerShell(filename);
    bindLogViewerControls();
    await refreshLogPage();
}

function renderLogViewerShell(filename) {
    const viewer = document.getElementById('log-viewer');
    const placeholder = document.getElementById('log-placeholder');
    if (!viewer) return;

    viewer.innerHTML = `
      <div class="log-rich-header">
        <div class="log-rich-file">📄 ${escapeHtml(filename || '')}</div>
        <div class="log-rich-stats" id="log-rich-stats-header">
          <span class="log-chip">Cargando...</span>
        </div>
      </div>

      <div class="log-rich-controls">
        <input id="log-filter-text" class="form-input" type="text" placeholder="Buscar texto, backup id, ruta, error..." />
        <select id="log-filter-level" class="form-select">
          <option value="">Todos los niveles</option>
          <option value="ERROR">ERROR</option>
          <option value="WARNING">WARNING</option>
          <option value="INFO">INFO</option>
          <option value="DEBUG">DEBUG</option>
          <option value="OTHER">OTHER</option>
        </select>
        <select id="log-filter-type" class="form-select">
          <option value="">Todos los tipos</option>
          <option value="backup">Backup</option>
          <option value="restore">Restore</option>
          <option value="storage">Storage</option>
          <option value="scheduler">Scheduler</option>
          <option value="duplicacy">DuplicacyCLI</option>
        </select>
        <input id="log-filter-from" class="form-input" type="date" title="Desde" />
        <input id="log-filter-to" class="form-input" type="date" title="Hasta" />
      </div>

      <div class="log-rich-controls" style="margin-top:8px;">
        <button id="log-quick-errors" type="button" class="btn btn-ghost btn-sm">🚨 Solo errores</button>
        <button id="log-quick-scheduler" type="button" class="btn btn-ghost btn-sm">⏰ Solo scheduler</button>
        <button id="log-quick-clear" type="button" class="btn btn-ghost btn-sm">🧹 Limpiar filtros</button>
        <button id="log-refresh-page" type="button" class="btn btn-ghost btn-sm">🔄 Refrescar</button>
        <button id="log-export-filtered" type="button" class="btn btn-primary btn-sm">📤 Exportar filtrado</button>
      </div>

      <div id="log-rich-summary" class="log-rich-summary"></div>
      <div id="log-rich-table" class="log-rich-table"><div class="log-rich-empty">Cargando...</div></div>

      <div class="log-rich-controls" style="margin-top:12px; align-items:center;">
        <button id="log-page-prev" type="button" class="btn btn-ghost btn-sm">⬅️ Anterior</button>
        <button id="log-page-next" type="button" class="btn btn-ghost btn-sm">Siguiente ➡️</button>
        <select id="log-page-size" class="form-select" style="max-width:140px;">
          <option value="100">100 líneas</option>
          <option value="200" selected>200 líneas</option>
          <option value="500">500 líneas</option>
        </select>
        <span id="log-page-info" class="form-hint" style="margin-left:auto;">—</span>
      </div>
    `;

    viewer.style.display = 'flex';
    viewer.classList.add('log-viewer-rich');
    if (placeholder) placeholder.style.display = 'none';
}

function bindLogViewerControls() {
    const textInput = document.getElementById('log-filter-text');
    const levelSel = document.getElementById('log-filter-level');
    const typeSel = document.getElementById('log-filter-type');
    const fromInput = document.getElementById('log-filter-from');
    const toInput = document.getElementById('log-filter-to');
    const pageSize = document.getElementById('log-page-size');

    const debounceApply = debounce(() => {
        currentLogQuery.offset = 0;
        syncLogQueryFromControls();
        refreshLogPage();
    }, 250);

    textInput?.addEventListener('input', debounceApply);
    levelSel?.addEventListener('change', debounceApply);
    typeSel?.addEventListener('change', debounceApply);
    fromInput?.addEventListener('change', debounceApply);
    toInput?.addEventListener('change', debounceApply);
    pageSize?.addEventListener('change', () => {
        currentLogQuery.offset = 0;
        currentLogQuery.limit = parseInt(pageSize.value, 10) || 200;
        refreshLogPage();
    });

    document.getElementById('log-page-prev')?.addEventListener('click', () => {
        currentLogQuery.offset = Math.max(0, (currentLogQuery.offset || 0) - (currentLogQuery.limit || 200));
        refreshLogPage();
    });
    document.getElementById('log-page-next')?.addEventListener('click', () => {
        currentLogQuery.offset = (currentLogQuery.offset || 0) + (currentLogQuery.limit || 200);
        refreshLogPage();
    });

    document.getElementById('log-quick-errors')?.addEventListener('click', () => {
        const level = document.getElementById('log-filter-level');
        const type = document.getElementById('log-filter-type');
        if (level) level.value = 'ERROR';
        if (type) type.value = '';
        currentLogQuery.offset = 0;
        syncLogQueryFromControls();
        refreshLogPage();
    });
    document.getElementById('log-quick-scheduler')?.addEventListener('click', () => {
        const level = document.getElementById('log-filter-level');
        const type = document.getElementById('log-filter-type');
        if (type) type.value = 'scheduler';
        if (level) level.value = '';
        currentLogQuery.offset = 0;
        syncLogQueryFromControls();
        refreshLogPage();
    });
    document.getElementById('log-quick-clear')?.addEventListener('click', () => {
        if (textInput) textInput.value = '';
        if (levelSel) levelSel.value = '';
        if (typeSel) typeSel.value = '';
        if (fromInput) fromInput.value = '';
        if (toInput) toInput.value = '';
        currentLogQuery.offset = 0;
        syncLogQueryFromControls();
        refreshLogPage();
    });
    document.getElementById('log-refresh-page')?.addEventListener('click', () => refreshLogPage());
    document.getElementById('log-export-filtered')?.addEventListener('click', exportFilteredLogView);

    // Apply initial defaults
    syncControlsFromLogQuery();
}

function syncLogQueryFromControls() {
    currentLogQuery.text = String(document.getElementById('log-filter-text')?.value || '').trim();
    currentLogQuery.level = String(document.getElementById('log-filter-level')?.value || '').trim();
    currentLogQuery.op_type = String(document.getElementById('log-filter-type')?.value || '').trim();
    currentLogQuery.date_from = String(document.getElementById('log-filter-from')?.value || '').trim();
    currentLogQuery.date_to = String(document.getElementById('log-filter-to')?.value || '').trim();
    currentLogQuery.limit = parseInt(document.getElementById('log-page-size')?.value || currentLogQuery.limit || 200, 10) || 200;
}

function syncControlsFromLogQuery() {
    const setVal = (id, v) => {
        const el = document.getElementById(id);
        if (el) el.value = v ?? '';
    };
    setVal('log-filter-text', currentLogQuery.text || '');
    setVal('log-filter-level', currentLogQuery.level || '');
    setVal('log-filter-type', currentLogQuery.op_type || '');
    setVal('log-filter-from', currentLogQuery.date_from || '');
    setVal('log-filter-to', currentLogQuery.date_to || '');
    setVal('log-page-size', String(currentLogQuery.limit || 200));
}

async function refreshLogPage() {
    if (!currentLogFileName) return;
    syncLogQueryFromControls();
    const table = document.getElementById('log-rich-table');
    if (table) table.innerHTML = '<div class="log-rich-empty">Cargando...</div>';
    try {
        const data = await API.queryLogFile(currentLogFileName, currentLogQuery);
        currentLogUsingLegacyFallback = false;
        currentLogAllRowsFallback = null;
        currentLogPageRows = data.rows || [];
        currentLogTotal = data.total || 0;
        currentLogSummary = data.summary || { levels: {}, types: {} };
        renderLogPageResult(data);
    } catch (err) {
        const msg = String(err?.message || '');
        const routeMissing = /API route not found|HTTP 404/i.test(msg);
        if (routeMissing) {
            await refreshLogPageLegacyFallback();
            return;
        }
        if (table) table.innerHTML = `<div class="log-rich-empty">Error cargando log: ${escapeHtml(msg || 'Error')}</div>`;
        showToast('Error consultando log: ' + msg, 'error');
    }
}

async function refreshLogPageLegacyFallback() {
    const table = document.getElementById('log-rich-table');
    try {
        if (!Array.isArray(currentLogAllRowsFallback)) {
            const raw = await API.readLogFile(currentLogFileName);
            const lines = String(raw.content || '').split(/\r?\n/).filter(Boolean);
            currentLogAllRowsFallback = lines.map(parseStructuredLogLine);
        }
        currentLogUsingLegacyFallback = true;
        const data = buildLegacyLogQueryResult(currentLogAllRowsFallback, currentLogQuery, currentLogFileName);
        currentLogPageRows = data.rows || [];
        currentLogTotal = data.total || 0;
        currentLogSummary = data.summary || { levels: {}, types: {} };
        renderLogPageResult(data);
        const summary = document.getElementById('log-rich-summary');
        if (summary) {
            summary.textContent += ' · modo compatibilidad (backend antiguo)';
        }
    } catch (fallbackErr) {
        const msg = String(fallbackErr?.message || 'Error');
        if (table) table.innerHTML = `<div class="log-rich-empty">Error cargando log: ${escapeHtml(msg)}</div>`;
        showToast('Error consultando log: ' + msg, 'error');
    }
}

function renderLogPageResult(data) {
    const statsHeader = document.getElementById('log-rich-stats-header');
    const levels = (data.summary && data.summary.levels) || {};
    const types = (data.summary && data.summary.types) || {};
    if (statsHeader) {
        statsHeader.innerHTML = `
          <span class="log-chip info">INFO ${levels.INFO || 0}</span>
          <span class="log-chip warning">WARN ${levels.WARNING || 0}</span>
          <span class="log-chip error">ERROR ${levels.ERROR || 0}</span>
          <span class="log-chip debug">DEBUG ${levels.DEBUG || 0}</span>
          <span class="log-chip">Scheduler ${types.scheduler || 0}</span>
          <span class="log-chip">Recientes arriba</span>
        `;
    }

    const table = document.getElementById('log-rich-table');
    if (table) {
        table.innerHTML = currentLogPageRows.length
            ? renderLogRowsHtml(currentLogPageRows)
            : '<div class="log-rich-empty">Sin resultados para los filtros actuales</div>';
    }
    const summary = document.getElementById('log-rich-summary');
    if (summary) {
        const start = (data.total || 0) ? ((data.offset || 0) + 1) : 0;
        const end = (data.offset || 0) + (data.count || 0);
        summary.textContent = `Mostrando ${data.count || 0} de ${data.total || 0} líneas filtradas (${start}-${end})`;
    }
    const pageInfo = document.getElementById('log-page-info');
    if (pageInfo) {
        pageInfo.textContent = `Offset ${data.offset || 0} · Límite ${data.limit || 200}`;
    }
    const prevBtn = document.getElementById('log-page-prev');
    const nextBtn = document.getElementById('log-page-next');
    if (prevBtn) prevBtn.disabled = (data.offset || 0) <= 0;
    if (nextBtn) nextBtn.disabled = !data.hasMore;
}

function renderLogRowsHtml(rows) {
    return (rows || []).map(line => {
        const level = (line.level || 'OTHER').toUpperCase();
        const levelClass = level === 'ERROR' ? 'error'
            : level === 'WARNING' ? 'warning'
            : level === 'INFO' ? 'info'
            : level === 'DEBUG' ? 'debug'
            : 'other';
        const opClass = line.opType ? ` log-row-op-${line.opType}` : '';
        const opBadgeLabel = line.opType
            ? ({
                backup: 'BACKUP',
                restore: 'RESTORE',
                storage: 'STORAGE',
                scheduler: 'SCHEDULER',
                duplicacy: 'CLI',
            }[line.opType] || line.opType.toUpperCase())
            : '';
        const opBadge = line.opType ? `<span class="log-op-badge ${line.opType}">${escapeHtml(opBadgeLabel)}</span>` : '';
        return `
          <div class="log-row${opClass}">
            <span class="log-col-time">${escapeHtml(line.time || '—')}</span>
            <span class="log-col-level ${levelClass}">${escapeHtml(level)}</span>
            <span class="log-col-source">${escapeHtml(line.source || 'Sistema')}</span>
            <span class="log-col-msg">${opBadge}${escapeHtml(line.message || line.raw || '')}</span>
          </div>
        `;
    }).join('');
}

function exportFilteredLogView() {
    if (!currentLogFileName) return;
    syncLogQueryFromControls();
    if (currentLogUsingLegacyFallback) {
        exportFilteredLogViewLegacy();
        return;
    }
    const url = API.getLogExportUrl(currentLogFileName, currentLogQuery);
    window.open(url, '_blank');
}

function exportFilteredLogViewLegacy() {
    const rows = applyClientLogFilters(currentLogAllRowsFallback || [], currentLogQuery, !!currentLogQuery.reverse);
    const text = rows.map(r => r.raw || '').join('\n');
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    const base = (currentLogFileName || 'log').replace(/\.log$/i, '');
    a.download = `${base}-filtrado.log`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function buildLegacyLogQueryResult(allRows, query, filename) {
    const filtered = applyClientLogFilters(allRows || [], query, !!query.reverse);
    const offset = Math.max(0, parseInt(query.offset || 0, 10) || 0);
    const limit = Math.max(1, Math.min(1000, parseInt(query.limit || 200, 10) || 200));
    const page = filtered.slice(offset, offset + limit);
    return {
        ok: true,
        filename,
        offset,
        limit,
        count: page.length,
        total: filtered.length,
        hasMore: (offset + page.length) < filtered.length,
        reverse: !!query.reverse,
        summary: buildClientLogCounts(filtered),
        rows: page.map(r => ({
            raw: r.raw || '',
            time: r.time || '',
            timeIso: r.timeIso || null,
            level: r.level || 'OTHER',
            source: r.source || '',
            message: r.message || '',
            opType: r.opType || null,
        })),
    };
}

function applyClientLogFilters(rows, query, reverse = true) {
    const text = String(query.text || '').trim().toLowerCase();
    const level = String(query.level || '').trim().toUpperCase();
    const opType = String(query.op_type || '').trim().toLowerCase();
    const from = parseClientLogDate(query.date_from, false);
    const to = parseClientLogDate(query.date_to, true);

    let filtered = (rows || []).filter(r => {
        if (level && String(r.level || 'OTHER').toUpperCase() !== level) return false;
        if (opType && String(r.opType || '').toLowerCase() !== opType) return false;
        if (from || to) {
            const dt = r.dt || null;
            if (!dt) return false;
            if (from && dt < from) return false;
            if (to && dt > to) return false;
        }
        if (text) {
            const hay = `${r.time || ''} ${r.level || ''} ${r.source || ''} ${r.message || r.raw || ''}`.toLowerCase();
            if (!hay.includes(text)) return false;
        }
        return true;
    });
    if (reverse) filtered = filtered.slice().reverse();
    return filtered;
}

function buildClientLogCounts(rows) {
    const levels = { INFO: 0, WARNING: 0, ERROR: 0, DEBUG: 0, OTHER: 0 };
    const types = { backup: 0, restore: 0, storage: 0, scheduler: 0, duplicacy: 0 };
    for (const r of rows || []) {
        const lvl = String(r.level || 'OTHER').toUpperCase();
        levels[lvl] = (levels[lvl] || 0) + 1;
        const t = String(r.opType || '').toLowerCase();
        if (t) types[t] = (types[t] || 0) + 1;
    }
    return { levels, types };
}

function parseClientLogDate(value, endOfDay = false) {
    const s = String(value || '').trim();
    if (!s) return null;
    const d = new Date(endOfDay ? `${s}T23:59:59` : `${s}T00:00:00`);
    if (Number.isNaN(d.getTime())) return null;
    return d;
}

function parseStructuredLogLine(rawLine) {
    const raw = String(rawLine || '');
    const m = raw.match(/^\[([^\]]+)\]\s+\[([^\]]+)\]\s+\[([^\]]+)\]\s*(.*)$/);
    if (!m) {
        return { raw, time: '', timeIso: null, dt: null, level: 'OTHER', source: '', message: raw, opType: null };
    }
    const time = m[1] || '';
    const level = (m[2] || '').toUpperCase() || 'OTHER';
    const source = m[3] || '';
    const message = m[4] || '';
    const dt = parseStructuredLogDate(time);
    return {
        raw,
        time,
        timeIso: dt ? dt.toISOString() : null,
        dt,
        level,
        source,
        message,
        opType: inferLogOpType(source, message),
    };
}

function parseStructuredLogDate(value) {
    const s = String(value || '').trim();
    if (!s) return null;
    const d = new Date(s.replace(' ', 'T'));
    if (Number.isNaN(d.getTime())) return null;
    return d;
}

function inferLogOpType(source, message) {
    const src = String(source || '').toLowerCase();
    const msg = String(message || '');
    if (/\[Backup\]/i.test(msg)) return 'backup';
    if (/\[Restore\]/i.test(msg)) return 'restore';
    if (/\[Storage\]/i.test(msg) || /\bstorage\b/i.test(msg)) return 'storage';
    if (/\[Scheduler\]/i.test(msg)) return 'scheduler';
    if (src === 'duplicacycli') return 'duplicacy';
    return null;
}

function debounce(fn, waitMs = 200) {
    let t = null;
    return (...args) => {
        if (t) clearTimeout(t);
        t = setTimeout(() => fn(...args), waitMs);
    };
}
