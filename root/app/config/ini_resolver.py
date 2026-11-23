"""FanFicFare INI file resolution, caching, and configuration construction."""

import configparser
import functools
import os
from pathlib import Path
import re
from typing import Any

lazy import fanficfare
lazy from fanficfare import adapters, configurable

# Cache of (mtime_ns, size, text) keyed by absolute INI path
_ini_text_cache: dict[str, tuple[int, int, str]] = {}

_SITE_ALIAS_DOMAINS: dict[str, str] = {
    "fanfiction": "fanfiction.net",
    "ffnet": "fanfiction.net",
    "archiveofourown": "archiveofourown.org",
    "ao3": "archiveofourown.org",
    "royalroad": "royalroad.com",
    "spacebattles": "forums.spacebattles.com",
    "sb": "forums.spacebattles.com",
    "sufficientvelocity": "forums.sufficientvelocity.com",
    "sv": "forums.sufficientvelocity.com",
    "questionablequesting": "forum.questionablequesting.com",
    "qq": "forum.questionablequesting.com",
    "scribblehub": "scribblehub.com",
    "fictionpress": "fictionpress.com",
    "webnovel": "webnovel.com",
    "wattpad": "wattpad.com",
    "fimfiction": "fimfiction.net",
    "alternatehistory": "alternatehistory.com",
}
_REPLACE_TAG_SPLIT_RE = re.compile(r"\\,|,")
_REGEX_BACKREF_RE = re.compile(r"(?:\\[0-9g<]|(?<!\\)\$[0-9])")


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


def resolve_state_default_ini(state: Any) -> str:
    """Resolve the filesystem path to defaults.ini from a WebState or similar state container."""
    if getattr(state, "config_store", None):
        return state.config_store.get_resolved_default_ini()
    raw_default = None
    if getattr(state, "config", None) and getattr(state.config, "calibre", None):
        raw_default = state.config.calibre.default_ini
    return (resolve_ini_path(raw_default, "defaults.ini") if raw_default else "") or ""


def build_fff_configuration(
    url: str,
    default_ini_path: str = "",
    personal_ini_path: str = "",
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


def _parse_ini_file(path: str) -> configparser.RawConfigParser | None:
    """Parse an INI file with RawConfigParser(strict=False), returning None on error."""
    if not path or not os.path.isfile(path):
        return None
    parser = configparser.RawConfigParser(strict=False)
    text = read_ini_file_cached(path)
    try:
        if text is not None:
            parser.read_string(text, source=path)
        else:
            parser.read(path, encoding="utf-8")
    except OSError, configparser.Error:
        return None
    return parser


def _matching_site_sections(
    parser: configparser.RawConfigParser, site: str
) -> list[str]:
    """Return INI section names in `parser` matching `site` (including www/alias variants)."""
    site_key = site.strip().lower()
    if not site_key:
        return []
    bare_site = site_key.removeprefix("www.")
    candidates = {site_key, bare_site}
    mapped = _SITE_ALIAS_DOMAINS.get(bare_site)
    if mapped:
        candidates.add(mapped)

    matched: list[str] = []
    for section in parser.sections():
        sec_lower = section.strip().lower()
        sec_bare = sec_lower.removeprefix("www.")
        if sec_lower in candidates or sec_bare in candidates:
            matched.append(section)
    return matched


def _pattern_matches_any(pattern: str, samples: tuple[str, ...]) -> bool:
    """Return True if regex `pattern` (case-insensitive) matches any sample string."""
    if not pattern:
        return False
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
        return any(compiled.search(sample) is not None for sample in samples)
    except re.error:
        lower_pat = pattern.lower()
        return any(sample.lower() in lower_pat for sample in samples)


def _append_unique_tag(tags: list[str], tag: str) -> None:
    """Append `tag` to `tags` if not already present (case-insensitive)."""
    lowered = tag.lower()
    if not any(existing.lower() == lowered for existing in tags):
        tags.append(tag)


def resolve_status_tags_from_ini(
    personal_ini_path: str,
    default_ini_path: str | None = None,
    site: str = "",
) -> tuple[list[str], list[str]]:
    """Auto-detect Calibre status include/exclude tags from FanFicFare INI files.

    Inspects ``include_subject_tags`` (and ``add_to_include_subject_tags``) across
    ``[defaults]``, site-specific sections, and ``[overrides]`` in ``defaults.ini``
    followed by ``personal.ini``, as well as ``replace_metadata`` /
    ``add_to_replace_metadata`` rules for custom status/oneshot tag mappings.

    Returns:
        ``(include_tags, exclude_tags)`` defaulting to
        ``(["In-Progress"], ["Completed", "Oneshot"])`` when ``status`` is included
        in ``include_subject_tags``, or ``([], ["Completed", "Oneshot"])`` when
        ``status`` was explicitly removed.
    """
    resolved_default = (
        default_ini_path
        if default_ini_path is not None
        else get_packaged_defaults_ini_path()
    )
    parsers = [
        p
        for p in (_parse_ini_file(resolved_default), _parse_ini_file(personal_ini_path))
        if p is not None
    ]

    subject_tags: set[str] | None = None
    replace_rule_blocks: list[str] = []

    for parser in parsers:
        section_order: list[str] = []
        if parser.has_section("defaults"):
            section_order.append("defaults")
        section_order.extend(_matching_site_sections(parser, site))
        if parser.has_section("overrides"):
            section_order.append("overrides")

        for section in section_order:
            if parser.has_option(section, "include_subject_tags"):
                raw_tags = parser.get(section, "include_subject_tags")
                subject_tags = {
                    tok.strip().lower() for tok in raw_tags.split(",") if tok.strip()
                }
            if parser.has_option(section, "add_to_include_subject_tags"):
                raw_add = parser.get(section, "add_to_include_subject_tags")
                added = {
                    tok.strip().lower() for tok in raw_add.split(",") if tok.strip()
                }
                if subject_tags is None:
                    subject_tags = {"status"} | added
                else:
                    subject_tags |= added

            for option_name in ("replace_metadata", "add_to_replace_metadata"):
                if parser.has_option(section, option_name):
                    replace_rule_blocks.append(parser.get(section, option_name))

    has_status = True if subject_tags is None else ("status" in subject_tags)
    include_tags: list[str] = ["In-Progress"] if has_status else []
    exclude_tags: list[str] = ["Completed", "Oneshot"]

    for block in replace_rule_blocks:
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            parts = line.split("=>")
            if len(parts) < 3:
                continue
            keys_raw = parts[0].split("&&", 1)[0]
            meta_keys = {k.strip().lower() for k in keys_raw.split(",") if k.strip()}
            if "status" not in meta_keys and "oneshot" not in meta_keys:
                continue

            pattern_raw = parts[1].strip()
            replacement_raw = parts[2].strip()
            replacement_tags = [
                cleaned
                for tok in _REPLACE_TAG_SPLIT_RE.split(replacement_raw)
                if (cleaned := tok.strip())
                and _REGEX_BACKREF_RE.search(cleaned) is None
            ]
            if not replacement_tags:
                continue

            if "oneshot" in meta_keys:
                for tag in replacement_tags:
                    _append_unique_tag(exclude_tags, tag)
                continue

            if _pattern_matches_any(
                pattern_raw, ("Completed", "Complete", "Oneshot", "Abandoned")
            ):
                for tag in replacement_tags:
                    _append_unique_tag(exclude_tags, tag)
            elif (
                has_status
                and len(replacement_tags) == 1
                and _pattern_matches_any(pattern_raw, ("In-Progress",))
                and replacement_tags[0].lower() != "in-progress"
            ):
                include_tags = [replacement_tags[0]]

    return (include_tags, exclude_tags)


__all__ = [
    "resolve_ini_path",
    "resolve_state_personal_ini",
    "resolve_state_default_ini",
    "get_packaged_defaults_ini_path",
    "read_ini_file_cached",
    "clear_ini_cache",
    "build_fff_configuration",
    "resolve_status_tags_from_ini",
]
