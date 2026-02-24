/**
 * DupliManager API Client
 * Communicates with the backend REST API
 */
const API = {
    BASE: '/api',

    async _fetch(url, opts = {}) {
        const response = await fetch(`${this.BASE}${url}`, {
            headers: { 'Content-Type': 'application/json', ...opts.headers },
            cache: 'no-store',
            ...opts
        });
        let data = {};
        try {
            data = await response.json();
        } catch {
            data = {};
        }
        if (!response.ok || !data.ok) {
            throw new Error(data.detail || data.error || `HTTP ${response.status}`);
        }
        return data;
    },

    // ─── REPOS ──────────────────────────────────────────
    async getRepos() {
        return this._fetch('/repos');
    },

    async getRepo(id) {
        return this._fetch(`/repos/${id}`);
    },

    async updateRepo(id, patch) {
        return this._fetch(`/repos/${id}`, {
            method: 'PUT',
            body: JSON.stringify(patch)
        });
    },

    async testRepoNotifications(id, payload) {
        return this._fetch(`/repos/${id}/test-notifications`, {
            method: 'POST',
            body: JSON.stringify(payload || {})
        });
    },

    async createRepo(repoData) {
        return this._fetch('/repos', {
            method: 'POST',
            body: JSON.stringify(repoData)
        });
    },

    async validateRepo(repoData) {
        return this._fetch('/repos/validate', {
            method: 'POST',
            body: JSON.stringify(repoData)
        });
    },


    async deleteRepo(id) {
        return this._fetch(`/repos/${id}`, { method: 'DELETE' });
    },

    async getStorages() {
        return this._fetch('/storages');
    },

    async createStorage(payload) {
        return this._fetch('/storages', {
            method: 'POST',
            body: JSON.stringify(payload)
        });
    },

    async updateStorage(id, payload) {
        return this._fetch(`/storages/${id}`, {
            method: 'PUT',
            body: JSON.stringify(payload)
        });
    },

    async deleteStorage(id) {
        return this._fetch(`/storages/${id}`, { method: 'DELETE' });
    },

    async getStorageSnapshots(id) {
        return this._fetch(`/storages/${id}/snapshots`);
    },

    async getStorageSnapshotRevisions(storageId, snapshotId) {
        const q = new URLSearchParams({ snapshot_id: snapshotId });
        return this._fetch(`/storages/${storageId}/snapshot-revisions?${q.toString()}`);
    },

    async getStorageSnapshotFiles(storageId, snapshotId, revision) {
        const q = new URLSearchParams({ snapshot_id: snapshotId, revision: String(revision) });
        return this._fetch(`/storages/${storageId}/snapshot-files?${q.toString()}`);
    },

    async restoreFromStorage(storageId, payload) {
        return this._fetch(`/storages/${storageId}/restore`, {
            method: 'POST',
            body: JSON.stringify(payload)
        });
    },

    async pickFolder(start) {
        const params = new URLSearchParams();
        if (start) params.set('start', start);
        const qs = params.toString();
        return this._fetch(`/system/pick-folder${qs ? `?${qs}` : ''}`);
    },

    async listLocalItems(root, relative) {
        const params = new URLSearchParams();
        params.set('root', root);
        if (relative) params.set('relative', relative);
        return this._fetch(`/system/list-local-items?${params.toString()}`);
    },

    async testWasabiConnection(payload) {
        return this._fetch('/system/test-wasabi', {
            method: 'POST',
            body: JSON.stringify(payload)
        });
    },

    async testWasabiWrite(payload) {
        return this._fetch('/system/test-wasabi-write', {
            method: 'POST',
            body: JSON.stringify(payload)
        });
    },

    async detectWasabiSnapshots(payload) {
        return this._fetch('/system/detect-wasabi-snapshots', {
            method: 'POST',
            body: JSON.stringify(payload)
        });
    },

    async testNotificationChannels(payload) {
        return this._fetch('/system/test-notification-channels', {
            method: 'POST',
            body: JSON.stringify(payload || {})
        });
    },

    // ─── BACKUP ─────────────────────────────────────────
    async startBackup(repoId, password, threads) {
        return this._fetch('/backup/start', {
            method: 'POST',
            body: JSON.stringify({ repoId, password, threads })
        });
    },

    async cancelBackup(repoId) {
        return this._fetch('/backup/cancel', {
            method: 'POST',
            body: JSON.stringify({ repoId })
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

    async getSnapshotFiles(repoId, revision) {
        return this._fetch(`/snapshots/${repoId}/files?revision=${encodeURIComponent(revision)}`);
    },

    // ─── RESTORE ────────────────────────────────────────
    async restore(repoId, revision, overwrite, password, restorePath, patterns) {
        return this._fetch('/restore', {
            method: 'POST',
            body: JSON.stringify({ repoId, revision, overwrite, password, restorePath, patterns })
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

    async queryLogFile(filename, params = {}) {
        const q = new URLSearchParams();
        Object.entries(params || {}).forEach(([k, v]) => {
            if (v === undefined || v === null || v === '') return;
            q.set(k, String(v));
        });
        return this._fetch(`/config/logs/${encodeURIComponent(filename)}/query?${q.toString()}`);
    },

    getLogExportUrl(filename, params = {}) {
        const q = new URLSearchParams();
        Object.entries(params || {}).forEach(([k, v]) => {
            if (v === undefined || v === null || v === '') return;
            q.set(k, String(v));
        });
        return `${this.BASE}/config/logs/${encodeURIComponent(filename)}/export${q.toString() ? `?${q.toString()}` : ''}`;
    },

    // ─── HEALTH ─────────────────────────────────────────
    async health() {
        return this._fetch('/health');
    }
};
