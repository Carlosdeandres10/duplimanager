/**
 * DupliManager API Client
 * Communicates with the backend REST API
 */
const API = {
    BASE: '/api',

    async _fetch(url, opts = {}) {
        const response = await fetch(`${this.BASE}${url}`, {
            headers: { 'Content-Type': 'application/json', ...opts.headers },
            ...opts
        });
        const data = await response.json();
        if (!data.ok) throw new Error(data.error || 'API Error');
        return data;
    },

    // ─── REPOS ──────────────────────────────────────────
    async getRepos() {
        return this._fetch('/repos');
    },

    async getRepo(id) {
        return this._fetch(`/repos/${id}`);
    },

    async createRepo(repoData) {
        return this._fetch('/repos', {
            method: 'POST',
            body: JSON.stringify(repoData)
        });
    },

    async deleteRepo(id) {
        return this._fetch(`/repos/${id}`, { method: 'DELETE' });
    },

    // ─── BACKUP ─────────────────────────────────────────
    async startBackup(repoId, password) {
        return this._fetch('/backup/start', {
            method: 'POST',
            body: JSON.stringify({ repoId, password })
        });
    },

    async getBackupStatus(repoId) {
        return this._fetch(`/backup/status/${repoId}`);
    },

    /**
     * Subscribe to backup progress via SSE
     */
    subscribeProgress(repoId, onMessage) {
        const evtSource = new EventSource(`${this.BASE}/backup/progress/${repoId}`);
        evtSource.onmessage = (e) => {
            const data = JSON.parse(e.data);
            onMessage(data);
            if (data.done) evtSource.close();
        };
        evtSource.onerror = () => {
            evtSource.close();
            onMessage({ done: true, error: true });
        };
        return evtSource;
    },

    // ─── SNAPSHOTS ──────────────────────────────────────
    async getSnapshots(repoId) {
        return this._fetch(`/snapshots/${repoId}`);
    },

    // ─── RESTORE ────────────────────────────────────────
    async restore(repoId, revision, overwrite, password) {
        return this._fetch('/restore', {
            method: 'POST',
            body: JSON.stringify({ repoId, revision, overwrite, password })
        });
    },

    // ─── CONFIG ─────────────────────────────────────────
    async getSettings() {
        return this._fetch('/config/settings');
    },

    async updateSettings(settings) {
        return this._fetch('/config/settings', {
            method: 'PUT',
            body: JSON.stringify(settings)
        });
    },

    async getLogFiles() {
        return this._fetch('/config/logs');
    },

    async readLogFile(filename) {
        return this._fetch(`/config/logs/${filename}`);
    },

    // ─── HEALTH ─────────────────────────────────────────
    async health() {
        return this._fetch('/health');
    }
};
