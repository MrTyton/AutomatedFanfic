"""Unit tests for FlareSolverr crash detection and session auto-recovery."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import json
import urllib.error


from utils import flaresolverr_utils


class TestFlareSolverrCrashDetection:
    """Tests for is_flaresolverr_crash helper."""

    def test_detects_tab_crashed_string(self):
        msg = "HTTP Error 500: Error solving the challenge. Message: tab crashed (Session info: chrome=133.0.6943.53)"
        assert flaresolverr_utils.is_flaresolverr_crash(msg) is True

    def test_detects_target_window_detached(self):
        msg = "Error: target window already detached"
        assert flaresolverr_utils.is_flaresolverr_crash(msg) is True

    def test_detects_detach_from_target(self):
        msg = "Protocol error: Target.detachFromTarget occurred"
        assert flaresolverr_utils.is_flaresolverr_crash(msg) is True

    def test_detects_from_exception_instance(self):
        exc = RuntimeError("Error solving the challenge. Message: tab crashed")
        assert flaresolverr_utils.is_flaresolverr_crash(exc) is True

    def test_returns_false_for_none(self):
        assert flaresolverr_utils.is_flaresolverr_crash(None) is False

    def test_returns_false_for_unrelated_error(self):
        assert flaresolverr_utils.is_flaresolverr_crash("404 Not Found") is False
        assert flaresolverr_utils.is_flaresolverr_crash("Connection refused") is False


class TestFlareSolverrConfigParsing:
    """Tests for discovering FlareSolverr configuration in personal.ini."""

    def test_parses_separate_address_port_and_session(self, tmp_path: Path):
        ini_content = """
[defaults]
slow_down_sleep_time: 10

[www.royalroad.com]
use_flaresolverr_proxy: true
flaresolverr_proxy_address: 192.168.1.161
flaresolverr_proxy_port: 8191
flaresolverr_proxy_protocol: http
use_flaresolverr_session: true
flaresolverr_session: FanFicFareSession_www_royalroad_com

[www.fanfiction.net]
use_flaresolverr_proxy: true
flaresolverr_proxy: http://10.0.0.5:8191/v1
flaresolverr_session: FanFicFareSession_www_fanfiction_net
"""
        ini_file = tmp_path / "personal.ini"
        ini_file.write_text(ini_content, encoding="utf-8")

        configs = flaresolverr_utils.get_flaresolverr_configs(ini_file)
        assert len(configs) == 2

        rr_cfg = next(c for c in configs if c.section == "www.royalroad.com")
        assert rr_cfg.endpoint == "http://192.168.1.161:8191/v1"
        assert rr_cfg.session == "FanFicFareSession_www_royalroad_com"

        ffn_cfg = next(c for c in configs if c.section == "www.fanfiction.net")
        assert ffn_cfg.endpoint == "http://10.0.0.5:8191/v1"
        assert ffn_cfg.session == "FanFicFareSession_www_fanfiction_net"

    def test_handles_nonexistent_or_empty_ini(self, tmp_path: Path):
        configs = flaresolverr_utils.get_flaresolverr_configs(tmp_path / "missing.ini")
        assert configs == []


class TestFlareSolverrApiOperations:
    """Tests for sessions.list and sessions.destroy commands."""

    @patch("urllib.request.urlopen")
    def test_list_sessions_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"status": "ok", "sessions": ["sess_rr", "sess_ffn"]}
        ).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        sessions = flaresolverr_utils.list_flaresolverr_sessions(
            "http://localhost:8191/v1"
        )
        assert sessions == ["sess_rr", "sess_ffn"]

    @patch("urllib.request.urlopen")
    def test_list_sessions_network_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        sessions = flaresolverr_utils.list_flaresolverr_sessions(
            "http://localhost:8191/v1"
        )
        assert sessions == []

    @patch("urllib.request.urlopen")
    def test_destroy_session_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"status": "ok", "message": "The session has been removed."}
        ).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        success = flaresolverr_utils.destroy_flaresolverr_session(
            "http://localhost:8191/v1", "sess_rr"
        )
        assert success is True

    @patch("urllib.request.urlopen")
    def test_destroy_session_failure(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("Timeout")
        success = flaresolverr_utils.destroy_flaresolverr_session(
            "http://localhost:8191/v1", "sess_rr"
        )
        assert success is False


class TestFlareSolverrRecovery:
    """Tests for recover_flaresolverr_crashes."""

    def test_recovers_matching_site_session(self, tmp_path: Path):
        ini_content = """
[www.royalroad.com]
use_flaresolverr_proxy: true
flaresolverr_proxy_address: 192.168.1.161
flaresolverr_proxy_port: 8191
flaresolverr_session: FanFicFareSession_www_royalroad_com
"""
        ini_file = tmp_path / "personal.ini"
        ini_file.write_text(ini_content, encoding="utf-8")

        with (
            patch.object(
                flaresolverr_utils,
                "list_flaresolverr_sessions",
                return_value=[
                    "FanFicFareSession_www_royalroad_com",
                    "FanFicFareSession_www_fanfiction_net",
                ],
            ),
            patch.object(
                flaresolverr_utils, "destroy_flaresolverr_session", return_value=True
            ) as mock_destroy,
        ):
            recovered = flaresolverr_utils.recover_flaresolverr_crashes(
                target_site="royalroad",
                personal_ini_path=ini_file,
            )
            assert recovered == 1
            mock_destroy.assert_called_once_with(
                "http://192.168.1.161:8191/v1",
                "FanFicFareSession_www_royalroad_com",
            )

    def test_recovers_all_sessions_when_no_target_site(self, tmp_path: Path):
        ini_content = """
[defaults]
flaresolverr_proxy: http://192.168.1.161:8191/v1
"""
        ini_file = tmp_path / "personal.ini"
        ini_file.write_text(ini_content, encoding="utf-8")

        with (
            patch.object(
                flaresolverr_utils,
                "list_flaresolverr_sessions",
                return_value=["sess_1", "sess_2"],
            ),
            patch.object(
                flaresolverr_utils, "destroy_flaresolverr_session", return_value=True
            ) as mock_destroy,
        ):
            recovered = flaresolverr_utils.recover_flaresolverr_crashes(
                target_site=None,
                personal_ini_path=ini_file,
            )
            assert recovered == 2
            assert mock_destroy.call_count == 2
