"""Tests for series/collection URL detection and expansion.

Tests verify that series_utils correctly identifies and expands series/collection
URLs using FanFicFare's native adapter methods without tautological assertions
or unexpected network calls on single-story URLs.
"""

from unittest.mock import patch
import pytest
from fanficfare import configurable
from fanficfare.adapters.base_adapter import BaseSiteAdapter

from utils import series_utils

_AO3_SERIES_HTML = """
<html>
<body>
  <div class="series-show">
    <h2 class="heading">Test Series Title</h2>
    <dl class="series meta group">
      <dt>Stats:</dt>
      <dd><dl class="stats"><dt class="words">Words:</dt><dd class="words">10,000</dd></dl></dd>
    </dl>
    <ul class="series work index group">
      <li id="work_1001" class="work blurb group">
        <div class="header module">
          <h4 class="heading"><a href="/works/1001">First Work</a></h4>
        </div>
      </li>
      <li id="work_1002" class="work blurb group">
        <div class="header module">
          <h4 class="heading"><a href="/works/1002">Second Work</a></h4>
        </div>
      </li>
    </ul>
  </div>
</body>
</html>
"""

_AO3_COLLECTION_HTML = """
<html>
<body>
  <div id="main">
    <a href="https://archiveofourown.org/works/2001">Collection Work 1</a>
    <a href="https://archiveofourown.org/works/2002">Collection Work 2</a>
  </div>
</body>
</html>
"""


class TestIsSeriesUrl:
    """Tests for is_series_url function."""

    def test_ao3_series_url_detection_with_and_without_scheme(self):
        """AO3 series URLs must return True both with and without https:// scheme."""
        with patch.object(
            BaseSiteAdapter,
            "get_request",
            side_effect=AssertionError(
                "AO3 series regex check must not make HTTP calls"
            ),
        ):
            assert (
                series_utils.is_series_url("https://archiveofourown.org/series/3039543")
                is True
            )
            assert (
                series_utils.is_series_url("archiveofourown.org/series/3039543") is True
            )
            assert (
                series_utils.is_series_url(
                    "https://archiveofourown.org/series/3039543/"
                )
                is True
            )

    @pytest.mark.parametrize(
        "url",
        [
            "https://archiveofourown.org/works/40707027",
            "archiveofourown.org/works/40707027",
            "https://archiveofourown.org/works/40707027/chapters/100001",
            "https://www.fanfiction.net/s/12345678/1/Story-Title",
            "www.fanfiction.net/s/12345678/1/",
            "https://www.fimfiction.net/story/123456/story-title",
            "https://www.royalroad.com/fiction/12345/story-title",
            "https://www.literotica.com/s/story-title",
        ],
    )
    def test_single_story_urls_return_false_without_network_calls(self, url):
        """Single story URLs across supported sites must return False with zero HTTP requests."""
        with patch.object(
            BaseSiteAdapter,
            "get_request",
            side_effect=AssertionError(
                f"Unexpected HTTP call for single-story URL {url}"
            ),
        ):
            assert series_utils.is_series_url(url) is False

    def test_unknown_site_returns_false(self):
        """Unknown sites default to False."""
        url = "https://example-unknown-site.com/story/123"
        assert series_utils.is_series_url(url) is False

    def test_with_custom_config(self):
        """Custom FanFicFare Configuration is respected."""
        url = "https://archiveofourown.org/series/3039543"
        custom_config = configurable.Configuration(
            ["test.com"], "EPUB", lightweight=True
        )
        assert series_utils.is_series_url(url, config=custom_config) is True

    def test_collection_url_via_get_urls_from_page_passes_geturls_helper(self):
        """Collection/list URLs using get_urls_from_page receive a real GetURLs helper."""
        url = "https://archiveofourown.org/collections/TestCollection2026/works"
        with patch.object(
            BaseSiteAdapter, "get_request", return_value=_AO3_COLLECTION_HTML
        ):
            assert series_utils.is_series_url(url) is True


class TestExpandSeriesUrl:
    """Tests for expand_series_url function."""

    def test_ao3_series_expansion_with_html_fixture(self):
        """Expanding an AO3 series URL parses real AO3 series HTML via FanFicFare adapter."""
        url = "https://archiveofourown.org/series/3039543"
        with patch.object(
            BaseSiteAdapter, "get_request", return_value=_AO3_SERIES_HTML
        ):
            result = series_utils.expand_series_url(url)

        assert result == [
            "https://archiveofourown.org/works/1001",
            "https://archiveofourown.org/works/1002",
        ]

    def test_ao3_series_expansion_schemeless_url(self):
        """Expanding a schemeless AO3 series URL normalizes scheme and extracts work URLs."""
        url = "archiveofourown.org/series/3039543"
        with patch.object(
            BaseSiteAdapter, "get_request", return_value=_AO3_SERIES_HTML
        ):
            result = series_utils.expand_series_url(url)

        assert result == [
            "https://archiveofourown.org/works/1001",
            "https://archiveofourown.org/works/1002",
        ]

    def test_single_story_returns_empty_without_network(self):
        """Single story URLs immediately return [] without making any network calls."""
        url = "https://archiveofourown.org/works/40707027"
        with patch.object(
            BaseSiteAdapter,
            "get_request",
            side_effect=AssertionError("Single story URL must not make network calls"),
        ):
            result = series_utils.expand_series_url(url)

        assert result == []

    def test_invalid_url_returns_empty(self):
        """Invalid/unknown URLs return empty list."""
        url = "https://example-invalid.com/story/123"
        assert series_utils.expand_series_url(url) == []

    def test_with_custom_config(self):
        """Custom config is passed through to expand_series_url."""
        url = "https://archiveofourown.org/series/3039543"
        custom_config = configurable.Configuration(
            ["test.com"], "EPUB", lightweight=True
        )
        with patch.object(
            BaseSiteAdapter, "get_request", return_value=_AO3_SERIES_HTML
        ):
            result = series_utils.expand_series_url(url, config=custom_config)

        assert result == [
            "https://archiveofourown.org/works/1001",
            "https://archiveofourown.org/works/1002",
        ]

    def test_collection_expansion_via_get_urls_from_page(self):
        """Collection URLs expand via get_urls_from_page using real GetURLs helper."""
        url = "https://archiveofourown.org/collections/TestCollection2026/works"
        with patch.object(
            BaseSiteAdapter, "get_request", return_value=_AO3_COLLECTION_HTML
        ):
            result = series_utils.expand_series_url(url)

        assert result == [
            "https://archiveofourown.org/works/2001",
            "https://archiveofourown.org/works/2002",
        ]


class TestProcessUrl:
    """Tests for process_url unified handler."""

    def test_series_url_processing(self):
        """Processing a series URL expands stories and sets is_series=True."""
        url = "https://archiveofourown.org/series/3039543"
        with patch.object(
            BaseSiteAdapter, "get_request", return_value=_AO3_SERIES_HTML
        ):
            result = series_utils.process_url(url)

        assert result == {
            "is_series": True,
            "urls": [
                "https://archiveofourown.org/works/1001",
                "https://archiveofourown.org/works/1002",
            ],
            "count": 2,
            "source_url": url,
        }

    def test_single_story_processing(self):
        """Processing a single story URL returns [url] with is_series=False and zero HTTP calls."""
        url = "https://archiveofourown.org/works/40707027"
        with patch.object(
            BaseSiteAdapter,
            "get_request",
            side_effect=AssertionError("Single story URL must not make network calls"),
        ):
            result = series_utils.process_url(url)

        assert result == {
            "is_series": False,
            "urls": [url],
            "count": 1,
            "source_url": url,
        }

    def test_result_structure(self):
        """Result dictionary has exact required keys and types."""
        url = "https://archiveofourown.org/works/40707027"
        result = series_utils.process_url(url)
        assert set(result.keys()) == {"is_series", "urls", "count", "source_url"}
        assert result["is_series"] is False
        assert result["urls"] == [url]
        assert result["count"] == 1
        assert result["source_url"] == url

    def test_graceful_error_handling(self):
        """Invalid URLs do not crash and fall back to treating input as single URL."""
        url = "not-a-valid-url"
        result = series_utils.process_url(url)
        assert result["is_series"] is False
        assert result["urls"] == [url]
        assert result["count"] == 1

    def test_tth_series_detection_and_expansion(self):
        """Twisting the Hellmouth Series-<id> URLs are detected without HTTP and expanded via get_series_from_page."""
        url = "https://www.tthfanfic.org/Series-2329"
        tth_html = """
        <html><head><title>TtH • Series • Test TtH Series</title></head>
        <body>
          <div class="storybody">Series description</div>
          <div class="storylistitem"><a class="storylink" href="/Story-111">One</a></div>
          <div class="storylistitem"><a class="storylink" href="/Story-222">Two</a></div>
        </body></html>
        """
        with patch.object(
            BaseSiteAdapter,
            "get_request",
            side_effect=AssertionError("TtH series detection must not make HTTP calls"),
        ):
            assert series_utils.is_series_url(url) is True

        with patch.object(BaseSiteAdapter, "get_request", return_value=tth_html):
            result = series_utils.process_url(url)

        assert result["is_series"] is True
        assert result["count"] == 2
        assert result["urls"] == [
            "https://www.tthfanfic.org/Story-111",
            "https://www.tthfanfic.org/Story-222",
        ]

    def test_efiction_series_detection_and_expansion(self):
        """eFiction viewseries.php?seriesid=<id> URLs are detected and expanded with GetURLs helper."""
        url = "https://www. fanfictalk.com/viewseries.php?seriesid=45".replace(" ", "")
        efiction_html = """
        <html><body>
          <div id="pagetitle">Series Title</div>
          <div class="summarytext">Summary</div>
          <a href="viewstory.php?sid=101">Story 101</a>
          <a href="viewstory.php?sid=102">Story 102</a>
        </body></html>
        """
        with patch.object(
            BaseSiteAdapter,
            "get_request",
            side_effect=AssertionError(
                "eFiction series detection must not make HTTP calls"
            ),
        ):
            assert series_utils.is_series_url(url) is True

        with patch.object(BaseSiteAdapter, "get_request", return_value=efiction_html):
            result = series_utils.process_url(url)

        assert result["is_series"] is True
        assert result["count"] == 2

    def test_collection_process_url_scrapes_page_only_once(self):
        """process_url on a collection URL must only scrape the collection page once (not twice)."""
        url = "https://archiveofourown.org/collections/TestCollection2026/works"
        with patch.object(
            BaseSiteAdapter, "get_request", return_value=_AO3_COLLECTION_HTML
        ) as mock_get_req:
            result = series_utils.process_url(url)

        assert result["is_series"] is True
        assert result["count"] == 2
        assert mock_get_req.call_count == 1

    def test_process_url_passes_page_cache_without_mutating_globals(self):
        """process_url uses an explicit _page_cache dict rather than mutating globals()['_call_get_urls_from_page']."""
        url = "https://archiveofourown.org/collections/TestCollection2026/works"
        orig_fn = series_utils._call_get_urls_from_page

        with patch.object(
            BaseSiteAdapter,
            "get_request",
            return_value=_AO3_COLLECTION_HTML,
        ) as mock_get_req:
            cache: dict = {}
            assert series_utils.is_series_url(url, _page_cache=cache) is True
            assert url in cache
            assert mock_get_req.call_count == 1
            expanded = series_utils.expand_series_url(url, _page_cache=cache)
            assert len(expanded) == 2
            # Because cache already held the page result, get_request was not called again
            assert mock_get_req.call_count == 1
            assert series_utils._call_get_urls_from_page is orig_fn


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_empty_url(self):
        """Empty URL returns safe non-series result."""
        result = series_utils.process_url("")
        assert result["is_series"] is False
        assert result["urls"] == [""]
        assert result["count"] == 1

    def test_none_url(self):
        """None URL is handled gracefully without crashing."""
        result = series_utils.process_url(None)
        assert result["is_series"] is False
        assert isinstance(result["urls"], list)

    def test_url_with_parameters(self):
        """Single-story URL with query parameters is still recognized as single story."""
        url = "https://archiveofourown.org/works/40707027?view_adult=true"
        with patch.object(
            BaseSiteAdapter,
            "get_request",
            side_effect=AssertionError(
                "Single story URL with query params must not make network calls"
            ),
        ):
            result = series_utils.process_url(url)

        assert result["is_series"] is False
        assert result["urls"] == [url]
        assert result["count"] == 1

    def test_url_normalization(self):
        """Series URL with trailing slash is recognized and expanded."""
        url = "https://archiveofourown.org/series/3039543/"
        with patch.object(
            BaseSiteAdapter, "get_request", return_value=_AO3_SERIES_HTML
        ):
            result = series_utils.process_url(url)

        assert result["is_series"] is True
        assert result["count"] == 2

    def test_get_series_configuration_loads_site_sections_and_ini_files(self, tmp_path):
        """get_series_configuration creates configuration with site sections and INI files via ConfigStore."""
        from config.config_store import ConfigStore

        ini_file = tmp_path / "personal.ini"
        ini_file.write_text(
            "[archiveofourown.org]\nusername=testuser\n", encoding="utf-8"
        )

        store = ConfigStore({})
        store.update("calibre.personal_ini", str(ini_file))
        config = series_utils.get_series_configuration(
            "https://archiveofourown.org/series/12345",
            config_store=store,
        )

        assert config.has_section("archiveofourown.org")
        assert config.get("archiveofourown.org", "username") == "testuser"

    def test_series_expansion_failure_returns_zero_count(self):
        """When series expansion encounters an HTTP error, it returns is_series=True and count=0."""
        url = "https://archiveofourown.org/series/12345"
        with patch.object(
            BaseSiteAdapter, "get_request", side_effect=Exception("403 Forbidden")
        ):
            result = series_utils.process_url(url)

        assert result["is_series"] is True
        assert result["urls"] == []
        assert result["count"] == 0
