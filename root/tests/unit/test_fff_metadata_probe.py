"""Unit tests for FanFicFare metadata-only probe in workers.fff_runner."""

import configparser
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from fanficfare import exceptions as fff_exceptions
import pytest

from calibre_integration.calibre_info import CalibreInfo
from models.fanfic_info import FanficInfo
from workers import fff_runner


def _make_cdb() -> MagicMock:
    cdb = MagicMock(spec=CalibreInfo)
    cdb.update_method = "update"
    cdb.default_ini = None
    cdb.personal_ini = None
    return cdb


def _make_fanfic(
    url: str = "https://www.fanfiction.net/s/12345/1/",
    site: str = "ffnet",
) -> FanficInfo:
    return FanficInfo(url=url, site=site)


def _make_story(
    metadata: dict[str, object], raw: dict[str, object] | None = None
) -> MagicMock:
    story = MagicMock()
    raw_map = raw if raw is not None else {}
    story.getMetadata.side_effect = lambda key: metadata.get(key)
    story.getMetadataRaw.side_effect = lambda key: raw_map.get(key)
    return story


def test_probe_story_metadata_success() -> None:
    cdb = _make_cdb()
    fanfic = _make_fanfic()

    config = configparser.RawConfigParser()
    config.add_section("overrides")

    story = _make_story(
        {
            "numChapters": "42",
            "dateUpdated": "2026-11-21",
            "status": "In-Progress",
            "title": "Wise as an Old Qrow",
        }
    )
    adapter = MagicMock()
    adapter.getStoryMetadataOnly.return_value = story

    with (
        patch.object(fff_runner.fff_cli, "get_configuration", return_value=config),
        patch.object(fff_runner.fff_adapters, "getAdapter", return_value=adapter),
        patch.object(fff_runner.impersonation, "install_impersonated_session"),
        patch.object(fff_runner.cookies, "get_site_cookiejar", return_value=None),
        patch.object(fff_runner.cookies, "set_site_cookiejar"),
    ):
        result = fff_runner.probe_story_metadata(cdb, fanfic)

    assert isinstance(result, fff_runner.MetadataProbeResult)
    assert result.num_chapters == 42
    assert result.date_updated == date(2026, 11, 21)
    assert result.status == "In-Progress"
    assert result.title == "Wise as an Old Qrow"
    assert result.story_deleted is False
    assert result.error is None
    assert result.exception is None
    assert result.has_error is False


def test_probe_story_metadata_story_does_not_exist() -> None:
    cdb = _make_cdb()
    fanfic = _make_fanfic()

    config = configparser.RawConfigParser()
    config.add_section("overrides")

    adapter = MagicMock()
    adapter.getStoryMetadataOnly.side_effect = fff_exceptions.StoryDoesNotExist(
        fanfic.url
    )

    with (
        patch.object(fff_runner.fff_cli, "get_configuration", return_value=config),
        patch.object(fff_runner.fff_adapters, "getAdapter", return_value=adapter),
        patch.object(fff_runner.impersonation, "install_impersonated_session"),
        patch.object(fff_runner.cookies, "get_site_cookiejar", return_value=None),
        patch.object(fff_runner.cookies, "set_site_cookiejar"),
    ):
        result = fff_runner.probe_story_metadata(cdb, fanfic)

    assert result.story_deleted is True
    assert result.error is not None and len(result.error) > 0
    assert result.has_error is True


def test_probe_story_metadata_transient_error() -> None:
    cdb = _make_cdb()
    fanfic = _make_fanfic()

    config = configparser.RawConfigParser()
    config.add_section("overrides")

    adapter = MagicMock()
    adapter.getStoryMetadataOnly.side_effect = RuntimeError("500 tab crashed")

    with (
        patch.object(fff_runner.fff_cli, "get_configuration", return_value=config),
        patch.object(fff_runner.fff_adapters, "getAdapter", return_value=adapter),
        patch.object(fff_runner.impersonation, "install_impersonated_session"),
        patch.object(fff_runner.cookies, "get_site_cookiejar", return_value=None),
        patch.object(fff_runner.cookies, "set_site_cookiejar"),
    ):
        result = fff_runner.probe_story_metadata(cdb, fanfic)

    assert result.story_deleted is False
    assert isinstance(result.exception, RuntimeError)
    assert result.error == "500 tab crashed"
    assert result.has_error is True


def test_probe_overrides_meta_from_last_chapter_false() -> None:
    cdb = _make_cdb()
    fanfic = _make_fanfic()

    config = configparser.RawConfigParser()
    captured_configs: list[configparser.RawConfigParser] = []

    story = _make_story(
        {
            "numChapters": "10",
            "dateUpdated": "2026-11-21",
            "status": "In-Progress",
            "title": "Test Story",
        }
    )
    adapter = MagicMock()
    adapter.getStoryMetadataOnly.return_value = story

    def _capture_adapter(conf: configparser.RawConfigParser, url: str) -> MagicMock:
        captured_configs.append(conf)
        return adapter

    with (
        patch.object(fff_runner.fff_cli, "get_configuration", return_value=config),
        patch.object(
            fff_runner.fff_adapters, "getAdapter", side_effect=_capture_adapter
        ),
        patch.object(fff_runner.impersonation, "install_impersonated_session"),
        patch.object(fff_runner.cookies, "get_site_cookiejar", return_value=None),
        patch.object(fff_runner.cookies, "set_site_cookiejar"),
    ):
        result = fff_runner.probe_story_metadata(cdb, fanfic)

    assert result.has_error is False
    assert len(captured_configs) == 1
    passed_conf = captured_configs[0]
    assert passed_conf.get("overrides", "meta_from_last_chapter") == "false"
    assert passed_conf.get("overrides", "check_next_chapter") == "false"


@pytest.mark.parametrize(
    ("raw_date", "expected"),
    [
        ("2026-11-21", date(2026, 11, 21)),
        ("2026/11/21", date(2026, 11, 21)),
        ("2026-11-21 14:30:00", date(2026, 11, 21)),
        (datetime(2026, 11, 21, 14, 30, 0), date(2026, 11, 21)),
        (date(2026, 11, 21), date(2026, 11, 21)),
    ],
)
def test_probe_parses_multiple_date_formats(raw_date: object, expected: date) -> None:
    cdb = _make_cdb()
    fanfic = _make_fanfic()

    config = configparser.RawConfigParser()
    config.add_section("overrides")

    story = _make_story(
        {
            "numChapters": "5",
            "dateUpdated": raw_date,
            "status": "In-Progress",
            "title": "Date Format Test",
        }
    )
    adapter = MagicMock()
    adapter.getStoryMetadataOnly.return_value = story

    with (
        patch.object(fff_runner.fff_cli, "get_configuration", return_value=config),
        patch.object(fff_runner.fff_adapters, "getAdapter", return_value=adapter),
        patch.object(fff_runner.impersonation, "install_impersonated_session"),
        patch.object(fff_runner.cookies, "get_site_cookiejar", return_value=None),
        patch.object(fff_runner.cookies, "set_site_cookiejar"),
    ):
        result = fff_runner.probe_story_metadata(cdb, fanfic)

    assert result.has_error is False
    assert result.date_updated == expected
