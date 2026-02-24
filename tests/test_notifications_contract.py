import unittest

from server_py.services.notifications import (
    _merge_repo_notification_overrides,
    _build_backup_report_text,
    _sanitize_text_for_keyword,
)


class NotificationsContractTests(unittest.TestCase):
    def test_global_config_does_not_enable_channels(self):
        global_cfg = {
            "healthchecks": {"enabled": True, "url": "https://hc", "successKeyword": "success", "sendLog": True},
            "email": {"enabled": True, "smtpHost": "smtp.local", "to": "a@b.com", "subjectPrefix": "[X]", "sendLog": True},
        }
        merged = _merge_repo_notification_overrides(global_cfg, {})
        self.assertFalse(merged["healthchecks"]["enabled"])
        self.assertFalse(merged["email"]["enabled"])
        # Defaults/global values still available
        self.assertEqual(merged["healthchecks"]["url"], "https://hc")
        self.assertEqual(merged["email"]["smtpHost"], "smtp.local")

    def test_repo_overrides_enable_specific_channel_only(self):
        global_cfg = {
            "healthchecks": {"enabled": False, "url": "https://hc", "successKeyword": "success", "sendLog": True},
            "email": {"enabled": False, "smtpHost": "smtp.local", "to": "global@x.com", "subjectPrefix": "[X]", "sendLog": True},
        }
        repo_cfg = {
            "healthchecks": {"enabled": True, "url": "https://hc-backup", "successKeyword": "ok", "sendLog": False},
            "email": {"enabled": False, "to": "backup@x.com", "subjectPrefix": "PRUEBA", "sendLog": False},
        }
        merged = _merge_repo_notification_overrides(global_cfg, repo_cfg)
        self.assertTrue(merged["healthchecks"]["enabled"])
        self.assertEqual(merged["healthchecks"]["url"], "https://hc-backup")
        self.assertEqual(merged["healthchecks"]["successKeyword"], "ok")
        self.assertFalse(merged["healthchecks"]["sendLog"])
        self.assertFalse(merged["email"]["enabled"])
        # SMTP should remain global while recipient/prefix may override
        self.assertEqual(merged["email"]["smtpHost"], "smtp.local")
        self.assertEqual(merged["email"]["to"], "backup@x.com")
        self.assertEqual(merged["email"]["subjectPrefix"], "PRUEBA")

    def test_build_report_uses_only_configured_signal_keyword(self):
        payload = {
            "repoName": "demo",
            "snapshotId": "snap1",
            "trigger": "manual",
            "sourcePath": "C:/data",
            "targetLabel": "wasabi://demo",
            "finishedAt": "2026-02-24T00:00:00",
            "durationSeconds": 1,
            "backupSummary": {"ok": True, "message": "Prueba"},
            "backupLog": "Linea de log",
        }
        report = _build_backup_report_text(payload, include_log=True, max_log_chars=1000, signal_keyword="error")
        self.assertTrue(report.startswith("error\n"))
        # The generator itself should not inject "success" fixed anymore.
        self.assertNotIn("\nsuccess\n", report.lower())

    def test_sanitize_text_for_keyword_removes_success_when_keyword_is_not_success(self):
        raw = "error\nsuccess\nSubject success\nTodo OK"
        sanitized = _sanitize_text_for_keyword(raw, "error")
        self.assertIn("error", sanitized.lower())
        self.assertNotIn("success", sanitized.lower())

    def test_sanitize_text_keeps_success_when_keyword_success(self):
        raw = "success\nBackup success done"
        sanitized = _sanitize_text_for_keyword(raw, "success")
        self.assertEqual(raw, sanitized)


if __name__ == "__main__":
    unittest.main()

