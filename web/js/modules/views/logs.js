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

