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
