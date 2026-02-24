// ─── STATE ──────────────────────────────────────────────
let currentView = 'dashboard';
let repos = [];
let storages = [];
let selectedRepo = null;
let currentTheme = 'dark';
let restoreFileEntries = [];
let restoreFilteredEntries = [];
let restoreSelectedPatterns = new Set();
let restoreBrowserPath = '';
let restoreStorageSnapshotsCache = {};
let restoreRevisionsCache = {};
let restoreFilesCache = {};
let newRepoContentState = { rootPath: '', selection: [] };
let editRepoContentState = { rootPath: '', selection: [] };
let backupIdPickerItems = [];
let backupIdPickerSelected = '';
let currentBackupRunRepoId = null;
let currentBackupEventSource = null;
let contentSelectorSession = {
    target: null, // 'new' | 'edit'
    rootPath: '',
    currentPath: '',
    items: [],
    filteredItems: [],
    selected: new Set(),
};

