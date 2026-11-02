"""FanFicFare INI file resolution, caching, and configuration construction."""

import functools
import os
from pathlib import Path
from typing import Any

lazy import fanficfare
lazy from fanficfare import adapters, configurable

# Cache of (mtime_ns, size, text) keyed by absolute INI path
_ini_text_cache: dict[str, tuple[int, int, str]] = {}


def read_ini_file_cached(path: str | os.PathLike) -> str | None:
    """Read an INI file from disk, caching its contents by (mtime_ns, size)."""
    key = str(path)
    try:
        st = os.stat(key)
        cached = _ini_text_cache.get(key)
        if (
            cached is not None
            and cached[0] == st.st_mtime_ns
            and cached[1] == st.st_size
        ):
            return cached[2]
        with open(key, encoding="utf-8") as fh:
            text = fh.read()
        _ini_text_cache[key] = (st.st_mtime_ns, st.st_size, text)
        return text
    except OSError:
        return None


def clear_ini_cache() -> None:
    """Clear in-memory cache of INI file contents."""
    _ini_text_cache.clear()


@functools.lru_cache(maxsize=1)
def get_packaged_defaults_ini_path() -> str:
    """Return the filesystem path to the packaged FanFicFare defaults.ini."""
    try:
        fff_ini = Path(fanficfare.__file__).resolve().parent / "defaults.ini"
        if fff_ini.is_file():
            return str(fff_ini)
    except Exception:
        pass

    return ""


def resolve_ini_path(path: str | None, default_filename: str) -> str:
    """Resolve an INI file path, appending the filename if the path is a directory.

    When resolving `defaults.ini` and no path is configured (None or empty),
    it automatically falls back to the packaged FanFicFare `defaults.ini`.
    """
    if not path:
        if default_filename == "defaults.ini":
            return get_packaged_defaults_ini_path()
        return ""

    if not path.endswith(default_filename):
        return str(Path(path) / default_filename)

    return path


def resolve_state_personal_ini(state: Any) -> str:
    """Resolve the filesystem path to personal.ini from a WebState or similar state container."""
    if getattr(state, "config_store", None):
        return state.config_store.get_resolved_personal_ini()
    raw_personal = None
    if getattr(state, "config", None) and getattr(state.config, "calibre", None):
        raw_personal = state.config.calibre.personal_ini
    return (
        resolve_ini_path(raw_personal, "personal.ini") if raw_personal else ""
    ) or ""


def build_fff_configuration(
    url: str,
    default_ini_path: str | None = None,
    personal_ini_path: str | None = None,
) -> configurable.Configuration:
    """Return a FanFicFare Configuration loaded with site sections and INI files."""
    try:
        sections = adapters.getConfigSectionsFor(url)
    except Exception:
        sections = ["test1.com"]

    config = configurable.Configuration(sections, "EPUB")
    ini_files: list[str] = []

    if default_ini_path and os.path.isfile(default_ini_path):
        ini_files.append(default_ini_path)

    if personal_ini_path and os.path.isfile(personal_ini_path):
        ini_files.append(personal_ini_path)

    if ini_files:
        uncached_files: list[str] = []
        for ini_path in ini_files:
            cached_text = read_ini_file_cached(ini_path)
            if cached_text is not None:
                try:
                    config.read_string(cached_text, source=ini_path)
                except Exception:
                    uncached_files.append(ini_path)
            else:
                uncached_files.append(ini_path)
        if uncached_files:
            config.read(uncached_files)

    return config


__all__ = [
    "resolve_ini_path",
    "resolve_state_personal_ini",
    "get_packaged_defaults_ini_path",
    "read_ini_file_cached",
    "clear_ini_cache",
    "build_fff_configuration",
]
