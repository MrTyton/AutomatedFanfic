"""Unit tests for bulk Calibre story listing and query/date helpers."""

from datetime import date, datetime, timezone
import json
from typing import Any
from unittest.mock import MagicMock, patch

import requests

from calibre_integration.calibre_info import CalibreInfo
from calibre_integration.calibredb_utils import CalibreDBClient
from calibre_integration.client_interface import (
    build_site_poll_query,
    parse_calibre_update_date,
)
from calibre_integration.http_client import CalibreHttpClient
from calibre_integration.models import CalibreStorySummary
from config.store import ConfigStore


def _make_mock_info(
    location: str = "http://calibre.local:8080/#Fanfic",
) -> MagicMock:
    info = MagicMock(spec=CalibreInfo)
    info.location = location
    info.username = None
    info.password = None
    info.lock = MagicMock()
    info.lock.__enter__ = MagicMock(return_value=None)
    info.lock.__exit__ = MagicMock(return_value=None)
    info.update_from_config_store.return_value = False
    info.to_args.return_value = ["--with-library", "/library"]
    return info


def _make_response(
    status_code: int = 200,
    json_data: Any = None,
) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.headers = {}
    raw = json.dumps(json_data).encode("utf-8")
    resp.content = raw
    resp.text = raw.decode("utf-8")
    resp.json.side_effect = lambda **kw: json.loads(resp.text, **kw)
    return resp


def test_parse_calibre_update_date_exact_tag() -> None:
    parsed_date, exact = parse_calibre_update_date(
        ["Last Update: 2026/11/21", "In-Progress"],
        datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc),
    )
    assert parsed_date == date(2026, 11, 21)
    assert exact is True


def test_parse_calibre_update_date_year_month_fallback() -> None:
    parsed_date, exact = parse_calibre_update_date(
        ["Last Update Year/Month: 2026/11", "In-Progress"],
        datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc),
    )
    assert parsed_date == date(2026, 11, 1)
    assert exact is False


def test_parse_calibre_update_date_last_modified_fallback() -> None:
    lm = datetime(2026, 10, 15, 8, 30, tzinfo=timezone.utc)
    parsed_date, exact = parse_calibre_update_date(["In-Progress"], lm)
    assert parsed_date == date(2026, 10, 15)
    assert exact is False

    none_date, none_exact = parse_calibre_update_date(["In-Progress"], None)
    assert none_date is None
    assert none_exact is False


def test_build_site_poll_query() -> None:
    query = build_site_poll_query(
        site_domain="fanfiction.net",
        include_tags=["In-Progress"],
        exclude_tags=["Completed"],
    )
    assert (
        query
        == 'identifiers:"fanfiction.net" and tags:"=In-Progress" and not tags:"=Completed"'
    )

    override_query = build_site_poll_query(
        site_domain="fanfiction.net",
        include_tags=["In-Progress"],
        exclude_tags=["Completed"],
        override='tags:"=Custom" and identifiers:"ffn"',
    )
    assert override_query == 'tags:"=Custom" and identifiers:"ffn"'


def test_http_client_list_stories_batches_and_skips_missing_url() -> None:
    info = _make_mock_info("http://calibre.local:8080/#Fanfic")
    client = CalibreHttpClient(info, MagicMock(spec=ConfigStore))

    # Case 1: 3 IDs returned — 1 missing url, 1 blank/invalid url, 1 valid
    search_resp = _make_response(json_data={"result": [101, 102, 103]})
    books_resp = _make_response(
        json_data={
            "101": {
                "title": "No URL Story",
                "identifiers": {},
                "tags": ["In-Progress"],
                "last_modified": "2026-11-20T10:00:00+00:00",
            },
            "102": {
                "title": "Blank URL Story",
                "identifiers": {"url": "   "},
                "tags": ["In-Progress"],
                "last_modified": "2026-11-20T10:00:00+00:00",
            },
            "103": {
                "title": "Valid Story",
                "identifiers": {"url": "https://www.fanfiction.net/s/12345/1/"},
                "tags": ["In-Progress", "Last Update: 2026/11/21"],
                "last_modified": "2026-11-21T15:30:00+00:00",
            },
        }
    )

    with patch.object(
        client, "_request", side_effect=[search_resp, books_resp]
    ) as mock_req:
        summaries = client.list_stories_by_query('identifiers:"fanfiction.net"')

    assert len(summaries) == 1
    assert summaries[0] == CalibreStorySummary(
        calibre_id="103",
        title="Valid Story",
        url="https://www.fanfiction.net/s/12345/1/",
        tags=["In-Progress", "Last Update: 2026/11/21"],
        last_modified=datetime(2026, 11, 21, 15, 30, tzinfo=timezone.utc),
        last_update_date=date(2026, 11, 21),
        update_date_exact=True,
    )
    assert mock_req.call_count == 2
    assert mock_req.call_args_list[0].args == ("POST", "/cdb/cmd/search/0")
    assert mock_req.call_args_list[0].kwargs["json_body"] == [
        'identifiers:"fanfiction.net"'
    ]
    assert mock_req.call_args_list[1].args == ("GET", "/ajax/books")
    assert mock_req.call_args_list[1].kwargs["params"] == {
        "ids": "101,102,103",
        "library_id": "Fanfic",
    }

    # Case 2: >200 IDs splits into multiple /ajax/books batches of 200
    many_ids = list(range(1, 451))  # 450 IDs -> 3 batches (200, 200, 50)
    search_many = _make_response(json_data={"result": many_ids})
    batch_responses = [
        _make_response(
            json_data={
                str(bid): {
                    "title": f"Story {bid}",
                    "identifiers": {"url": f"https://www.fanfiction.net/s/{bid}/1/"},
                    "tags": ["In-Progress"],
                    "last_modified": "2026-11-21T00:00:00+00:00",
                }
                for bid in many_ids[start : start + 200]
            }
        )
        for start in (0, 200, 400)
    ]

    with patch.object(
        client, "_request", side_effect=[search_many, *batch_responses]
    ) as mock_batch_req:
        many_summaries = client.list_stories_by_query('identifiers:"fanfiction.net"')

    assert len(many_summaries) == 450
    assert mock_batch_req.call_count == 4  # 1 search + 3 /ajax/books batches
    assert (
        len(mock_batch_req.call_args_list[1].kwargs["params"]["ids"].split(",")) == 200
    )
    assert (
        len(mock_batch_req.call_args_list[2].kwargs["params"]["ids"].split(",")) == 200
    )
    assert (
        len(mock_batch_req.call_args_list[3].kwargs["params"]["ids"].split(",")) == 50
    )


def test_calibredb_client_list_stories_parses_json_and_skips_missing_url() -> None:
    info = _make_mock_info("/library")
    client = CalibreDBClient(info, MagicMock(spec=ConfigStore))

    cli_payload = [
        {
            "id": 10,
            "title": "Missing URL",
            "identifiers": {"isbn": "12345"},
            "tags": ["In-Progress"],
            "last_modified": "2026-11-19T12:00:00+00:00",
        },
        {
            "id": 11,
            "title": "Invalid URL",
            "identifiers": {"url": "not a valid url"},
            "tags": ["In-Progress"],
            "last_modified": "2026-11-19T12:00:00+00:00",
        },
        {
            "id": 12,
            "title": "Good Story",
            "identifiers": {"url": "https://archiveofourown.org/works/99999"},
            "tags": ["In-Progress", "Last Update Year/Month: 2026/11"],
            "last_modified": "2026-11-20T09:15:00+00:00",
        },
    ]

    with patch(
        "calibre_integration.calibredb_utils.check_output",
        return_value=json.dumps(cli_payload),
    ) as mock_check_output:
        summaries = client.list_stories_by_query('identifiers:"archiveofourown.org"')

    assert len(summaries) == 1
    assert summaries[0] == CalibreStorySummary(
        calibre_id="12",
        title="Good Story",
        url="https://archiveofourown.org/works/99999",
        tags=["In-Progress", "Last Update Year/Month: 2026/11"],
        last_modified=datetime(2026, 11, 20, 9, 15, tzinfo=timezone.utc),
        last_update_date=date(2026, 11, 1),
        update_date_exact=False,
    )
    info.lock.__enter__.assert_called_once()
    info.lock.__exit__.assert_called_once()
    called_cmd = mock_check_output.call_args.args[0]
    assert called_cmd[:6] == [
        "calibredb",
        "list",
        "--search",
        'identifiers:"archiveofourown.org"',
        "--fields",
        "id,title,identifiers,tags,last_modified",
    ]
    assert "--for-machine" in called_cmd
