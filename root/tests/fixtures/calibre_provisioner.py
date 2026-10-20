"""Automated Calibre binary provisioner for live integration testing."""

from dataclasses import dataclass
import lzma
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

REPO_ROOT = Path(__file__).resolve().parents[3]
CALIBRE_VERSION_FILE = REPO_ROOT / "release-versions" / "calibre.txt"
CACHE_ROOT = REPO_ROOT / ".cache" / "calibre"


@dataclass(frozen=True)
class CalibreBinaries:
    """Paths to provisioned `calibre-server` and `calibredb` executables."""

    calibre_server: Path
    calibredb: Path
    version: str


def get_pinned_calibre_version() -> str:
    """Read the pinned Calibre version from `release-versions/calibre.txt`."""
    return CALIBRE_VERSION_FILE.read_text(encoding="utf-8").strip().lstrip("v")


def _query_binary_version(binary_path: Path) -> str | None:
    """Run `<binary> --version` and extract the `X.Y.Z` version string."""
    if not binary_path.is_file():
        return None
    try:
        output = subprocess.check_output(
            [str(binary_path), "--version"],
            stderr=subprocess.DEVNULL,
            timeout=15,
            text=True,
        )
        match = re.search(r"calibre\s+(\d+\.\d+(?:\.\d+)?)", output, re.IGNORECASE)
        if match:
            return match.group(1)
    except subprocess.SubprocessError, OSError:
        return None
    return None


def _version_matches(actual: str | None, expected: str) -> bool:
    if not actual:
        return False

    # Handle 9.16 vs 9.16.0 normalization
    def _norm(v: str) -> tuple[int, ...]:
        parts = [int(p) for p in v.split(".") if p.isdigit()]
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts)

    return _norm(actual) == _norm(expected)


def _find_existing_binaries(expected_version: str) -> CalibreBinaries | None:
    """Search cache and standard system locations for matching Calibre binaries."""
    exe_suffix = ".exe" if sys.platform == "win32" else ""
    server_name = f"calibre-server{exe_suffix}"
    db_name = f"calibredb{exe_suffix}"

    version_cache = CACHE_ROOT / expected_version
    candidate_dirs = [
        version_cache,
        version_cache / "Calibre Portable" / "Calibre",
    ]

    which_server = shutil.which("calibre-server")
    if which_server:
        candidate_dirs.append(Path(which_server).resolve().parent)

    if sys.platform == "win32":
        candidate_dirs.append(Path(r"C:\Program Files\Calibre2"))
    elif sys.platform == "darwin":
        candidate_dirs.append(Path("/Applications/calibre.app/Contents/MacOS"))

    for directory in candidate_dirs:
        server_bin = directory / server_name
        db_bin = directory / db_name
        if server_bin.is_file() and db_bin.is_file():
            detected = _query_binary_version(server_bin)
            if _version_matches(detected, expected_version):
                return CalibreBinaries(
                    calibre_server=server_bin,
                    calibredb=db_bin,
                    version=expected_version,
                )

    return None


def _provision_linux(version: str, target_dir: Path) -> CalibreBinaries:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        arch = "x86_64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    else:
        raise RuntimeError(f"Unsupported Linux architecture for Calibre: {machine}")

    target_dir.mkdir(parents=True, exist_ok=True)
    archive_path = target_dir / f"calibre-{version}-{arch}.txz"
    url = f"https://download.calibre-ebook.com/{version}/calibre-{version}-{arch}.txz"

    if not archive_path.is_file() or archive_path.stat().st_size == 0:
        urllib.request.urlretrieve(url, archive_path)

    with tarfile.open(archive_path, mode="r:xz") as tf:
        tf.extractall(path=target_dir, filter="fully_trusted")

    server_bin = target_dir / "calibre-server"
    db_bin = target_dir / "calibredb"
    if not server_bin.is_file() or not db_bin.is_file():
        raise RuntimeError(f"Failed to provision Calibre {version} in {target_dir}")

    return CalibreBinaries(calibre_server=server_bin, calibredb=db_bin, version=version)


def _extract_windows_portable_installer(installer_path: Path, target_dir: Path) -> None:
    """Headlessly extract the LZIP-compressed ZIP archive inside `calibre-portable-installer.exe`.

    Calibre's portable installer embeds an LZIP stream (4-byte magic ``LZIP``,
    1-byte version, 1-byte coded LZMA dictionary size) inside its ``.rsrc`` PE
    section that decompresses to a standard ZIP archive containing ``Calibre/*``.
    Extracting it directly in Python avoids the Windows GUI prompt and works in
    headless CI environments.
    """
    zip_path = target_dir / "portable_payload.zip"
    with installer_path.open("rb") as f:
        header_probe = f.read(1024 * 1024)
        lzip_offset = -1
        search_pos = 0
        while True:
            idx = header_probe.find(b"LZIP\x00", search_pos)
            if idx == -1 or idx + 6 > len(header_probe):
                break
            ds_code = header_probe[idx + 5]
            if 12 <= (ds_code & 0x1F) <= 29:
                lzip_offset = idx
                break
            search_pos = idx + 1
        if lzip_offset == -1:
            raise RuntimeError(f"Could not locate LZIP payload inside {installer_path}")
        f.seek(lzip_offset)
        lzip_header = f.read(6)
        ds_code = lzip_header[5]
        dict_size = 1 << (ds_code & 0x1F)
        dict_size -= (dict_size // 16) * ((ds_code >> 5) & 7)
        decompressor = lzma.LZMADecompressor(
            format=lzma.FORMAT_RAW,
            filters=[
                {
                    "id": lzma.FILTER_LZMA1,
                    "dict_size": dict_size,
                    "lc": 3,
                    "lp": 0,
                    "pb": 2,
                }
            ],
        )
        with zip_path.open("wb") as out_f:
            while not decompressor.eof:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                out_f.write(decompressor.decompress(chunk))

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(target_dir)
    finally:
        zip_path.unlink(missing_ok=True)


def _provision_windows(version: str, target_dir: Path) -> CalibreBinaries:
    target_dir.mkdir(parents=True, exist_ok=True)
    installer_path = target_dir / f"calibre-portable-installer-{version}.exe"
    url = f"https://download.calibre-ebook.com/{version}/calibre-portable-installer-{version}.exe"

    if not installer_path.is_file() or installer_path.stat().st_size == 0:
        urllib.request.urlretrieve(url, installer_path)

    _extract_windows_portable_installer(installer_path, target_dir)

    calibre_dir = target_dir / "Calibre Portable" / "Calibre"
    if not (calibre_dir / "calibre-server.exe").is_file():
        # Fallback if the ZIP extracted directly under target_dir / Calibre
        alt_dir = target_dir / "Calibre"
        if (alt_dir / "calibre-server.exe").is_file():
            calibre_dir = alt_dir

    server_bin = calibre_dir / "calibre-server.exe"
    db_bin = calibre_dir / "calibredb.exe"
    if not server_bin.is_file() or not db_bin.is_file():
        raise RuntimeError(
            f"Failed to extract Calibre Portable {version} into {calibre_dir}"
        )

    return CalibreBinaries(calibre_server=server_bin, calibredb=db_bin, version=version)


def ensure_calibre_binaries() -> CalibreBinaries:
    """Return paths to `calibre-server` and `calibredb` matching `release-versions/calibre.txt`."""
    expected_version = get_pinned_calibre_version()
    existing = _find_existing_binaries(expected_version)
    if existing is not None:
        return existing

    target_dir = CACHE_ROOT / expected_version
    if sys.platform.startswith("linux"):
        return _provision_linux(expected_version, target_dir)
    if sys.platform == "win32":
        return _provision_windows(expected_version, target_dir)

    raise RuntimeError(
        f"Automatic Calibre provisioning is not supported on {sys.platform}; "
        f"please install Calibre {expected_version} on PATH."
    )
