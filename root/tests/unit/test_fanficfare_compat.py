"""
FanFicFare API Compatibility Tests

These tests validate that the installed version of FanFicFare exposes the exact
API surfaces that AutomatedFanfic depends on. They run against the real library
with NO mocking, so any breaking upstream change causes an immediate, clear failure
before it can reach a Docker image.

When one of these tests fails after a FanFicFare update, the fix is either:
  1. Update AutomatedFanfic to use the new API (and update the assertion here), OR
  2. Pin FanFicFare to the last known-good version until the new API is understood.
"""

import unittest

import fanficfare.adapters as adapters
import fanficfare.configurable as configurable
import fanficfare.exceptions as exceptions
import fanficfare.geturls as geturls


class TestFanFicFareGeturlsAPI(unittest.TestCase):
    """Verify the fanficfare.geturls API contract."""

    def test_geturls_exposes_GetURLs_class(self):
        self.assertTrue(
            hasattr(geturls, "GetURLs"),
            "fanficfare.geturls must export a 'GetURLs' class",
        )
        self.assertTrue(
            isinstance(geturls.GetURLs, type),
            "geturls.GetURLs must be a class",
        )

    def test_GetURLs_is_instantiable_without_args(self):
        instance = geturls.GetURLs()
        self.assertIsNotNone(instance)

    def test_GetURLs_has_get_urls_from_imap(self):
        instance = geturls.GetURLs()
        self.assertTrue(
            hasattr(instance, "get_urls_from_imap"),
            "GetURLs instance must have a 'get_urls_from_imap' method",
        )
        self.assertTrue(
            callable(instance.get_urls_from_imap),
            "GetURLs.get_urls_from_imap must be callable",
        )

    def test_GetURLs_has_get_urls_from_html(self):
        instance = geturls.GetURLs()
        self.assertTrue(
            hasattr(instance, "get_urls_from_html"),
            "GetURLs instance must have a 'get_urls_from_html' method",
        )

    def test_GetURLs_has_get_urls_from_text(self):
        instance = geturls.GetURLs()
        self.assertTrue(
            hasattr(instance, "get_urls_from_text"),
            "GetURLs instance must have a 'get_urls_from_text' method",
        )


class TestFanFicFareAdaptersAPI(unittest.TestCase):
    """Verify the fanficfare.adapters API contract."""

    def test_adapters_has_getSiteExamples(self):
        self.assertTrue(
            hasattr(adapters, "getSiteExamples"),
            "fanficfare.adapters must export 'getSiteExamples'",
        )
        self.assertTrue(callable(adapters.getSiteExamples))

    def test_getSiteExamples_returns_non_empty(self):
        examples = adapters.getSiteExamples()
        self.assertIsNotNone(examples)
        self.assertGreater(
            len(examples), 0, "getSiteExamples() must return at least one site"
        )

    def test_adapters_has_getAdapter(self):
        self.assertTrue(
            hasattr(adapters, "getAdapter"),
            "fanficfare.adapters must export 'getAdapter'",
        )
        self.assertTrue(callable(adapters.getAdapter))


class TestFanFicFareConfigurableAPI(unittest.TestCase):
    """Verify the fanficfare.configurable API contract."""

    def test_configurable_has_Configuration_class(self):
        self.assertTrue(
            hasattr(configurable, "Configuration"),
            "fanficfare.configurable must export 'Configuration'",
        )
        self.assertTrue(isinstance(configurable.Configuration, type))

    def test_Configuration_instantiable_with_lightweight(self):
        """Configuration must accept the (sites, output_type, lightweight=True) signature."""
        config = configurable.Configuration(["test.com"], "EPUB", lightweight=True)
        self.assertIsNotNone(config)


class TestFanFicFareExceptionsAPI(unittest.TestCase):
    """Verify the fanficfare.exceptions API contract."""

    def test_exceptions_has_UnknownSite(self):
        self.assertTrue(
            hasattr(exceptions, "UnknownSite"),
            "fanficfare.exceptions must export 'UnknownSite'",
        )

    def test_UnknownSite_is_exception(self):
        self.assertTrue(
            issubclass(exceptions.UnknownSite, Exception),
            "exceptions.UnknownSite must be an Exception subclass",
        )

    def test_exceptions_has_FetchEmailFailed(self):
        self.assertTrue(
            hasattr(exceptions, "FetchEmailFailed"),
            "fanficfare.exceptions must export 'FetchEmailFailed'",
        )


class TestFanFicFareCliAndIntegrationAPI(unittest.TestCase):
    """Verify fanficfare.cli entry points and real GetURLs/Configuration integration."""

    def test_cli_exports_mkParser_expandOptions_do_download(self):
        import inspect
        import fanficfare.cli as fff_cli

        self.assertTrue(callable(getattr(fff_cli, "mkParser", None)))
        self.assertTrue(callable(getattr(fff_cli, "expandOptions", None)))
        self.assertTrue(callable(getattr(fff_cli, "do_download", None)))

        parser = fff_cli.mkParser(calibre=False)
        options, args = parser.parse_args(
            [
                "-u",
                "--update-cover",
                "--non-interactive",
                "https://archiveofourown.org/works/123",
            ]
        )
        fff_cli.expandOptions(options)
        self.assertEqual(args, ["https://archiveofourown.org/works/123"])

        target_fn = fff_cli.do_download
        closure = getattr(target_fn, "__closure__", None)
        if closure is not None:
            for cell in closure:
                if callable(cell.cell_contents):
                    target_fn = cell.cell_contents
                    break
        sig = inspect.signature(target_fn)
        for param in (
            "arg",
            "options",
            "passed_defaultsini",
            "passed_personalini",
            "warn",
            "fail",
        ):
            self.assertIn(
                param,
                sig.parameters,
                f"fanficfare.cli.do_download must accept '{param}' parameter",
            )

    def test_getAdapter_anyurl_false_rejects_series_and_accepts_single_story(self):
        config = configurable.Configuration(["test.com"], "EPUB", lightweight=True)
        adapter = adapters.getAdapter(
            config, "https://archiveofourown.org/works/12345", anyurl=False
        )
        self.assertEqual(adapter.story.getMetadata("storyId"), "12345")

        with self.assertRaises(Exception):
            adapters.getAdapter(
                config, "https://archiveofourown.org/series/12345", anyurl=False
            )

    def test_make_fff_get_configuration_with_real_GetURLs_html_extraction(self):
        """Real _make_fff_get_configuration + GetURLs extracts URLs from HTML without AttributeError."""
        from pathlib import Path
        from services.url_ingester import _make_fff_get_configuration

        defaults_ini = (
            Path(__file__).resolve().parents[2] / "config.default" / "defaults.ini"
        )
        get_config_fn = _make_fff_get_configuration(str(defaults_ini), "")
        initial_config = get_config_fn("test1.com")
        gu = geturls.GetURLs(config=initial_config, get_config=get_config_fn)

        html = (
            "<html><body>"
            '<a href="https://archiveofourown.org/works/987654">AO3 Work</a>'
            '<a href="https://www.fanfiction.net/s/11223344/1/Test">FFNet Work</a>'
            "</body></html>"
        )
        urls = gu.get_urls_from_html(html)
        self.assertIn("https://archiveofourown.org/works/987654", urls)
        self.assertTrue(any("fanfiction.net/s/11223344" in u for u in urls))
