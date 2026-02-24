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

