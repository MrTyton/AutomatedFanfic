import unittest
from unittest.mock import MagicMock, patch
import io
import threading

from workers.command import (
    construct_fanficfare_command,
    _build_argv,
    _ThreadLocalStdout,
    FanFicFareResult,
    execute_fanficfare_direct,
)
from calibre_integration.calibre_info import CalibreInfo
from models.fanfic_info import FanficInfo


class TestConstructFanficfareCommand(unittest.TestCase):
    def setUp(self):
        self.mock_cdb = MagicMock(spec=CalibreInfo)
        self.mock_fanfic = MagicMock(spec=FanficInfo)
        self.path_or_url = "http://test.com/story"
        self.mock_fanfic.url = self.path_or_url
        self.mock_fanfic.site = "test_site"
        self.mock_fanfic.behavior = None

    def test_update_method_update(self):
        self.mock_cdb.update_method = "update"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        self.assertIn("-u", command)
        self.assertNotIn("-U", command)
        self.assertNotIn("--force", command)

    def test_update_method_update_always(self):
        self.mock_cdb.update_method = "update_always"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        self.assertIn("-U", command)
        self.assertNotIn("-u", command)
        self.assertNotIn("--force", command)

    def test_update_method_force(self):
        self.mock_cdb.update_method = "force"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        self.assertIn("-u", command)
        self.assertIn("--force", command)
        self.assertNotIn("-U", command)

    def test_fanfic_behavior_force_override(self):
        self.mock_cdb.update_method = "update"
        self.mock_fanfic.behavior = "force"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        self.assertIn("-u", command)
        self.assertIn("--force", command)
        self.assertNotIn("-U", command)

    def test_update_no_force_with_force_behavior(self):
        # With the new implementation, update_no_force ignores force requests
        # and always uses normal update behavior
        self.mock_cdb.update_method = "update_no_force"
        self.mock_fanfic.behavior = "force"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        # Should use -u instead of --force when update_no_force is set
        self.assertIn("-u", command)
        self.assertNotIn("-U", command)
        self.assertNotIn("--force", command)

    def test_update_no_force_without_force_behavior(self):
        self.mock_cdb.update_method = "update_no_force"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        self.assertIn("-u", command)
        self.assertNotIn("-U", command)
        self.assertNotIn("--force", command)

    def test_default_update_method_fallback(self):
        # Test that unrecognized update_method defaults to -u
        self.mock_cdb.update_method = "unknown_method"
        self.mock_fanfic.behavior = None
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        self.assertIn("-u", command)
        self.assertNotIn("-U", command)
        self.assertNotIn("--force", command)

    def test_none_behavior_with_various_update_methods(self):
        # Test None behavior with different update methods
        self.mock_fanfic.behavior = None

        # Test with update_always
        self.mock_cdb.update_method = "update_always"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        self.assertIn("-U", command)

        # Test with force
        self.mock_cdb.update_method = "force"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        self.assertIn("-u", command)
        self.assertIn("--force", command)

    def test_empty_string_behavior(self):
        # Test empty string behavior (should be treated as no force)
        self.mock_cdb.update_method = "update"
        self.mock_fanfic.behavior = ""
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        self.assertIn("-u", command)
        self.assertNotIn("--force", command)

    def test_command_structure(self):
        # Test that the command structure is correct
        self.mock_cdb.update_method = "update"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        # command should be a list
        self.assertIsInstance(command, list)
        self.assertIn("fanficfare.cli", command)  # It is "-m fanficfare.cli" split
        # Actually it is [sys.executable, "-m", "fanficfare.cli", ...]
        self.assertIn("fanficfare.cli", command)
        self.assertIn("--update-cover", command)
        self.assertIn("--non-interactive", command)
        self.assertIn(self.path_or_url, command)

    def test_force_behavior_precedence_over_update_always(self):
        # Test that force behavior overrides update_always method
        self.mock_cdb.update_method = "update_always"
        self.mock_fanfic.behavior = "force"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        self.assertIn("-u", command)
        self.assertIn("--force", command)
        self.assertNotIn("-U", command)

    def test_update_no_force_precedence_over_force_behavior(self):
        # Test that update_no_force method overrides force behavior
        self.mock_cdb.update_method = "update_no_force"
        self.mock_fanfic.behavior = "force"
        command = construct_fanficfare_command(
            self.mock_cdb, self.mock_fanfic, self.path_or_url
        )
        self.assertIn("-u", command)
        self.assertNotIn("--force", command)
        self.assertNotIn("-U", command)

    def test_case_sensitivity_of_behavior(self):
        # Test that behavior is case-sensitive (only "force" should trigger force)
        self.mock_cdb.update_method = "update"
        test_cases = ["Force", "FORCE", "force "]  # Various case variations
        for behavior in test_cases:
            with self.subTest(behavior=behavior):
                self.mock_fanfic.behavior = behavior
                command = construct_fanficfare_command(
                    self.mock_cdb, self.mock_fanfic, self.path_or_url
                )
                self.assertIn("-u", command)
                self.assertNotIn("--force", command)


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
        from fanficfare.cli import expandOptions, mkParser

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
        import inspect
        from fanficfare.cli import do_download

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

    def _run_direct(self, do_download_side_effect=None, temp_dir="/tmp/test"):
        """Helper: patch fanficfare internals and run execute_fanficfare_direct."""
        mock_options = MagicMock()
        mock_parser = MagicMock()
        mock_parser.parse_args.return_value = (mock_options, [])

        with patch("workers.command.ff_logging.is_verbose", return_value=False), patch(
            "fanficfare.cli.mkParser", return_value=mock_parser
        ) as mock_mk, patch("fanficfare.cli.expandOptions"), patch(
            "fanficfare.cli.do_download", side_effect=do_download_side_effect
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

        with patch("workers.command._ensure_tl_stdout", return_value=proxy), patch(
            "sys.stdout", proxy
        ):
            result = self._run_direct(do_download_side_effect=fake_do_download)
        self.assertTrue(result.has_failure)


if __name__ == "__main__":
    unittest.main()
