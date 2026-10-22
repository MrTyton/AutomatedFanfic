"""Unit tests for URL normalization utilities."""

import unittest
from utils.url_utils import normalize_url


class TestUrlUtils(unittest.TestCase):
    """Test suite for url_utils functions."""

    def test_normalize_url_prepends_https(self):
        """Schemeless URLs should get https:// prepended."""
        self.assertEqual(
            normalize_url("scribblehub.com/series/12345"),
            "https://scribblehub.com/series/12345",
        )

    def test_normalize_url_preserves_https(self):
        """HTTPS URLs should be preserved."""
        self.assertEqual(
            normalize_url("https://scribblehub.com/series/12345"),
            "https://scribblehub.com/series/12345",
        )

    def test_normalize_url_preserves_http(self):
        """HTTP URLs should be preserved."""
        self.assertEqual(
            normalize_url("http://scribblehub.com/series/12345"),
            "http://scribblehub.com/series/12345",
        )

    def test_normalize_url_strips_whitespace(self):
        """Whitespace should be trimmed before scheme checking."""
        self.assertEqual(
            normalize_url("  scribblehub.com/series/12345 \n"),
            "https://scribblehub.com/series/12345",
        )

    def test_normalize_url_handles_empty(self):
        """Empty or whitespace-only strings should return empty string."""
        self.assertEqual(normalize_url(""), "")
        self.assertEqual(normalize_url("   "), "")


if __name__ == "__main__":
    unittest.main()
