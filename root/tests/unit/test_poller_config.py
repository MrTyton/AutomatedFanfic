"""Unit tests for library_poller configuration schema and TOML roundtrip."""

from pathlib import Path
import pytest
from pydantic import ValidationError

from config import (
    AppConfig,
    CalibreConfig,
    ConfigManager,
    EmailConfig,
    LibraryPollerConfig,
    SitePollerConfig,
)
from config.ini_resolver import resolve_status_tags_from_ini
from config.schemas import (
    LibraryPollerConfig as SchemasLibraryPollerConfig,
    SitePollerConfig as SchemasSitePollerConfig,
)
from config.schemas.poller import (
    LibraryPollerConfig as DirectLibraryPollerConfig,
    SitePollerConfig as DirectSitePollerConfig,
)


def test_reexports_match() -> None:
    """Verify LibraryPollerConfig and SitePollerConfig are consistently re-exported."""
    assert LibraryPollerConfig is SchemasLibraryPollerConfig
    assert LibraryPollerConfig is DirectLibraryPollerConfig
    assert SitePollerConfig is SchemasSitePollerConfig
    assert SitePollerConfig is DirectSitePollerConfig


def test_default_library_poller_config() -> None:
    """AppConfig loads with library_poller.enabled is False and sites == {}."""
    app_config = AppConfig(
        email=EmailConfig(email="user", password="pw", server="imap.example.com"),
        calibre=CalibreConfig(path="http://localhost:8080"),
    )

    assert isinstance(app_config.library_poller, LibraryPollerConfig)
    assert app_config.library_poller.enabled is False
    assert app_config.library_poller.library_sync_interval_hours == 6.0
    assert app_config.library_poller.tick_interval_seconds == 60.0
    assert app_config.library_poller.sites == {}


def test_site_poller_config_defaults() -> None:
    """SitePollerConfig defaults match specification."""
    site = SitePollerConfig()

    assert site.enabled is True
    assert site.include_tags == []
    assert site.exclude_tags == []
    assert site.calibre_search_override == ""
    assert site.max_checks_per_day == 24
    assert site.min_interval_minutes == 30.0
    assert site.hot_max_age_days == 14
    assert site.hot_interval_days == 1.5
    assert site.warm_max_age_days == 90
    assert site.warm_interval_days == 7.0
    assert site.cool_max_age_days == 365
    assert site.cool_interval_days == 21.0
    assert site.dormant_interval_days == 60.0
    assert site.jitter_ratio == 0.15
    assert site.max_error_backoff_days == 30.0


def test_site_poller_config_toml_roundtrip(tmp_path: Path) -> None:
    """Loading TOML with [library_poller] and [library_poller.sites.*] populates fields and normalizes site keys."""
    toml_content = """
[email]
email = "user@example.com"
password = "secret"
server = "imap.example.com"

[calibre]
path = "http://localhost:8080"

[library_poller]
enabled = true
library_sync_interval_hours = 12.0
tick_interval_seconds = 30.0

[library_poller.sites.fanfiction]
enabled = true
include_tags = ["In-Progress", "WIP"]
exclude_tags = ["Completed", "Oneshot", "Abandoned"]
calibre_search_override = "tags:=In-Progress"
max_checks_per_day = 24
min_interval_minutes = 30.0
hot_max_age_days = 14
hot_interval_days = 1.5
warm_max_age_days = 90
warm_interval_days = 7.0
cool_max_age_days = 365
cool_interval_days = 21.0
dormant_interval_days = 60.0
jitter_ratio = 0.15
max_error_backoff_days = 30.0

[library_poller.sites."  ArchiveOfOurOwn  "]
enabled = false
max_checks_per_day = 10
hot_interval_days = 2.0
"""
    config_file = tmp_path / "config.toml"
    config_file.write_text(toml_content, encoding="utf-8")

    ConfigManager.clear_cache()
    try:
        app_config = ConfigManager.load_config(config_file, force_reload=True)
    finally:
        ConfigManager.clear_cache()

    poller = app_config.library_poller
    assert poller.enabled is True
    assert poller.library_sync_interval_hours == 12.0
    assert poller.tick_interval_seconds == 30.0

    assert set(poller.sites.keys()) == {"fanfiction", "archiveofourown"}

    ffnet = poller.sites["fanfiction"]
    assert ffnet.enabled is True
    assert ffnet.include_tags == ["In-Progress", "WIP"]
    assert ffnet.exclude_tags == ["Completed", "Oneshot", "Abandoned"]
    assert ffnet.calibre_search_override == "tags:=In-Progress"
    assert ffnet.max_checks_per_day == 24
    assert ffnet.min_interval_minutes == 30.0
    assert ffnet.hot_max_age_days == 14
    assert ffnet.hot_interval_days == 1.5
    assert ffnet.warm_max_age_days == 90
    assert ffnet.warm_interval_days == 7.0
    assert ffnet.cool_max_age_days == 365
    assert ffnet.cool_interval_days == 21.0
    assert ffnet.dormant_interval_days == 60.0
    assert ffnet.jitter_ratio == 0.15
    assert ffnet.max_error_backoff_days == 30.0

    ao3 = poller.sites["archiveofourown"]
    assert ao3.enabled is False
    assert ao3.max_checks_per_day == 10
    assert ao3.hot_interval_days == 2.0


def test_site_key_normalization_rejects_empty_and_duplicates() -> None:
    """Empty/whitespace site keys and colliding normalized keys raise ValidationError."""
    with pytest.raises(ValidationError):
        LibraryPollerConfig(sites={"   ": SitePollerConfig()})

    with pytest.raises(ValidationError):
        LibraryPollerConfig(
            sites={
                "FanFiction": SitePollerConfig(),
                " fanfiction ": SitePollerConfig(),
            }
        )


def test_tier_age_ordering_validation() -> None:
    """Raises ValidationError if hot_max_age_days >= warm_max_age_days or warm_max_age_days >= cool_max_age_days."""
    # Equal hot and warm
    with pytest.raises(ValidationError):
        SitePollerConfig(
            hot_max_age_days=90, warm_max_age_days=90, cool_max_age_days=365
        )

    # hot > warm
    with pytest.raises(ValidationError):
        SitePollerConfig(
            hot_max_age_days=100, warm_max_age_days=90, cool_max_age_days=365
        )

    # Equal warm and cool
    with pytest.raises(ValidationError):
        SitePollerConfig(
            hot_max_age_days=14, warm_max_age_days=365, cool_max_age_days=365
        )

    # warm > cool
    with pytest.raises(ValidationError):
        SitePollerConfig(
            hot_max_age_days=14, warm_max_age_days=400, cool_max_age_days=365
        )

    # Valid strict ordering passes
    cfg = SitePollerConfig(hot_max_age_days=1, warm_max_age_days=2, cool_max_age_days=3)
    assert cfg.hot_max_age_days == 1
    assert cfg.warm_max_age_days == 2
    assert cfg.cool_max_age_days == 3


def test_budget_and_jitter_validation() -> None:
    """Raises ValidationError for max_checks_per_day < 1, min_interval_minutes <= 0, or jitter_ratio outside [0.0, 0.5]."""
    with pytest.raises(ValidationError):
        SitePollerConfig(max_checks_per_day=0)

    with pytest.raises(ValidationError):
        SitePollerConfig(max_checks_per_day=-5)

    with pytest.raises(ValidationError):
        SitePollerConfig(min_interval_minutes=0.0)

    with pytest.raises(ValidationError):
        SitePollerConfig(min_interval_minutes=-1.0)

    with pytest.raises(ValidationError):
        SitePollerConfig(jitter_ratio=-0.01)

    with pytest.raises(ValidationError):
        SitePollerConfig(jitter_ratio=0.51)

    # Boundary valid values
    cfg_low = SitePollerConfig(
        max_checks_per_day=1, min_interval_minutes=0.5, jitter_ratio=0.0
    )
    assert cfg_low.jitter_ratio == 0.0

    cfg_high = SitePollerConfig(jitter_ratio=0.5)
    assert cfg_high.jitter_ratio == 0.5


def test_positive_interval_bounds() -> None:
    """Poller and site intervals must be strictly positive."""
    with pytest.raises(ValidationError):
        LibraryPollerConfig(library_sync_interval_hours=0.0)

    with pytest.raises(ValidationError):
        LibraryPollerConfig(tick_interval_seconds=0.0)

    for field_name in (
        "hot_interval_days",
        "warm_interval_days",
        "cool_interval_days",
        "dormant_interval_days",
        "max_error_backoff_days",
    ):
        with pytest.raises(ValidationError):
            SitePollerConfig.model_validate({field_name: 0.0})


def test_resolve_status_tags_from_ini(tmp_path: Path) -> None:
    """Auto-detects include/exclude status tags from defaults.ini + personal.ini."""
    defaults_ini = tmp_path / "defaults.ini"
    defaults_ini.write_text(
        "[defaults]\n" "include_subject_tags: extratags, genre, category, status\n",
        encoding="utf-8",
    )

    # 1. Default behavior with no personal.ini
    inc, exc = resolve_status_tags_from_ini(
        personal_ini_path=str(tmp_path / "missing_personal.ini"),
        default_ini_path=str(defaults_ini),
    )
    assert inc == ["In-Progress"]
    assert exc == ["Completed", "Oneshot"]

    # 2. User removes status from include_subject_tags in personal.ini
    personal_no_status = tmp_path / "personal_no_status.ini"
    personal_no_status.write_text(
        "[defaults]\n" "include_subject_tags: extratags, genre, category\n",
        encoding="utf-8",
    )
    inc, exc = resolve_status_tags_from_ini(
        personal_ini_path=str(personal_no_status),
        default_ini_path=str(defaults_ini),
    )
    assert inc == []
    assert exc == ["Completed", "Oneshot"]

    # 3. Custom replace_metadata / add_to_replace_metadata mappings
    personal_custom = tmp_path / "personal_custom.ini"
    personal_custom.write_text(
        "[defaults]\n"
        "add_to_replace_metadata:\n"
        " oneshot=>Completed=>Completed\\,Oneshot\\,Standalone\n"
        " status=>^Completed$=>Finished\n"
        " status=>^In-Progress$=>WIP\n",
        encoding="utf-8",
    )
    inc, exc = resolve_status_tags_from_ini(
        personal_ini_path=str(personal_custom),
        default_ini_path=str(defaults_ini),
    )
    assert inc == ["WIP"]
    assert exc == ["Completed", "Oneshot", "Standalone", "Finished"]

    # 4. Site-specific section override
    personal_site = tmp_path / "personal_site.ini"
    personal_site.write_text(
        "[fanfiction.net]\n" "include_subject_tags: genre, category\n",
        encoding="utf-8",
    )
    inc_ff, exc_ff = resolve_status_tags_from_ini(
        personal_ini_path=str(personal_site),
        default_ini_path=str(defaults_ini),
        site="fanfiction",
    )
    assert inc_ff == []
    assert exc_ff == ["Completed", "Oneshot"]

    inc_ao3, exc_ao3 = resolve_status_tags_from_ini(
        personal_ini_path=str(personal_site),
        default_ini_path=str(defaults_ini),
        site="archiveofourown",
    )
    assert inc_ao3 == ["In-Progress"]
    assert exc_ao3 == ["Completed", "Oneshot"]

    # 5. [overrides] section takes highest precedence
    personal_overrides = tmp_path / "personal_overrides.ini"
    personal_overrides.write_text(
        "[defaults]\n"
        "include_subject_tags: genre, status\n"
        "[overrides]\n"
        "include_subject_tags: genre\n",
        encoding="utf-8",
    )
    inc_ov, _exc_ov = resolve_status_tags_from_ini(
        personal_ini_path=str(personal_overrides),
        default_ini_path=str(defaults_ini),
    )
    assert inc_ov == []
