/**
 * DupliManager — Main SPA Application
 * Handles routing, view management, and UI orchestration
 */

// ─── INIT ───────────────────────────────────────────────
let appBootstrapped = false;
let authState = { requiresAuth: false, authenticated: true, enabled: false, configured: false };

document.addEventListener('DOMContentLoaded', async () => {
    initTheme();
    initAuthUI();
    await bootApplication();
});

async function bootApplication() {
    try {
        const data = await API.authStatus();
        authState = data.auth || { requiresAuth: false, authenticated: true };
    } catch {
        authState = { requiresAuth: false, authenticated: true };
    }

    if (authState.requiresAuth && !authState.authenticated) {
        showAuthOverlay();
        updateAuthUIState();
        return;
    }
    hideAuthOverlay();
    startAppUI();
    updateAuthUIState();
}

function startAppUI() {
    if (appBootstrapped) return;
    appBootstrapped = true;
    initNavigation();
    navigateTo('dashboard');
    checkServerHealth();
}

function initTheme() {
    const stored = localStorage.getItem('duplimanager_theme');
    applyTheme(stored || 'dark');
}

function applyTheme(theme) {
    currentTheme = (theme === 'light') ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', currentTheme);
    document.body.setAttribute('data-theme', currentTheme);
    localStorage.setItem('duplimanager_theme', currentTheme);
}

function previewThemeFromSettings() {
    const select = document.getElementById('setting-theme');
    if (!select) return;
    applyTheme(select.value);
}

// ─── NAVIGATION ─────────────────────────────────────────
function initNavigation() {
    document.querySelectorAll('.nav-item[data-view]').forEach(item => {
        item.addEventListener('click', () => {
            navigateTo(item.dataset.view);
        });
    });
}

function initAuthUI() {
    const form = document.getElementById('auth-login-form');
    if (form && !form.dataset.bound) {
        form.addEventListener('submit', submitLogin);
        form.dataset.bound = '1';
    }
    const logoutBtn = document.getElementById('btn-panel-logout');
    if (logoutBtn && !logoutBtn.dataset.bound) {
        logoutBtn.addEventListener('click', logoutPanelSession);
        logoutBtn.dataset.bound = '1';
    }
    window.handleAuthRequired = () => {
        authState.requiresAuth = true;
        authState.authenticated = false;
        showAuthOverlay();
        updateAuthUIState();
    };
}

function showAuthOverlay() {
    const overlay = document.getElementById('auth-overlay');
    if (!overlay) return;
    overlay.classList.add('active');
    document.body.classList.add('auth-locked');
    const input = document.getElementById('auth-login-password');
    setTimeout(() => input?.focus(), 20);
}

function hideAuthOverlay() {
    const overlay = document.getElementById('auth-overlay');
    if (!overlay) return;
    overlay.classList.remove('active');
    document.body.classList.remove('auth-locked');
}

function updateAuthUIState() {
    const logoutWrap = document.getElementById('panel-logout-wrap');
    if (logoutWrap) {
        logoutWrap.style.display = (authState.requiresAuth && authState.authenticated) ? 'block' : 'none';
    }
    const authBadge = document.getElementById('auth-status-badge');
    if (authBadge) {
        if (authState.requiresAuth && authState.authenticated) {
            authBadge.textContent = '🔒 Panel protegido';
        } else if (authState.requiresAuth) {
            authBadge.textContent = '🔐 Acceso requerido';
        } else {
            authBadge.textContent = '🔓 Sin contraseña';
        }
    }
}

async function submitLogin(e) {
    e.preventDefault();
    const input = document.getElementById('auth-login-password');
    const status = document.getElementById('auth-login-status');
    const btn = document.getElementById('btn-auth-login');
    const password = input?.value || '';
    try {
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Entrando...';
        }
        if (status) status.textContent = 'Validando contraseña...';
        const data = await API.authLogin(password);
        authState = data.auth || { requiresAuth: false, authenticated: true };
        if (input) input.value = '';
        if (status) status.textContent = '';
        hideAuthOverlay();
        startAppUI();
        if (currentView === 'dashboard') {
            navigateTo('dashboard');
        }
        updateAuthUIState();
        showToast('✅ Acceso concedido', 'success');
    } catch (err) {
        if (status) status.textContent = err.message || 'Contraseña incorrecta';
        showToast('❌ ' + (err.message || 'Contraseña incorrecta'), 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Entrar';
        }
    }
}

async function logoutPanelSession() {
    try {
        await API.authLogout();
    } catch {}
    authState.requiresAuth = true;
    authState.authenticated = false;
    showAuthOverlay();
    updateAuthUIState();
}

function navigateTo(view) {
    currentView = view;

    // Update nav active state
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    const activeNav = document.querySelector(`.nav-item[data-view="${view}"]`);
    if (activeNav) activeNav.classList.add('active');

    // Show/hide views
    document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
    const viewEl = document.getElementById(`view-${view}`);
    if (viewEl) viewEl.classList.add('active');

    // Load view data
    switch (view) {
        case 'dashboard':  loadDashboard(); break;
        case 'storages':   loadStoragesView(); break;
        case 'repositories': loadRepositoriesView(); break;
        case 'tasks':      loadTasksView(); break;
        case 'backup':     loadBackupView(); break;
        case 'restore':    loadRestoreView(); break;
        case 'settings':   loadSettingsView(); break;
        case 'logs':       loadLogsView(); break;
    }
}

// ─── SERVER HEALTH ──────────────────────────────────────
async function checkServerHealth() {
    try {
        const data = await API.health();
        const indicator = document.getElementById('server-status');
        if (indicator) {
            indicator.innerHTML = `<span class="badge badge-success">🟢 Servidor activo</span>`;
        }
    } catch {
        const indicator = document.getElementById('server-status');
        if (indicator) {
            indicator.innerHTML = `<span class="badge badge-error">🔴 Servidor offline</span>`;
        }
    }
}

