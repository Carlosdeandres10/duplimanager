import unittest
import sys
from unittest.mock import patch, MagicMock
from server_py.services.panel_auth import get_login_lockout_status, register_login_failure, clear_login_failures, should_use_secure_cookie

class TestSecurityCore(unittest.TestCase):

    def setUp(self):
        clear_login_failures("mock-ip")

    def test_rate_limit_lockout(self):
        # 5 fallos = bloqueo
        ip = "mock-ip"
        for _ in range(4):
            status = register_login_failure(ip)
            self.assertFalse(status.get("blocked"))
        
        # El 5to falla y bloquea
        status = register_login_failure(ip)
        self.assertTrue(status.get("blocked"))
        self.assertGreater(status.get("retryAfterSeconds"), 0)
        
        lockout = get_login_lockout_status(ip)
        self.assertFalse(lockout.get("allowed"))

    @patch("server_py.services.panel_auth._read_panel_access_cfg")
    def test_cookie_secure_mode_always(self, mock_read_cfg):
        mock_read_cfg.return_value = {"cookieSecureMode": "always"}
        self.assertTrue(should_use_secure_cookie(request_scheme="http", x_forwarded_proto=None))

    @patch("server_py.services.panel_auth._read_panel_access_cfg")
    def test_cookie_secure_mode_never(self, mock_read_cfg):
        mock_read_cfg.return_value = {"cookieSecureMode": "never"}
        self.assertFalse(should_use_secure_cookie(request_scheme="https", x_forwarded_proto="https"))

    @patch("server_py.services.panel_auth._read_panel_access_cfg")
    def test_cookie_secure_mode_auto(self, mock_read_cfg):
        mock_read_cfg.return_value = {"cookieSecureMode": "auto"}
        self.assertTrue(should_use_secure_cookie(request_scheme="https", x_forwarded_proto=None))
        self.assertTrue(should_use_secure_cookie(request_scheme="http", x_forwarded_proto="https"))
        self.assertFalse(should_use_secure_cookie(request_scheme="http", x_forwarded_proto="http"))

if __name__ == "__main__":
    unittest.main()
