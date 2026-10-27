import inspect
import io
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from fanficfare.cli import do_download, expandOptions, mkParser
import fanficfare.configurable as configurable

from calibre_integration.calibre_info import CalibreInfo
from models.fanfic_info import FanficInfo
from utils import anubis_solver
from utils.system_utils import get_packaged_defaults_ini_path
from workers import command
from workers.command import (
    _build_argv,
    _extract_output_filename_template,
    _resolve_fanficfare_user_agent,
    _resolve_target_url,
    _ThreadLocalStdout,
    execute_fanficfare_direct,
    FanFicFareResult,
)


class TestBuildArgv(unittest.TestCase):
    """Tests for _build_argv() — the argv builder used by execute_fanficfare_direct."""

    def setUp(self):
        self.mock_cdb = MagicMock(spec=CalibreInfo)
        self.mock_fanfic = MagicMock(spec=FanficInfo)
        self.mock_fanfic.behavior = None

    def test_update_method_update(self):
        self.mock_cdb.update_method = "update"
        argv = _build_argv(self.mock_cdb, self.mock_fanfic)
        self.assertIn("-u", argv)
        self.assertNotIn("-U", argv)
        self.assertNotIn("--force", argv)
        self.assertIn("--update-cover", argv)
        self.assertIn("--non-interactive", argv)

    def test_update_method_update_always(self):
        self.mock_cdb.update_method = "update_always"
        argv = _build_argv(self.mock_cdb, self.mock_fanfic)
        self.assertIn("-U", argv)
        self.assertNotIn("-u", argv)
        self.assertNotIn("--force", argv)

    def test_update_method_force(self):
        self.mock_cdb.update_method = "force"
        argv = _build_argv(self.mock_cdb, self.mock_fanfic)
        self.assertIn("-u", argv)
        self.assertIn("--force", argv)
        self.assertNotIn("-U", argv)

    def test_force_behavior_overrides_update(self):
        self.mock_cdb.update_method = "update"
        self.mock_fanfic.behavior = "force"
        argv = _build_argv(self.mock_cdb, self.mock_fanfic)
        self.assertIn("-u", argv)
        self.assertIn("--force", argv)

    def test_update_no_force_ignores_force_behavior(self):
        self.mock_cdb.update_method = "update_no_force"
        self.mock_fanfic.behavior = "force"
        argv = _build_argv(self.mock_cdb, self.mock_fanfic)
        self.assertIn("-u", argv)
        self.assertNotIn("--force", argv)
        self.assertNotIn("-U", argv)

    def test_force_behavior_overrides_update_always(self):
        self.mock_cdb.update_method = "update_always"
        self.mock_fanfic.behavior = "force"
        argv = _build_argv(self.mock_cdb, self.mock_fanfic)
        self.assertIn("-u", argv)
        self.assertIn("--force", argv)
        self.assertNotIn("-U", argv)

    @patch("workers.command.ff_logging.is_verbose", return_value=True)
    def test_verbose_adds_debug_flag(self, _mock):
        self.mock_cdb.update_method = "update"
        argv = _build_argv(self.mock_cdb, self.mock_fanfic)
        self.assertIn("--debug", argv)

    @patch("workers.command.ff_logging.is_verbose", return_value=False)
    def test_non_verbose_omits_debug_flag(self, _mock):
        self.mock_cdb.update_method = "update"
        argv = _build_argv(self.mock_cdb, self.mock_fanfic)
        self.assertNotIn("--debug", argv)

    def test_target_not_included(self):
        # Unlike construct_fanficfare_command, _build_argv must NOT include the URL
        self.mock_cdb.update_method = "update"
        argv = _build_argv(self.mock_cdb, self.mock_fanfic)
        self.assertNotIn("http://test.com/story", argv)


class TestBuildArgvWithRealFanFicFareParser(unittest.TestCase):
    """
    Integration-level tests for _build_argv().

    These tests feed _build_argv()'s output through the *real* FanFicFare
    option parser (mkParser + expandOptions) so that signature changes in
    FanFicFare internals are caught immediately rather than only at runtime.
    The tests that mock mkParser in TestExecuteFanficfareDirect would not
    catch a missing/renamed parameter — these tests will.
    """

    def setUp(self):
        self.mkParser = mkParser
        self.expandOptions = expandOptions
        self.mock_cdb = MagicMock(spec=CalibreInfo)
        self.mock_fanfic = MagicMock(spec=FanficInfo)
        self.mock_fanfic.behavior = None

    def _parse(self, update_method, behavior=None):
        """Helper: build argv, parse through real FFF, return options object."""
        self.mock_cdb.update_method = update_method
        self.mock_fanfic.behavior = behavior
        argv = _build_argv(self.mock_cdb, self.mock_fanfic)
        parser = self.mkParser(calibre=False)
        options, _ = parser.parse_args(argv)
        self.expandOptions(options)
        return options

    def test_mkparser_callable_with_calibre_false(self):
        """mkParser(calibre=False) must not raise — catches missing-arg regressions."""
        parser = self.mkParser(calibre=False)
        self.assertIsNotNone(parser)

    def test_update_sets_update_flag(self):
        options = self._parse("update")
        self.assertTrue(options.update)
        self.assertFalse(getattr(options, "updatealways", False))
        self.assertFalse(getattr(options, "force", False))

    def test_update_always_sets_updatealways_flag(self):
        options = self._parse("update_always")
        self.assertTrue(options.updatealways)
        # expandOptions sets update=True whenever updatealways=True
        self.assertTrue(options.update)

    def test_force_method_sets_force_flag(self):
        options = self._parse("force")
        self.assertTrue(options.update)
        self.assertTrue(options.force)

    def test_force_behavior_sets_force_flag(self):
        options = self._parse("update", behavior="force")
        self.assertTrue(options.update)
        self.assertTrue(options.force)

    def test_update_no_force_with_force_behavior_does_not_force(self):
        options = self._parse("update_no_force", behavior="force")
        self.assertTrue(options.update)
        self.assertFalse(getattr(options, "force", False))

    def test_update_cover_always_set(self):
        options = self._parse("update")
        self.assertTrue(options.updatecover)

    def test_non_interactive_always_set(self):
        options = self._parse("update")
        self.assertFalse(options.interactive)

    @patch("workers.command.ff_logging.is_verbose", return_value=True)
    def test_verbose_sets_debug_flag(self, _mock):
        options = self._parse("update")
        self.assertTrue(options.debug)

    @patch("workers.command.ff_logging.is_verbose", return_value=False)
    def test_non_verbose_omits_debug_flag(self, _mock):
        options = self._parse("update")
        self.assertFalse(options.debug)

    def test_do_download_has_expected_signature(self):
        """
        do_download must accept the exact kwargs we pass — catches FFF API changes.

        If FanFicFare renames or removes 'warn', 'fail', 'passed_defaultsini',
        or 'passed_personalini', this test will fail immediately rather than
        surfacing as a runtime error.

        FanFicFare >=4.62.2 wraps do_download with @do_cprofile, a profiling
        decorator that does NOT use functools.wraps.  inspect.signature() then
        sees (*args, **kwargs) on the wrapper.  We walk the closure chain to
        reach the underlying function before inspecting its parameters.
        """
        # Unwrap any profiling/decorator closures that hide the real signature.
        fn = do_download
        seen: set[int] = set()
        while fn.__closure__ and id(fn) not in seen:
            seen.add(id(fn))
            for cell in fn.__closure__:
                try:
                    inner = cell.cell_contents
                    if callable(inner) and inner is not fn:
                        sig = inspect.signature(inner)
                        # If the inner function has explicit params, use it.
                        if not all(
                            p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
                            for p in sig.parameters.values()
                        ):
                            fn = inner
                        break
                except ValueError:
                    pass
            else:
                break

        params = inspect.signature(fn).parameters
        for name in ("warn", "fail", "passed_defaultsini", "passed_personalini"):
            self.assertIn(
                name,
                params,
                f"do_download is missing expected parameter '{name}' — "
                f"update execute_fanficfare_direct() to match the new FFF API",
            )


class TestFanFicFareResult(unittest.TestCase):
    """Tests for the FanFicFareResult dataclass."""

    def test_no_failures(self):
        result = FanFicFareResult()
        self.assertFalse(result.has_failure)
        self.assertFalse(result.is_forceable)

    def test_failure_messages_detected(self):
        result = FanFicFareResult(failure_messages=["something broke"])
        self.assertTrue(result.has_failure)
        self.assertFalse(result.is_forceable)

    def test_exception_is_failure(self):
        result = FanFicFareResult(exception=RuntimeError("boom"))
        self.assertTrue(result.has_failure)

    def test_forceable_messages_detected(self):
        result = FanFicFareResult(forceable_messages=["chapter difference"])
        self.assertFalse(result.has_failure)
        self.assertTrue(result.is_forceable)


class TestThreadLocalStdout(unittest.TestCase):
    """Tests for _ThreadLocalStdout."""

    def setUp(self):
        self.real_stdout = io.StringIO()
        self.proxy = _ThreadLocalStdout(self.real_stdout)

    def test_write_passthrough_outside_capture(self):
        self.proxy.write("hello")
        self.assertEqual(self.real_stdout.getvalue(), "hello")

    def test_capture_intercepts_write(self):
        with self.proxy.capture() as buf:
            self.proxy.write("captured")
        self.assertEqual(buf.getvalue(), "captured")
        # Real stdout should NOT have received it
        self.assertEqual(self.real_stdout.getvalue(), "")

    def test_capture_restored_after_exit(self):
        with self.proxy.capture():
            pass
        self.proxy.write("after")
        self.assertEqual(self.real_stdout.getvalue(), "after")

    def test_threads_are_isolated(self):
        results = {}

        def worker(label, value):
            with self.proxy.capture() as buf:
                self.proxy.write(value)
                results[label] = buf.getvalue()

        t1 = threading.Thread(target=worker, args=("a", "aaa"))
        t2 = threading.Thread(target=worker, args=("b", "bbb"))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(results["a"], "aaa")
        self.assertEqual(results["b"], "bbb")

    def test_encoding_property(self):
        wrapped = MagicMock()
        wrapped.encoding = "utf-8"
        proxy = _ThreadLocalStdout(wrapped)
        self.assertEqual(proxy.encoding, "utf-8")

    def test_fileno_raises_when_wrapped_unsupported(self):
        wrapped = io.StringIO()
        proxy = _ThreadLocalStdout(wrapped)
        with self.assertRaises(io.UnsupportedOperation):
            proxy.fileno()


class TestExecuteFanficfareDirect(unittest.TestCase):
    """Tests for execute_fanficfare_direct()."""

    def setUp(self):
        self.mock_cdb = MagicMock(spec=CalibreInfo)
        self.mock_cdb.update_method = "update"
        self.mock_cdb.default_ini = None
        self.mock_cdb.personal_ini = None

        self.mock_fanfic = MagicMock(spec=FanficInfo)
        self.mock_fanfic.behavior = None
        self.mock_fanfic.site = "archiveofourown"
        if hasattr(command, "clear_site_cookiejars"):
            command.clear_site_cookiejars()

    def _run_direct(self, do_download_side_effect=None, temp_dir="/tmp/test"):
        """Helper: patch fanficfare internals and run execute_fanficfare_direct."""
        mock_options = MagicMock()
        mock_parser = MagicMock()
        mock_parser.parse_args.return_value = (mock_options, [])

        with (
            patch("workers.command.ff_logging.is_verbose", return_value=False),
            patch("fanficfare.cli.mkParser", return_value=mock_parser) as mock_mk,
            patch("fanficfare.cli.expandOptions"),
            patch("fanficfare.cli.do_download", side_effect=do_download_side_effect),
        ):
            result = execute_fanficfare_direct(
                self.mock_cdb, self.mock_fanfic, "http://example.com/story/1", temp_dir
            )
            mock_mk.assert_called_once_with(calibre=False)
            return result

    def test_success_returns_empty_result(self):
        result = self._run_direct()
        self.assertFalse(result.has_failure)
        self.assertFalse(result.is_forceable)

    def test_exception_sets_exception_field(self):
        result = self._run_direct(do_download_side_effect=RuntimeError("network error"))
        self.assertTrue(result.has_failure)
        self.assertIsInstance(result.exception, RuntimeError)

    def test_fail_callback_adds_failure_message(self):
        """do_download calling fail() should populate failure_messages."""

        def fake_do_download(path_or_url, options, **kwargs):
            kwargs["fail"]("StoryDoesNotExist")

        result = self._run_direct(do_download_side_effect=fake_do_download)
        self.assertTrue(result.has_failure)
        self.assertIn("StoryDoesNotExist", result.failure_messages)

    def test_warn_callback_forceable_message(self):
        """do_download calling warn() with a chapter-diff message → forceable."""

        def fake_do_download(path_or_url, options, **kwargs):
            kwargs["warn"]("story contains 5 chapters, more than source: 3.")

        result = self._run_direct(do_download_side_effect=fake_do_download)
        self.assertFalse(result.has_failure)
        self.assertTrue(result.is_forceable)

    def test_warn_callback_failure_message(self):
        """do_download calling warn() with a permanent-fail message → failure."""

        def fake_do_download(path_or_url, options, **kwargs):
            kwargs["warn"]("story already contains 5 chapters.")

        result = self._run_direct(do_download_side_effect=fake_do_download)
        self.assertTrue(result.has_failure)

    def test_silent_failure_via_stdout_capture(self):
        """A print() inside do_download with a failure string should be detected."""

        def fake_do_download(path_or_url, options, **kwargs):
            print("story already contains 5 chapters.")

        # Provide a fresh proxy for this test so sys.stdout state from other tests
        # doesn't interfere.  We patch both _ensure_tl_stdout and sys.stdout so the
        # print() call inside fake_do_download flows through the capture buffer.
        captured_base = io.StringIO()
        proxy = _ThreadLocalStdout(captured_base)

        with (
            patch("workers.command._ensure_tl_stdout", return_value=proxy),
            patch("sys.stdout", proxy),
        ):
            result = self._run_direct(do_download_side_effect=fake_do_download)
        self.assertTrue(result.has_failure)

    def test_cookiejar_persisted_and_reused_across_downloads_for_same_site(self):
        """options.cookiejar populated by do_download on first call is reused on subsequent calls for the same site."""
        fake_jar = object()
        observed_jars_before_download: list[object | None] = []

        def fake_do_download(path_or_url, options, **kwargs):
            observed_jars_before_download.append(vars(options).get("cookiejar"))
            if not hasattr(options, "cookiejar") or options.cookiejar is None:
                options.cookiejar = fake_jar

        with patch("fanficfare.cli.do_download", side_effect=fake_do_download):
            execute_fanficfare_direct(
                self.mock_cdb,
                self.mock_fanfic,
                "https://archiveofourown.org/works/1",
                "/tmp/test",
            )
            execute_fanficfare_direct(
                self.mock_cdb,
                self.mock_fanfic,
                "https://archiveofourown.org/works/2",
                "/tmp/test",
            )

        self.assertEqual(observed_jars_before_download, [None, fake_jar])

    def test_cookiejar_persisted_even_when_do_download_raises(self):
        """Cookies acquired during login before a mid-download failure (e.g. HTTP 525) are still preserved."""
        fake_jar = object()
        observed_jars_before_download: list[object | None] = []
        call_num = 0

        def fake_do_download(path_or_url, options, **kwargs):
            nonlocal call_num
            call_num += 1
            observed_jars_before_download.append(vars(options).get("cookiejar"))
            if call_num == 1:
                options.cookiejar = fake_jar
                raise RuntimeError("HTTP Error 525")

        with patch("fanficfare.cli.do_download", side_effect=fake_do_download):
            res1 = execute_fanficfare_direct(
                self.mock_cdb,
                self.mock_fanfic,
                "https://archiveofourown.org/works/1",
                "/tmp/test",
            )
            res2 = execute_fanficfare_direct(
                self.mock_cdb,
                self.mock_fanfic,
                "https://archiveofourown.org/works/2",
                "/tmp/test",
            )

        self.assertTrue(res1.has_failure)
        self.assertFalse(res2.has_failure)
        self.assertEqual(observed_jars_before_download, [None, fake_jar])

    def test_cookiejar_isolated_between_different_sites(self):
        """Cookiejars are stored per-site so AO3 cookies are not shared with unrelated sites."""
        ao3_jar = object()
        ffnet_fanfic = MagicMock(spec=FanficInfo)
        ffnet_fanfic.behavior = None
        ffnet_fanfic.site = "fanfiction"
        observed_jars: list[tuple[str, object | None]] = []

        def fake_do_download(path_or_url, options, **kwargs):
            site = (
                "archiveofourown" if "archiveofourown" in path_or_url else "fanfiction"
            )
            observed_jars.append((site, vars(options).get("cookiejar")))
            if site == "archiveofourown":
                options.cookiejar = ao3_jar

        with patch("fanficfare.cli.do_download", side_effect=fake_do_download):
            execute_fanficfare_direct(
                self.mock_cdb,
                self.mock_fanfic,
                "https://archiveofourown.org/works/1",
                "/tmp/test",
            )
            execute_fanficfare_direct(
                self.mock_cdb,
                ffnet_fanfic,
                "https://www.fanfiction.net/s/1",
                "/tmp/test",
            )

        self.assertEqual(
            observed_jars,
            [("archiveofourown", None), ("fanfiction", None)],
        )

    def test_cookiejar_invalidated_when_personal_ini_changes(self):
        """Modifying personal.ini (e.g. changing username/password) clears cached cookiejars."""
        jar1 = object()
        jar2 = object()
        observed_jars_before_download: list[object | None] = []
        call_num = 0

        def fake_do_download(path_or_url, options, **kwargs):
            nonlocal call_num
            call_num += 1
            observed_jars_before_download.append(vars(options).get("cookiejar"))
            if vars(options).get("cookiejar") is None:
                options.cookiejar = jar1 if call_num <= 2 else jar2

        with tempfile.TemporaryDirectory() as tmp_dir:
            personal_ini_path = os.path.join(tmp_dir, "personal.ini")
            with open(personal_ini_path, "w", encoding="utf-8") as fh:
                fh.write("[archiveofourown.org]\nusername: user1\npassword: pass1\n")

            self.mock_cdb.personal_ini = personal_ini_path

            with patch("fanficfare.cli.do_download", side_effect=fake_do_download):
                # Download 1 & 2 with user1 credentials -> jar1 created then reused
                execute_fanficfare_direct(
                    self.mock_cdb,
                    self.mock_fanfic,
                    "https://archiveofourown.org/works/1",
                    tmp_dir,
                )
                execute_fanficfare_direct(
                    self.mock_cdb,
                    self.mock_fanfic,
                    "https://archiveofourown.org/works/2",
                    tmp_dir,
                )

                # User updates personal.ini credentials
                with open(personal_ini_path, "w", encoding="utf-8") as fh:
                    fh.write(
                        "[archiveofourown.org]\nusername: user2_new\npassword: pass2_new\n"
                    )

                # Download 3 & 4 -> jar1 must be invalidated on Download 3, then jar2 reused on Download 4
                execute_fanficfare_direct(
                    self.mock_cdb,
                    self.mock_fanfic,
                    "https://archiveofourown.org/works/3",
                    tmp_dir,
                )
                execute_fanficfare_direct(
                    self.mock_cdb,
                    self.mock_fanfic,
                    "https://archiveofourown.org/works/4",
                    tmp_dir,
                )

        self.assertEqual(
            observed_jars_before_download,
            [None, jar1, None, jar2],
        )

    def test_execute_fanficfare_direct_calls_anubis_solver_for_protected_site(self):
        """When site is marked anubis-protected, ensure_anubis_session is called and injected into options.cookiejar."""
        self.mock_fanfic.site = "some_site"
        self.mock_fanfic.url = "https://example.com/fiction/74983"
        mock_options = MagicMock()
        mock_parser = MagicMock()
        mock_parser.parse_args.return_value = (mock_options, [])
        mock_jar = MagicMock()

        with (
            patch("workers.command.ff_logging.is_verbose", return_value=False),
            patch("fanficfare.cli.mkParser", return_value=mock_parser),
            patch("fanficfare.cli.expandOptions"),
            patch("fanficfare.cli.do_download"),
            patch("utils.anubis_solver.is_site_anubis_protected", return_value=True),
            patch(
                "utils.anubis_solver.ensure_anubis_session", return_value=mock_jar
            ) as mock_ensure,
        ):
            res = execute_fanficfare_direct(
                self.mock_cdb, self.mock_fanfic, self.mock_fanfic.url, "/tmp/test"
            )
            self.assertFalse(res.has_failure)
            mock_ensure.assert_called_once()
            self.assertEqual(mock_options.cookiejar, mock_jar)

    def test_execute_fanficfare_direct_reactive_retry_on_anubis_challenge(self):
        """When any site fails and reactive probe detects Anubis, it solves, marks site, and retries."""
        self.mock_fanfic.site = "scribblehub"
        self.mock_fanfic.url = "https://scribblehub.com/series/123"
        mock_options = MagicMock()
        mock_parser = MagicMock()
        mock_parser.parse_args.return_value = (mock_options, [])
        mock_solved_jar = MagicMock()

        call_count = 0

        def fake_download(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("'NoneType' object is not subscriptable")

        with (
            patch("workers.command.ff_logging.is_verbose", return_value=False),
            patch("fanficfare.cli.mkParser", return_value=mock_parser),
            patch("fanficfare.cli.expandOptions"),
            patch("fanficfare.cli.do_download", side_effect=fake_download),
            patch(
                "utils.anubis_solver.probe_and_solve_anubis",
                return_value=(True, mock_solved_jar),
            ) as mock_probe,
            patch("utils.anubis_solver.mark_site_anubis_protected") as mock_mark,
        ):
            res = execute_fanficfare_direct(
                self.mock_cdb, self.mock_fanfic, self.mock_fanfic.url, "/tmp/test"
            )
            self.assertFalse(res.has_failure)
            self.assertEqual(call_count, 2)
            mock_probe.assert_called_once()
            mock_mark.assert_called_once_with("scribblehub")
            self.assertEqual(mock_options.cookiejar, mock_solved_jar)

    def test_execute_fanficfare_direct_no_retry_when_not_anubis_challenge(self):
        """When download fails but probe detects no Anubis challenge, it does not retry."""
        self.mock_fanfic.site = "archiveofourown"
        self.mock_fanfic.url = "https://archiveofourown.org/works/1"
        mock_options = MagicMock()
        mock_parser = MagicMock()
        mock_parser.parse_args.return_value = (mock_options, [])

        call_count = 0

        def fake_download(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("404 Not Found")

        with (
            patch("workers.command.ff_logging.is_verbose", return_value=False),
            patch("fanficfare.cli.mkParser", return_value=mock_parser),
            patch("fanficfare.cli.expandOptions"),
            patch("fanficfare.cli.do_download", side_effect=fake_download),
            patch(
                "utils.anubis_solver.probe_and_solve_anubis",
                return_value=(False, MagicMock()),
            ) as mock_probe,
        ):
            res = execute_fanficfare_direct(
                self.mock_cdb, self.mock_fanfic, self.mock_fanfic.url, "/tmp/test"
            )
            self.assertTrue(res.has_failure)
            self.assertEqual(call_count, 1)
            mock_probe.assert_called_once()


class TestExtractOutputFilenameTemplate(unittest.TestCase):
    """Tests for _extract_output_filename_template()."""

    def test_empty_ini_returns_default(self):
        result = _extract_output_filename_template("")
        self.assertEqual(result, "${title}-${siteabbrev}_${storyId}.epub")

    def test_no_output_filename_returns_default(self):
        ini = "[defaults]\nsome_other_key: value\n"
        result = _extract_output_filename_template(ini)
        self.assertEqual(result, "${title}-${siteabbrev}_${storyId}.epub")

    def test_defaults_section_template_preserved(self):
        ini = "[defaults]\noutput_filename: ${title}-${author}_${storyId}.epub\n"
        result = _extract_output_filename_template(ini)
        self.assertEqual(result, "${title}-${author}_${storyId}.epub")

    def test_overrides_section_takes_priority_over_defaults(self):
        ini = (
            "[defaults]\noutput_filename: from_defaults.epub\n"
            "[overrides]\noutput_filename: from_overrides.epub\n"
        )
        result = _extract_output_filename_template(ini)
        self.assertEqual(result, "from_overrides.epub")

    def test_site_section_beats_defaults(self):
        ini = (
            "[defaults]\noutput_filename: from_defaults.epub\n"
            "[archiveofourown.org]\noutput_filename: from_site.epub\n"
        )
        result = _extract_output_filename_template(ini, site="archiveofourown")
        self.assertEqual(result, "from_site.epub")

    def test_overrides_beats_site_section(self):
        ini = (
            "[archiveofourown.org]\noutput_filename: from_site.epub\n"
            "[overrides]\noutput_filename: from_overrides.epub\n"
        )
        result = _extract_output_filename_template(ini, site="archiveofourown")
        self.assertEqual(result, "from_overrides.epub")

    def test_site_substring_matches_section_with_tld(self):
        ini = "[archiveofourown.org]\noutput_filename: site_specific.epub\n"
        result = _extract_output_filename_template(ini, site="archiveofourown")
        self.assertEqual(result, "site_specific.epub")

    def test_site_used_for_update_flow_file_path(self):
        # When path_or_url is a file path (update flow), site param still works
        ini = "[archiveofourown.org]\noutput_filename: site_specific.epub\n"
        result = _extract_output_filename_template(ini, site="archiveofourown")
        self.assertEqual(result, "site_specific.epub")

    def test_directory_prefix_stripped(self):
        ini = "[defaults]\noutput_filename: /some/path/${title}-${siteabbrev}_${storyId}.epub\n"
        result = _extract_output_filename_template(ini)
        self.assertEqual(result, "${title}-${siteabbrev}_${storyId}.epub")

    def test_relative_directory_prefix_stripped(self):
        ini = "[defaults]\noutput_filename: subdir/${title}.epub\n"
        result = _extract_output_filename_template(ini)
        self.assertEqual(result, "${title}.epub")

    def test_malformed_ini_returns_default(self):
        result = _extract_output_filename_template("not\x00valid\x00ini")
        self.assertEqual(result, "${title}-${siteabbrev}_${storyId}.epub")

    def test_duplicate_keys_and_sections_parsed_non_strict(self):
        """User personal.ini with duplicate keys or sections must not fall back to default template."""
        ini = (
            "[defaults]\n"
            "add_to_extra_valid_entries: custom1\n"
            "add_to_extra_valid_entries: custom2\n"
            "output_filename: ${title}_By_${author}_${storyId}.epub\n"
            "[archiveofourown.org]\n"
            "use_archiveofourown_gay: true\n"
            "[archiveofourown.org]\n"
            "output_filename: AO3_${title}_${storyId}.epub\n"
        )
        self.assertEqual(
            _extract_output_filename_template(ini, site="archiveofourown"),
            "AO3_${title}_${storyId}.epub",
        )
        self.assertEqual(
            _extract_output_filename_template(ini, site="fanfiction"),
            "${title}_By_${author}_${storyId}.epub",
        )

    def test_execute_fanficfare_direct_real_fff_config_forces_temp_dir(self):
        """Real FFF mkParser + expandOptions + Configuration resolves output_filename into temp_dir even when [archiveofourown.org] sets output_filename."""
        defaults_ini = get_packaged_defaults_ini_path()
        with tempfile.TemporaryDirectory() as tmp_dir:
            personal_ini = os.path.join(tmp_dir, "personal.ini")
            with open(personal_ini, "w", encoding="utf-8") as fh:
                fh.write(
                    "[archiveofourown.org]\n"
                    "output_filename: /wrong/dir/MyCustom_${title}_${storyId}.epub\n"
                )

            cdb = MagicMock(spec=CalibreInfo)
            cdb.update_method = "update"
            cdb.default_ini = defaults_ini
            cdb.personal_ini = personal_ini

            fanfic = FanficInfo(
                url="https://archiveofourown.org/works/12345",
                site="archiveofourown",
            )

            captured = {}

            def inspect_do_download(url, options, passed_personalini=None, **kwargs):
                cfg = configurable.Configuration(
                    ["archiveofourown.org"], "EPUB", lightweight=False
                )
                cfg.read([defaults_ini])
                if passed_personalini:
                    cfg.read_string(passed_personalini)
                captured["output_filename"] = cfg.getConfig("output_filename")

            out_dir = os.path.join(tmp_dir, "download_target")
            os.makedirs(out_dir, exist_ok=True)
            with patch("fanficfare.cli.do_download", side_effect=inspect_do_download):
                res = execute_fanficfare_direct(cdb, fanfic, fanfic.url, out_dir)

            self.assertFalse(res.has_failure)
            expected_prefix = (
                out_dir.replace("\\", "/") + "/MyCustom_${title}_${storyId}.epub"
            )
            self.assertEqual(captured["output_filename"], expected_prefix)


class TestResolveTargetUrl(unittest.TestCase):
    """Tests for _resolve_target_url."""

    def test_schemeless_fanfic_url_normalized(self):
        fanfic = FanficInfo(url="royalroad.com/fiction/129182", site="royalroad")
        url = _resolve_target_url(fanfic, "/tmp/story.epub", "")
        self.assertEqual(url, "https://royalroad.com/fiction/129182")

    def test_https_fanfic_url_preserved(self):
        fanfic = FanficInfo(
            url="https://royalroad.com/fiction/129182", site="royalroad"
        )
        url = _resolve_target_url(fanfic, "/tmp/story.epub", "")
        self.assertEqual(url, "https://royalroad.com/fiction/129182")

    def test_extract_url_from_captured_output_when_fanfic_url_empty(self):
        fanfic = FanficInfo(url="", site="royalroad")
        output = (
            "Updating /tmp/story.epub, URL: https://www.royalroad.com/fiction/129182"
        )
        url = _resolve_target_url(fanfic, "/tmp/story.epub", output)
        self.assertEqual(url, "https://www.royalroad.com/fiction/129182")

    def test_fallback_to_path_or_url_when_not_epub(self):
        fanfic = FanficInfo(url="", site="royalroad")
        url = _resolve_target_url(fanfic, "royalroad.com/fiction/129182", "")
        self.assertEqual(url, "https://royalroad.com/fiction/129182")

    def test_empty_when_no_url_available(self):
        fanfic = FanficInfo(url="", site="royalroad")
        url = _resolve_target_url(fanfic, "/tmp/story.epub", "")
        self.assertEqual(url, "")


class TestResolveFanficfareUserAgent(unittest.TestCase):
    """Tests for _resolve_fanficfare_user_agent."""

    def setUp(self):
        parser = mkParser(calibre=False)
        self.options, _ = parser.parse_args(["-u"])
        expandOptions(self.options)
        defaults_path = get_packaged_defaults_ini_path()
        self.defaults_ini = (
            Path(defaults_path).read_text(encoding="utf-8")
            if defaults_path and Path(defaults_path).is_file()
            else None
        )

    def test_site_specific_user_agent_used(self):
        personal = (
            f"[defaults]\nuser_agent: {anubis_solver.DEFAULT_USER_AGENT}\n\n"
            "[www.royalroad.com]\nuser_agent: CustomRRUA/1.0\n"
        )
        ua = _resolve_fanficfare_user_agent(
            "https://www.royalroad.com/fiction/129182",
            self.defaults_ini,
            personal,
            self.options,
        )
        self.assertEqual(ua, "CustomRRUA/1.0")

    def test_user_defaults_user_agent_overrides_fallback(self):
        personal = (
            f"[defaults]\nuser_agent: {anubis_solver.DEFAULT_USER_AGENT}\n\n"
            "[defaults]\nuser_agent: CustomDefaultUA/2.0\n"
        )
        ua = _resolve_fanficfare_user_agent(
            "https://www.royalroad.com/fiction/129182",
            self.defaults_ini,
            personal,
            self.options,
        )
        self.assertEqual(ua, "CustomDefaultUA/2.0")

    def test_unset_user_agent_falls_back_to_default_browser_ua(self):
        personal = (
            f"[defaults]\nuser_agent: {anubis_solver.DEFAULT_USER_AGENT}\n\n"
            "[defaults]\nis_adult: true\n[www.fanfiction.net]\nuser_agent: FFNetUA/3.0\n"
        )
        ua = _resolve_fanficfare_user_agent(
            "https://www.royalroad.com/fiction/129182",
            self.defaults_ini,
            personal,
            self.options,
        )
        self.assertEqual(ua, anubis_solver.DEFAULT_USER_AGENT)

    def test_empty_target_url_returns_default(self):
        ua = _resolve_fanficfare_user_agent(
            "",
            self.defaults_ini,
            "",
            self.options,
        )
        self.assertEqual(ua, anubis_solver.DEFAULT_USER_AGENT)


if __name__ == "__main__":
    unittest.main()
