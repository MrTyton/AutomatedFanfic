"""Pure-Python HTTP client for Calibre Content Server."""

import base64
from contextlib import AbstractContextManager, nullcontext
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import quote, unquote, urlsplit

import requests
import requests.auth

from calibre_integration import calibre_info
from calibre_integration.client_interface import (
    CalibreClient,
    CalibreMetadata,
    build_url_search_query,
)
from calibre_integration.models import (
    AddedBook,
    BookExport,
    CalibreAuthError,
    CalibreConnectionError,
    CalibreOperationError,
    MetadataUpdateReport,
)
from config.config_store import ConfigStore
from models import fanfic_info
from parsers import regex_parsing
from utils import ff_logging

CALIBRE_CANARY_KEY = "jPoAv3zOyHvQ5JFNYg4hJ9"
DEFAULT_HTTP_TIMEOUT = 60


def _calibre_json_object_hook(obj: dict[str, object]) -> object:
    """Unwrap Calibre's custom JSON serialization canary for sets and datetimes."""
    if CALIBRE_CANARY_KEY in obj and "v" in obj:
        return obj["v"]
    return obj


class CalibreHttpClient(CalibreClient):
    """Client for interacting with Calibre Content Server over HTTP/HTTPS."""

    def __init__(
        self,
        cdb_info: calibre_info.CalibreInfo,
        config_store: ConfigStore,
    ) -> None:
        """Initialize the Calibre HTTP client."""
        super().__init__(cdb_info, config_store)
        self.base_url: str = ""
        self.library_id: str = ""
        self._auth_generation: int = 0
        self._thread_local = threading.local()
        self._parse_server_url()

    def _parse_server_url(self) -> None:
        """Parse base_url and optional #library_id fragment from cdb_info.location."""
        raw_location = (self.cdb_info.location or "").strip()
        parsed = urlsplit(raw_location)
        clean_path = parsed.path.rstrip("/")
        self.base_url = f"{parsed.scheme}://{parsed.netloc}{clean_path}"
        self.library_id = unquote(parsed.fragment.strip()) if parsed.fragment else ""

    def _on_config_refreshed(self) -> None:
        """Re-parse URL and invalidate thread-local sessions when config changes."""
        self._parse_server_url()
        self._auth_generation += 1

    def __getstate__(self) -> dict[str, object]:
        """Strip unpicklable thread-local session storage before multiprocessing pickle."""
        state = self.__dict__.copy()
        state.pop("_thread_local", None)
        return state

    def __setstate__(self, state: dict[str, object]) -> None:
        """Restore state and re-initialize thread-local storage in child process."""
        for key, value in state.items():
            setattr(self, key, value)
        self._thread_local = threading.local()

    def _get_session(self) -> requests.Session:
        """Return a thread-local requests.Session configured with current credentials."""
        session: requests.Session | None = getattr(self._thread_local, "session", None)
        gen: int = getattr(self._thread_local, "auth_generation", -1)
        if session is None or gen != self._auth_generation:
            session = requests.Session()
            if self.cdb_info.username and self.cdb_info.password:
                session.auth = requests.auth.HTTPDigestAuth(
                    self.cdb_info.username, self.cdb_info.password
                )
            self._thread_local.session = session
            self._thread_local.auth_generation = self._auth_generation
        return session

    def _lock_context(self) -> AbstractContextManager[object]:
        """Return cdb_info.lock if available, or a no-op context manager."""
        lock = getattr(self.cdb_info, "lock", None)
        return lock if lock is not None else nullcontext()

    def _library_path_suffix(self) -> str:
        """Return URL path suffix '/{library_id}' if library_id is set, else ''."""
        if self.library_id:
            return f"/{quote(self.library_id, safe='')}"
        return ""

    def _library_query_params(self) -> dict[str, str]:
        """Return query parameter dict for `/cdb/cmd/*` endpoints."""
        if self.library_id:
            return {"library_id": self.library_id}
        return {}

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: object = None,
        raw_body: bytes | None = None,
        content_type: str | None = None,
        timeout: int = DEFAULT_HTTP_TIMEOUT,
    ) -> requests.Response:
        """Execute an HTTP request against the Calibre Content Server."""
        self.refresh_if_changed()
        session = self._get_session()
        url = f"{self.base_url}{path}"

        headers: dict[str, str] = {}
        data: bytes | str | None = None
        if json_body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
            data = json.dumps(json_body)
        elif raw_body is not None:
            headers["Content-Type"] = content_type or "application/octet-stream"
            data = raw_body

        try:
            response = session.request(
                method,
                url,
                params=params,
                data=data,
                headers=headers,
                timeout=timeout,
            )

            # Fallback from Digest Auth to Basic Auth if server demands Basic
            if (
                response.status_code == 401
                and self.cdb_info.username
                and self.cdb_info.password
                and isinstance(session.auth, requests.auth.HTTPDigestAuth)
            ):
                www_auth = response.headers.get("WWW-Authenticate", "")
                if www_auth.lower().startswith("basic"):
                    session.auth = requests.auth.HTTPBasicAuth(
                        self.cdb_info.username, self.cdb_info.password
                    )
                    response = session.request(
                        method,
                        url,
                        params=params,
                        data=data,
                        headers=headers,
                        timeout=timeout,
                    )
        except requests.RequestException as exc:
            raise CalibreConnectionError(
                f"Failed to connect to Calibre server at {url}: {exc}"
            ) from exc

        if response.status_code in (401, 403):
            raise CalibreAuthError(
                f"Calibre authentication/permission error ({response.status_code}) at {url}: {response.text.strip()}"
            )

        if response.status_code >= 400:
            err_detail = response.text.strip()
            try:
                err_json = json.loads(response.text)
                if isinstance(err_json, dict) and "err" in err_json:
                    err_detail = str(err_json["err"])
            except ValueError, TypeError:
                pass
            raise CalibreOperationError(
                f"Calibre server error ({response.status_code}) at {url}: {err_detail}"
            )

        return response

    @staticmethod
    def _decode_json(response: requests.Response) -> object:
        """Decode JSON response, unwrapping Calibre canary objects and checking 'err'."""
        try:
            payload = json.loads(response.text, object_hook=_calibre_json_object_hook)
        except (ValueError, TypeError) as exc:
            raise CalibreOperationError(
                f"Invalid JSON response from Calibre server: {exc}"
            ) from exc

        if isinstance(payload, dict) and payload.get("err"):
            raise CalibreOperationError(f"Calibre RPC error: {payload['err']}")
        return payload

    def get_version(self) -> str:
        """Return the remote Calibre server version string."""
        try:
            response = self._request("GET", "/ajax/library-info", timeout=10)
            if not self.library_id:
                try:
                    info = self._decode_json(response)
                    if isinstance(info, dict) and info.get("default_library"):
                        self.library_id = str(info["default_library"])
                except CalibreOperationError:
                    pass

            server_header = response.headers.get("Server", "").strip()
            if server_header:
                match = re.search(
                    r"calibre[/ ](\d+\.\d+(?:\.\d+)?)", server_header, re.IGNORECASE
                )
                if match:
                    return match.group(1)
                return server_header
            return "Unknown"
        except (
            CalibreConnectionError,
            CalibreAuthError,
            CalibreOperationError,
        ) as exc:
            return f"Error: {exc}"

    def get_story_id(self, fanfic: fanfic_info.FanficInfo) -> str | None:
        """Check if a story exists in Calibre Content Server and return its ID."""
        try:
            search_query = build_url_search_query(fanfic.url)
            response = self._request(
                "POST",
                "/cdb/cmd/search/0",
                params=self._library_query_params(),
                json_body=[search_query],
            )
            payload = self._decode_json(response)
            result = payload.get("result") if isinstance(payload, dict) else None
            if isinstance(result, list) and result:
                sorted_ids = sorted(int(x) for x in result)
                fanfic.calibre_id = str(sorted_ids[0])
                return fanfic.calibre_id

            ff_logging.log(f"\t({fanfic.site}) Story not in Calibre")
            return None
        except (
            CalibreConnectionError,
            CalibreAuthError,
            CalibreOperationError,
        ) as exc:
            ff_logging.log(f"\t({fanfic.site}) Story not in Calibre")
            ff_logging.log_debug(f"\tError checking story ID over HTTP: {exc}")
            return None

    def add_story(
        self, location: str, fanfic: fanfic_info.FanficInfo
    ) -> AddedBook | None:
        """Upload an EPUB from `location` to the Calibre Content Server."""
        file_to_add = self._find_epub_in_directory(location)
        if not file_to_add:
            ff_logging.log_failure(
                f"\t({fanfic.site}) No EPUB file found in '{location}' for {fanfic.url}. "
                "FanFicFare may have failed silently — check the FanFicFare output above."
            )
            return None

        epub_path = Path(file_to_add)
        fanfic.title = regex_parsing.extract_filename(file_to_add)
        ff_logging.log(f"\t({fanfic.site}) Adding {file_to_add} to Calibre via HTTP")

        try:
            epub_bytes = epub_path.read_bytes()
            job_id = int(time.time() * 1000) % 1_000_000_000
            encoded_name = quote(epub_path.name, safe="")
            # 'y' means add_duplicates=True (Calibre checks add_duplicates in ('y', '1'))
            path = (
                f"/cdb/add-book/{job_id}/y/{encoded_name}{self._library_path_suffix()}"
            )

            with self._lock_context():
                response = self._request(
                    "POST",
                    path,
                    raw_body=epub_bytes,
                    content_type="application/octet-stream",
                )
            payload = self._decode_json(response)
            if not isinstance(payload, dict) or "book_id" not in payload:
                if isinstance(payload, dict) and "duplicates" in payload:
                    raise CalibreOperationError(
                        f"Calibre server rejected book as duplicate: {payload['duplicates']}"
                    )
                raise CalibreOperationError(
                    f"Unexpected add-book response from Calibre server: {payload}"
                )

            fanfic.calibre_id = str(payload["book_id"])
            if payload.get("title"):
                fanfic.title = str(payload["title"])

            ff_logging.log_debug(
                f"\t({fanfic.site}) Added story with ID: {fanfic.calibre_id}"
            )
            return AddedBook(
                calibre_id=fanfic.calibre_id,
                title=str(fanfic.title or ""),
                formats=("EPUB",),
            )
        except OSError as exc:
            ff_logging.log_failure(f"\t({fanfic.site}) Failed to add story: {exc}")
            raise

    def remove_story(self, fanfic: fanfic_info.FanficInfo) -> bool:
        """Delete a book from the Calibre Content Server by ID."""
        if not fanfic.calibre_id:
            ff_logging.log_failure("\tCannot remove story: no calibre_id")
            return False

        book_id = int(fanfic.calibre_id)
        path = f"/cdb/delete-books/{book_id}{self._library_path_suffix()}"
        with self._lock_context():
            self._request("POST", path, json_body={})
        fanfic.calibre_id = None
        return True

    def export_story(
        self, fanfic: fanfic_info.FanficInfo, location: str
    ) -> BookExport | None:
        """Download an EPUB story from the Calibre Content Server into `location`."""
        if not fanfic.calibre_id:
            ff_logging.log_failure("\tCannot export story: no calibre_id")
            return None

        book_id = int(fanfic.calibre_id)
        path = f"/get/epub/{book_id}{self._library_path_suffix()}"
        response = self._request("GET", path)

        filename = f"{book_id}.epub"
        content_disp = response.headers.get("Content-Disposition", "")
        if content_disp:
            match = re.search(
                r'filename\*?=(?:UTF-8\'\')?"?([^";\r\n]+)"?', content_disp
            )
            if match:
                candidate = Path(unquote(match.group(1)).strip()).name
                if candidate:
                    if not candidate.lower().endswith(".epub"):
                        candidate = f"{candidate}.epub"
                    filename = candidate

        target_path = Path(location) / filename
        target_path.write_bytes(response.content)
        return BookExport(
            file_path=target_path,
            format="EPUB",
            size_bytes=len(response.content),
        )

    def add_format_to_existing_story(
        self, location: str, fanfic: fanfic_info.FanficInfo
    ) -> bool:
        """Replace the EPUB format for an existing story via `/cdb/set-fields`."""
        if not fanfic.calibre_id:
            ff_logging.log_failure("\tCannot add format: story has no calibre_id")
            return False

        file_to_add = self._find_epub_in_directory(location)
        if not file_to_add:
            ff_logging.log_failure(
                f"\t({fanfic.site}) No EPUB file found in '{location}' for {fanfic.url}. "
                "FanFicFare may have failed silently — check the FanFicFare output above."
            )
            return False

        ff_logging.log(
            f"\t({fanfic.site}) Replacing EPUB format for ID {fanfic.calibre_id}"
        )

        try:
            epub_bytes = Path(file_to_add).read_bytes()
            b64_data = base64.b64encode(epub_bytes).decode("ascii")
            book_id = int(fanfic.calibre_id)
            path = f"/cdb/set-fields/{book_id}{self._library_path_suffix()}"
            payload = {
                "changes": {
                    "added_formats": [
                        {
                            "ext": "EPUB",
                            "data_url": b64_data,
                        }
                    ]
                }
            }
            with self._lock_context():
                self._request("POST", path, json_body=payload)
            ff_logging.log(f"\t({fanfic.site}) Successfully replaced EPUB format")
            return True
        except OSError as exc:
            ff_logging.log_failure(
                f"\t({fanfic.site}) Failed to replace EPUB format: {exc}"
            )
            raise

    def get_metadata(self, fanfic: fanfic_info.FanficInfo) -> CalibreMetadata:
        """Get all metadata fields for a story via `/cdb/cmd/list/0`."""
        if not fanfic.calibre_id:
            ff_logging.log_failure("\tCannot get metadata: story has no calibre_id")
            return {}

        try:
            book_id = int(fanfic.calibre_id)
            book_id_str = str(book_id)
            response = self._request(
                "POST",
                "/cdb/cmd/list/0",
                params=self._library_query_params(),
                json_body=[["all"], "id", True, f"id:{book_id}", 1],
            )
            payload = self._decode_json(response)
            result = payload.get("result") if isinstance(payload, dict) else None
            if not isinstance(result, dict):
                ff_logging.log_failure(
                    f"\tNo metadata found for ID {fanfic.calibre_id}"
                )
                return {}

            book_ids = result.get("book_ids") or []
            data_by_field = result.get("data") or {}
            if not book_ids or not isinstance(data_by_field, dict):
                ff_logging.log_failure(
                    f"\tNo metadata found for ID {fanfic.calibre_id}"
                )
                return {}

            metadata: CalibreMetadata = {"id": book_id}
            for raw_field, field_map in data_by_field.items():
                field_name = (
                    "#" + raw_field[1:] if raw_field.startswith("*") else raw_field
                )
                if isinstance(field_map, dict):
                    if book_id_str in field_map:
                        metadata[field_name] = field_map[book_id_str]
                    elif book_id in field_map:
                        metadata[field_name] = field_map[book_id]

            ff_logging.log_debug(
                f"\t({fanfic.site}) Retrieved metadata for ID {fanfic.calibre_id}: "
                f"{len(metadata)} fields"
            )
            return metadata
        except OSError as exc:
            ff_logging.log_failure(
                f"\tFailed to retrieve metadata for ID {fanfic.calibre_id}: {exc}"
            )
            return {}

    def set_metadata_fields(
        self,
        fanfic: fanfic_info.FanficInfo,
        metadata: CalibreMetadata,
    ) -> MetadataUpdateReport:
        """Restore custom `#` metadata fields for a story via `/cdb/set-fields`."""
        if not fanfic.calibre_id:
            ff_logging.log_failure("\tCannot set metadata: story has no calibre_id")
            return MetadataUpdateReport(updated_fields=(), failed_fields=())

        if not metadata:
            return MetadataUpdateReport(updated_fields=(), failed_fields=())

        custom_changes: CalibreMetadata = {
            k: v
            for k, v in metadata.items()
            if k.startswith("#") and v is not None and v != "" and v != []
        }
        if not custom_changes:
            return MetadataUpdateReport(updated_fields=(), failed_fields=())

        ff_logging.log_debug(
            f"\t({fanfic.site}) Attempting to restore {len(custom_changes)} metadata fields"
        )

        book_id = int(fanfic.calibre_id)
        path = f"/cdb/set-fields/{book_id}{self._library_path_suffix()}"
        updated_fields: list[str] = []
        failed_fields: list[str] = []

        try:
            with self._lock_context():
                self._request("POST", path, json_body={"changes": custom_changes})
            updated_fields = list(custom_changes.keys())
        except OSError as batch_err:
            ff_logging.log_debug(
                f"\t({fanfic.site}) Batch set-fields failed ({batch_err}), falling back to per-field update"
            )
            for field_name, field_val in custom_changes.items():
                try:
                    with self._lock_context():
                        self._request(
                            "POST",
                            path,
                            json_body={"changes": {field_name: field_val}},
                        )
                    updated_fields.append(field_name)
                except OSError as exc:
                    failed_fields.append(field_name)
                    ff_logging.log_failure(
                        f"\t  Failed to restore field {field_name}: {exc}"
                    )

        ff_logging.log_debug(
            f"\t({fanfic.site}) Successfully restored {len(updated_fields)}/{len(custom_changes)} metadata fields"
        )
        return MetadataUpdateReport(
            updated_fields=tuple(updated_fields),
            failed_fields=tuple(failed_fields),
        )
