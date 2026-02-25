// ─── SETTINGS ───────────────────────────────────────────
async function loadSettingsView() {
    try {
        const data = await API.getSettings();
        const s = data.settings;
        const n = s.notifications || {};
        const hc = n.healthchecks || {};
        const mail = n.email || {};
        const pa = s.panelAccess || {};
        document.getElementById('setting-duplicacy-path').value = s.duplicacy_path || s.duplicacyPath || '';
        document.getElementById('setting-host').value = s.host || '127.0.0.1';
        document.getElementById('setting-port').value = s.port || 8500;
        document.getElementById('setting-language').value = s.language || 'es';
        document.getElementById('setting-theme').value = s.theme || currentTheme || 'dark';
        const setChecked = (id, v) => { const el = document.getElementById(id); if (el) el.checked = !!v; };
        const setValue = (id, v) => { const el = document.getElementById(id); if (el) el.value = v ?? ''; };
        setChecked('setting-hc-enabled', !!hc.enabled);
        setValue('setting-hc-url', hc.url || '');
        setValue('setting-hc-keyword', hc.successKeyword || 'success');
        setValue('setting-hc-timeout', hc.timeoutSeconds || 10);
        setChecked('setting-hc-send-log', hc.sendLog !== false);

        setChecked('setting-email-enabled', !!mail.enabled);
        setValue('setting-email-smtp-host', mail.smtpHost || '');
        setValue('setting-email-smtp-port', mail.smtpPort || 587);
        setChecked('setting-email-starttls', mail.smtpStartTls !== false);
        setValue('setting-email-user', mail.smtpUsername || '');
        setValue('setting-email-pass', mail.smtpPassword || '');
        setValue('setting-email-from', mail.from || '');
        setValue('setting-email-to', mail.to || '');
        setValue('setting-email-subject-prefix', mail.subjectPrefix || '[DupliManager]');
        setChecked('setting-email-send-log', mail.sendLog !== false);
        setChecked('setting-panel-auth-enabled', !!pa.enabled);
        setValue('setting-panel-cookie-secure-mode', pa.cookieSecureMode || 'auto');
        const ttlSeconds = parseInt(pa.sessionTtlSeconds || (12 * 60 * 60), 10) || (12 * 60 * 60);
        const ttlHours = Math.max(1, Math.round(ttlSeconds / 3600));
        const ttlEl = document.getElementById('setting-panel-session-ttl-hours');
        if (ttlEl) {
            const allowed = new Set(['1', '4', '12', '24', '72', '168']);
            ttlEl.value = allowed.has(String(ttlHours)) ? String(ttlHours) : '12';
        }
        const paStatus = document.getElementById('setting-panel-auth-status');
        if (paStatus) {
            paStatus.textContent = pa.configured
                ? (pa.enabled ? 'Protección activa: el panel requiere contraseña.' : 'Contraseña configurada, protección desactivada.')
                : 'No hay contraseña configurada para el panel.';
        }
        applyTheme(document.getElementById('setting-theme').value);
    } catch (err) {
        showToast('Error cargando settings', 'error');
    }
}

async function savePanelAccessSettings() {
    const enabled = !!document.getElementById('setting-panel-auth-enabled')?.checked;
    const currentPassword = document.getElementById('setting-panel-auth-current')?.value || '';
    const newPassword = document.getElementById('setting-panel-auth-new')?.value || '';
    const confirmPassword = document.getElementById('setting-panel-auth-confirm')?.value || '';
    const status = document.getElementById('setting-panel-auth-status');
    const btn = document.getElementById('btn-save-panel-auth');
    try {
        if (newPassword || confirmPassword) {
            if (newPassword !== confirmPassword) {
                throw new Error('La nueva contraseña y la confirmación no coinciden.');
            }
        }
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner"></span> Guardando...';
        }
        if (status) {
            status.textContent = 'Guardando configuración de acceso...';
            status.style.color = '';
        }
        const data = await API.savePanelAccess({
            enabled,
            currentPassword,
            newPassword,
        });
        const auth = data.auth || {};
        if (status) {
            status.textContent = auth.configured
                ? (auth.enabled ? 'Protección del panel activada.' : 'Protección del panel desactivada (contraseña conservada).')
                : 'No hay contraseña configurada.';
            status.style.color = 'var(--accent-green)';
        }
        try {
            const authData = await API.authStatus();
            if (typeof authState !== 'undefined') authState = authData.auth || authState;
            if (typeof updateAuthUIState === 'function') updateAuthUIState();
        } catch {}
        const currentEl = document.getElementById('setting-panel-auth-current');
        const newEl = document.getElementById('setting-panel-auth-new');
        const confEl = document.getElementById('setting-panel-auth-confirm');
        if (currentEl) currentEl.value = '';
        if (newEl) newEl.value = '';
        if (confEl) confEl.value = '';
        showToast('✅ Acceso del panel actualizado', 'success');
    } catch (err) {
        if (status) {
            status.textContent = 'Error: ' + (err.message || 'No se pudo guardar');
            status.style.color = 'var(--accent-red)';
        }
        showToast('❌ ' + (err.message || 'No se pudo guardar acceso del panel'), 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '🔐 Guardar contraseña del panel';
        }
    }
}

async function saveSettings(e) {
    e.preventDefault();
    try {
        const hostValue = (document.getElementById('setting-host')?.value || '').trim() || '127.0.0.1';
        const ttlHours = parseInt(document.getElementById('setting-panel-session-ttl-hours')?.value || '12', 10) || 12;
        const ttlSeconds = Math.max(1, ttlHours) * 3600;
        await API.updateSettings({
            host: hostValue,
            duplicacy_path: document.getElementById('setting-duplicacy-path').value,
            duplicacyPath: document.getElementById('setting-duplicacy-path').value,
            port: parseInt(document.getElementById('setting-port').value, 10),
            language: document.getElementById('setting-language').value,
            theme: document.getElementById('setting-theme').value,
            panelAccess: {
                cookieSecureMode: (document.getElementById('setting-panel-cookie-secure-mode')?.value || 'auto').trim() || 'auto',
                sessionTtlSeconds: ttlSeconds,
            },
            notifications: {
                healthchecks: {
                    enabled: !!document.getElementById('setting-hc-enabled')?.checked,
                    url: (document.getElementById('setting-hc-url')?.value || '').trim(),
                    successKeyword: (document.getElementById('setting-hc-keyword')?.value || 'success').trim() || 'success',
                    timeoutSeconds: parseInt(document.getElementById('setting-hc-timeout')?.value || '10', 10) || 10,
                    sendLog: !!document.getElementById('setting-hc-send-log')?.checked,
                },
                email: {
                    enabled: !!document.getElementById('setting-email-enabled')?.checked,
                    smtpHost: (document.getElementById('setting-email-smtp-host')?.value || '').trim(),
                    smtpPort: parseInt(document.getElementById('setting-email-smtp-port')?.value || '587', 10) || 587,
                    smtpStartTls: !!document.getElementById('setting-email-starttls')?.checked,
                    smtpUsername: (document.getElementById('setting-email-user')?.value || '').trim(),
                    smtpPassword: document.getElementById('setting-email-pass')?.value || '',
                    from: (document.getElementById('setting-email-from')?.value || '').trim(),
                    to: (document.getElementById('setting-email-to')?.value || '').trim(),
                    subjectPrefix: (document.getElementById('setting-email-subject-prefix')?.value || '[DupliManager]').trim() || '[DupliManager]',
                    sendLog: !!document.getElementById('setting-email-send-log')?.checked,
                }
            }
        });
        applyTheme(document.getElementById('setting-theme').value);
        showToast('✅ Configuración guardada (reinicia el servicio si cambiaste host/puerto)', 'success');
    } catch (err) {
        showToast('❌ Error guardando', 'error');
    }
}

function buildSettingsNotificationsPayloadFromUI() {
    return {
        healthchecks: {
            enabled: !!document.getElementById('setting-hc-enabled')?.checked,
            url: (document.getElementById('setting-hc-url')?.value || '').trim(),
            successKeyword: (document.getElementById('setting-hc-keyword')?.value || 'success').trim() || 'success',
            timeoutSeconds: parseInt(document.getElementById('setting-hc-timeout')?.value || '10', 10) || 10,
            sendLog: !!document.getElementById('setting-hc-send-log')?.checked,
        },
        email: {
            enabled: !!document.getElementById('setting-email-enabled')?.checked,
            smtpHost: (document.getElementById('setting-email-smtp-host')?.value || '').trim(),
            smtpPort: parseInt(document.getElementById('setting-email-smtp-port')?.value || '587', 10) || 587,
            smtpStartTls: !!document.getElementById('setting-email-starttls')?.checked,
            smtpUsername: (document.getElementById('setting-email-user')?.value || '').trim(),
            smtpPassword: document.getElementById('setting-email-pass')?.value || '',
            from: (document.getElementById('setting-email-from')?.value || '').trim(),
            to: (document.getElementById('setting-email-to')?.value || '').trim(),
            subjectPrefix: (document.getElementById('setting-email-subject-prefix')?.value || '[DupliManager]').trim() || '[DupliManager]',
            sendLog: !!document.getElementById('setting-email-send-log')?.checked,
        }
    };
}

async function testGlobalHealthchecksNotification() {
    const btn = document.getElementById('btn-test-hc-global');
    const status = document.getElementById('setting-hc-test-status');
    const keyword = (document.getElementById('setting-hc-keyword')?.value || 'success').trim() || 'success';
    try {
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner"></span> Probando...';
        }
        if (status) {
            status.textContent = `Probando HTTP POST a Healthchecks con keyword "${keyword}"...`;
            status.style.color = '';
        }
        await API.updateSettings({
            notifications: buildSettingsNotificationsPayloadFromUI(),
        });
        const result = await API.testNotificationChannels({ channel: 'healthchecks', keyword });
        const msg = result?.channels?.healthchecks?.ok ? 'Healthchecks OK' : 'Healthchecks probado';
        if (status) {
            status.textContent = `${msg} (keyword="${keyword}")`;
            status.style.color = 'var(--accent-green)';
        }
        showToast(`✅ ${msg}`, 'success');
    } catch (err) {
        if (status) {
            status.textContent = 'Error en prueba Healthchecks: ' + err.message;
            status.style.color = 'var(--accent-red)';
        }
        showToast('❌ Error probando Healthchecks: ' + err.message, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '🧪 Probar Healthchecks';
        }
    }
}

async function testGlobalEmailNotification() {
    const btn = document.getElementById('btn-test-email-global');
    const status = document.getElementById('setting-email-test-status');
    try {
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner"></span> Probando...';
        }
        if (status) {
            status.textContent = 'Probando envío por SMTP...';
            status.style.color = '';
        }
        await API.updateSettings({
            notifications: buildSettingsNotificationsPayloadFromUI(),
        });
        const result = await API.testNotificationChannels({ channel: 'email' });
        const msg = result?.channels?.email?.ok ? 'Email OK' : 'Email probado';
        if (status) {
            status.textContent = msg;
            status.style.color = 'var(--accent-green)';
        }
        showToast(`✅ ${msg}`, 'success');
    } catch (err) {
        if (status) {
            status.textContent = 'Error en prueba Email: ' + err.message;
            status.style.color = 'var(--accent-red)';
        }
        showToast('❌ Error probando Email: ' + err.message, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '🧪 Probar Email';
        }
    }
}

async function runSecretsMigration() {
    const btn = document.getElementById('btn-migrate-secrets');
    const status = document.getElementById('setting-secrets-migration-status');
    try {
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner"></span> Migrando...';
        }
        if (status) {
            status.textContent = 'Ejecutando migración de secretos...';
            status.style.color = '';
        }
        const result = await API.migrateSecrets();
        const msg = [
            `settings=${result.settingsSecretsMigrated || 0}`,
            `storages=${result.storagesRecordsMigrated || 0}`,
            `repos=${result.repositoriesRecordsMigrated || 0}`
        ].join(' · ');
        if (status) {
            status.textContent = result.changed
                ? `Migración completada. Registros actualizados: ${msg}`
                : `No había secretos legacy pendientes. (${msg})`;
            status.style.color = 'var(--accent-green)';
        }
        showToast(`✅ Migración de secretos completada (${msg})`, 'success');
    } catch (err) {
        if (status) {
            status.textContent = 'Error en migración de secretos: ' + (err.message || 'Error');
            status.style.color = 'var(--accent-red)';
        }
        showToast('❌ Error migrando secretos', 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '🔐 Migrar secretos legacy a DPAPI';
        }
    }
}

