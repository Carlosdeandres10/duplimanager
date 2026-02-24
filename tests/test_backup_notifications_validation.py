import unittest

from fastapi import HTTPException

from server_py.routers.backups import _validate_repo_notifications_on_save


class BackupNotificationValidationTests(unittest.TestCase):
    def test_all_disabled_is_valid(self):
        _validate_repo_notifications_on_save({
            "healthchecks": {"enabled": False, "url": "", "successKeyword": "", "sendLog": True},
            "email": {"enabled": False, "to": "", "subjectPrefix": "", "sendLog": True},
        })

    def test_healthchecks_enabled_requires_url(self):
        with self.assertRaises(HTTPException) as ctx:
            _validate_repo_notifications_on_save({
                "healthchecks": {"enabled": True, "url": "", "successKeyword": "success", "sendLog": True},
                "email": {"enabled": False, "to": "", "subjectPrefix": "", "sendLog": True},
            })
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("URL Healthchecks", str(ctx.exception.detail))

    def test_email_enabled_requires_destination(self):
        with self.assertRaises(HTTPException) as ctx:
            _validate_repo_notifications_on_save({
                "healthchecks": {"enabled": False, "url": "", "successKeyword": "success", "sendLog": True},
                "email": {"enabled": True, "to": "", "subjectPrefix": "pref", "sendLog": True},
            })
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Email destino", str(ctx.exception.detail))

    def test_any_enabled_requires_keyword(self):
        with self.assertRaises(HTTPException) as ctx:
            _validate_repo_notifications_on_save({
                "healthchecks": {"enabled": True, "url": "https://hc", "successKeyword": "", "sendLog": True},
                "email": {"enabled": False, "to": "", "subjectPrefix": "", "sendLog": True},
            })
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("palabra de éxito", str(ctx.exception.detail).lower())

    def test_valid_healthchecks_only_passes(self):
        _validate_repo_notifications_on_save({
            "healthchecks": {"enabled": True, "url": "https://hc", "successKeyword": "success", "sendLog": True},
            "email": {"enabled": False, "to": "", "subjectPrefix": "", "sendLog": True},
        })

    def test_valid_email_only_passes(self):
        _validate_repo_notifications_on_save({
            "healthchecks": {"enabled": False, "url": "", "successKeyword": "exito", "sendLog": False},
            "email": {"enabled": True, "to": "soporte@dominio.com", "subjectPrefix": "exito", "sendLog": False},
        })


if __name__ == "__main__":
    unittest.main()

