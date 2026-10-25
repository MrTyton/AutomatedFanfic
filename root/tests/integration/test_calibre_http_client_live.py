from collections.abc import Iterator
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import zipfile
import pytest
import requests

from calibre_integration.calibre_info import CalibreInfo
from calibre_integration.http_client import CalibreHttpClient
from calibre_integration.models import (
    AddedBook,
    BookExport,
    CalibreAuthError,
    MetadataUpdateReport,
)
from config.config_store import ConfigStore
from models.config_models import CalibreConfig
from models.fanfic_info import FanficInfo
from fixtures.calibre_provisioner import ensure_calibre_binaries

pytestmark = [pytest.mark.integration, pytest.mark.slow, pytest.mark.flaky_ci]


class _NoopLockFactory:
    @staticmethod
    def Lock() -> None:
        return None


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_for_server(
    base_url: str, proc: subprocess.Popen | None = None, timeout: float = 20.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            stdout, stderr = proc.communicate(timeout=2.0)
            raise RuntimeError(
                f"calibre-server exited unexpectedly with rc={proc.returncode}.\n"
                f"STDOUT: {stdout}\nSTDERR: {stderr}"
            )
        try:
            resp = requests.get(f"{base_url}/favicon.png", timeout=1.0)
            if resp.status_code in (200, 401, 404):
                return
        except requests.RequestException:
            pass
        time.sleep(0.05)
    raise RuntimeError(f"calibre-server at {base_url} did not start within {timeout}s")


def _build_sample_epub(
    target_path: Path,
    *,
    title: str,
    author: str,
    story_url: str,
    body_html: str,
) -> Path:
    with zipfile.ZipFile(target_path, "w") as zf:
        zf.writestr(
            "mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED
        )
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?>'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            "<rootfiles>"
            '<rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>'
            "</rootfiles>"
            "</container>",
        )
        zf.writestr(
            "content.opf",
            '<?xml version="1.0" encoding="utf-8"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" xmlns:opf="http://www.idpf.org/2007/opf" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" unique-identifier="BookId" version="2.0">'
            "<metadata>"
            f"<dc:title>{title}</dc:title>"
            f'<dc:creator opf:role="aut">{author}</dc:creator>'
            "<dc:language>en</dc:language>"
            f'<dc:identifier id="BookId" opf:scheme="URI">{story_url}</dc:identifier>'
            f'<dc:identifier opf:scheme="URL">{story_url}</dc:identifier>'
            f"<dc:source>{story_url}</dc:source>"
            "</metadata>"
            "<manifest>"
            '<item id="ch1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>'
            "</manifest>"
            "<spine>"
            '<itemref idref="ch1"/>'
            "</spine>"
            "</package>",
        )
        zf.writestr(
            "chapter1.xhtml",
            f'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{title}</title></head>'
            f"<body>{body_html}</body></html>",
        )
    return target_path


def _init_calibre_library(calibredb_bin: Path, lib_dir: Path) -> None:
    lib_dir.mkdir(parents=True, exist_ok=True)
    for args in (
        [str(calibredb_bin), "list", f"--with-library={lib_dir}"],
        [
            str(calibredb_bin),
            "add_custom_column",
            f"--with-library={lib_dir}",
            "testcol",
            "Test Column",
            "text",
        ],
    ):
        res = subprocess.run(args, capture_output=True, text=True, timeout=30)
        if res.returncode != 0:
            raise RuntimeError(
                f"Command {args} failed (rc={res.returncode}):\n"
                f"STDOUT: {res.stdout}\nSTDERR: {res.stderr}"
            )


@pytest.fixture
def calibre_server_url() -> Iterator[str]:
    binaries = ensure_calibre_binaries()
    # Calibre enforces a <75-char library path limit on Windows, so use a short temp prefix
    lib_dir = Path(tempfile.mkdtemp(prefix="cal_l_"))
    try:
        _init_calibre_library(binaries.calibredb, lib_dir)

        port = _find_free_port()
        base_url = f"http://127.0.0.1:{port}"
        proc = subprocess.Popen(
            [
                str(binaries.calibre_server),
                "--listen-on",
                "127.0.0.1",
                "--port",
                str(port),
                "--enable-local-write",
                str(lib_dir),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            _wait_for_server(base_url, proc=proc)
            yield base_url
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    finally:
        shutil.rmtree(lib_dir, ignore_errors=True)


@pytest.fixture
def calibre_auth_server_url() -> Iterator[tuple[str, str, str]]:
    binaries = ensure_calibre_binaries()
    lib_dir = Path(tempfile.mkdtemp(prefix="cal_a_"))
    userdb_dir = Path(tempfile.mkdtemp(prefix="cal_u_"))
    try:
        _init_calibre_library(binaries.calibredb, lib_dir)

        userdb_path = userdb_dir / "users.sqlite"
        username = "ffdl_user"
        password = "ffdl_pass_123"

        subprocess.run(
            [
                str(binaries.calibre_server),
                "--userdb",
                str(userdb_path),
                "--manage-users",
                "--",
                "add",
                username,
                password,
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )

        port = _find_free_port()
        base_url = f"http://127.0.0.1:{port}"
        proc = subprocess.Popen(
            [
                str(binaries.calibre_server),
                "--listen-on",
                "127.0.0.1",
                "--port",
                str(port),
                "--enable-auth",
                "--userdb",
                str(userdb_path),
                str(lib_dir),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            _wait_for_server(base_url, proc=proc)
            yield base_url, username, password
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    finally:
        shutil.rmtree(lib_dir, ignore_errors=True)
        shutil.rmtree(userdb_dir, ignore_errors=True)


def test_live_calibre_http_client_full_lifecycle(
    calibre_server_url: str, tmp_path: Path
) -> None:
    expected_version = (
        (Path(__file__).resolve().parents[3] / "release-versions" / "calibre.txt")
        .read_text(encoding="utf-8")
        .strip()
    )

    cfg = CalibreConfig(path=calibre_server_url)
    info = CalibreInfo(cfg, _NoopLockFactory())
    client = CalibreHttpClient(info, ConfigStore({}))

    # 1. Verify server version
    version = client.get_version()
    assert version == expected_version

    story_url = "https://archiveofourown.org/works/99999"
    prefix_url = "https://archiveofourown.org/works/9999"
    fanfic = FanficInfo(site="ao3", url=story_url)
    prefix_fanfic = FanficInfo(site="ao3", url=prefix_url)

    # 2. Verify story does not exist initially
    assert client.get_story_id(fanfic) is None

    # 3. Add story from EPUB
    add_dir = tmp_path / "add_dir"
    add_dir.mkdir()
    _build_sample_epub(
        add_dir / "Live Test Story - TestAuthor.epub",
        title="Live Test Story",
        author="TestAuthor",
        story_url=story_url,
        body_html="<p>Initial chapter 1 content</p>",
    )
    added = client.add_story(str(add_dir), fanfic)
    assert isinstance(added, AddedBook)
    assert added.calibre_id == fanfic.calibre_id
    assert added.title == "Live Test Story"

    # Verify adding a duplicate story succeeds and assigns a new distinct calibre_id
    duplicate_fanfic = FanficInfo(site="ao3", url=story_url)
    added_duplicate = client.add_story(str(add_dir), duplicate_fanfic)
    assert isinstance(added_duplicate, AddedBook)
    assert added_duplicate.calibre_id != added.calibre_id
    client.remove_story(duplicate_fanfic)

    # 4. Verify exact URL search matches story_url and does NOT match prefix_url
    found_id = client.get_story_id(fanfic)
    assert found_id == added.calibre_id
    assert client.get_story_id(prefix_fanfic) is None

    # 5. Set and read back custom metadata
    report = client.set_metadata_fields(fanfic, {"#testcol": "CustomTagValue"})
    assert isinstance(report, MetadataUpdateReport)
    assert report.is_success is True
    assert report.updated_fields == ("#testcol",)

    meta = client.get_metadata(fanfic)
    assert meta["title"] == "Live Test Story"
    assert meta["#testcol"] == "CustomTagValue"

    # 6. Export story and verify chapter HTML inside exported EPUB
    export_dir = tmp_path / "export_dir"
    export_dir.mkdir()
    exported = client.export_story(fanfic, str(export_dir))
    assert isinstance(exported, BookExport)
    assert exported.file_path.exists()
    assert exported.size_bytes > 0
    with zipfile.ZipFile(exported.file_path, "r") as zf:
        ch_text = zf.read("chapter1.xhtml").decode("utf-8")
        assert "Initial chapter 1 content" in ch_text

    # 7. Replace format with updated EPUB and verify both updated content and preserved custom metadata
    update_dir = tmp_path / "update_dir"
    update_dir.mkdir()
    _build_sample_epub(
        update_dir / "Live Test Story - TestAuthor.epub",
        title="Live Test Story",
        author="TestAuthor",
        story_url=story_url,
        body_html="<p>Updated chapter 2 content</p>",
    )
    assert client.add_format_to_existing_story(str(update_dir), fanfic) is True

    export_dir_2 = tmp_path / "export_dir_2"
    export_dir_2.mkdir()
    exported_2 = client.export_story(fanfic, str(export_dir_2))
    assert isinstance(exported_2, BookExport)
    with zipfile.ZipFile(exported_2.file_path, "r") as zf:
        ch_text_2 = zf.read("chapter1.xhtml").decode("utf-8")
        assert "Updated chapter 2 content" in ch_text_2

    meta_after_replace = client.get_metadata(fanfic)
    assert meta_after_replace["#testcol"] == "CustomTagValue"

    # 8. Remove story and verify it is gone
    assert client.remove_story(fanfic) is True
    assert fanfic.calibre_id is None
    assert client.get_story_id(fanfic) is None


def test_live_calibre_http_client_digest_auth(
    calibre_auth_server_url: tuple[str, str, str], tmp_path: Path
) -> None:
    base_url, username, password = calibre_auth_server_url

    # Verify wrong password raises CalibreAuthError
    bad_cfg = CalibreConfig(path=base_url, username=username, password="wrong_password")
    bad_client = CalibreHttpClient(
        CalibreInfo(bad_cfg, _NoopLockFactory()), ConfigStore({})
    )
    with pytest.raises(CalibreAuthError):
        bad_client._request("GET", "/ajax/library-info")

    # Verify valid credentials authenticate via HTTP Digest Auth and can write/delete a story
    good_cfg = CalibreConfig(path=base_url, username=username, password=password)
    good_client = CalibreHttpClient(
        CalibreInfo(good_cfg, _NoopLockFactory()), ConfigStore({})
    )

    add_dir = tmp_path / "auth_add"
    add_dir.mkdir()
    story_url = "https://archiveofourown.org/works/88888"
    _build_sample_epub(
        add_dir / "Auth Story - Author.epub",
        title="Auth Story",
        author="Author",
        story_url=story_url,
        body_html="<p>Authenticated upload</p>",
    )
    fanfic = FanficInfo(site="ao3", url=story_url)
    added = good_client.add_story(str(add_dir), fanfic)
    assert isinstance(added, AddedBook)
    assert good_client.get_story_id(fanfic) == added.calibre_id
    assert good_client.remove_story(fanfic) is True
