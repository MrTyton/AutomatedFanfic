"""URL pattern parsing, site catalogs, series expansion, and regex extraction."""

from parsers.regex_parsing import (
    check_failure_from_message,
    check_forceable_from_message,
    extract_filename,
    generate_FanficInfo_from_url,
    normalize_url,
)
from parsers.series import (
    FanFicFareAdapter,
    SeriesExpansionResult,
    expand_series_url,
    get_series_configuration,
    is_series_url,
    process_url,
)
from parsers.site_catalog import (
    clean_display_name_from_adapter,
    clean_display_name_from_domain,
    get_supported_sites_catalog,
)
from parsers.url_patterns import (
    generate_pattern_and_prefix,
    generate_site_identifier,
    generate_url_parsers_from_fanficfare,
)

__all__ = [
    "FanFicFareAdapter",
    "SeriesExpansionResult",
    "check_failure_from_message",
    "check_forceable_from_message",
    "clean_display_name_from_adapter",
    "clean_display_name_from_domain",
    "expand_series_url",
    "extract_filename",
    "generate_FanficInfo_from_url",
    "generate_pattern_and_prefix",
    "generate_site_identifier",
    "generate_url_parsers_from_fanficfare",
    "get_series_configuration",
    "get_supported_sites_catalog",
    "is_series_url",
    "normalize_url",
    "process_url",
]
