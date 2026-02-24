/**
 * DupliManager — Main SPA Application
 * Handles routing, view management, and UI orchestration
 */

// ─── INIT ───────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initNavigation();
    navigateTo('dashboard');
    checkServerHealth();
});

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

