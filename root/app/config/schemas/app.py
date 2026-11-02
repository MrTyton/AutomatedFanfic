"""Root application configuration model combining all subsystem schemas."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from config.schemas.calibre import CalibreConfig
from config.schemas.email import EmailConfig
from config.schemas.notifications import AppriseConfig, PushbulletConfig
from config.schemas.process import ProcessConfig
from config.schemas.retry import RetryConfig
from config.schemas.web import WebConfig
import ff_logging

_active_toml_data: ContextVar[dict[str, Any] | None] = ContextVar(
    "_active_toml_data", default=None
)


@contextmanager
def toml_settings_context(data: dict[str, Any]) -> Iterator[None]:
    """Context manager providing parsed TOML settings to AppConfig initialization."""
    token = _active_toml_data.set(data)
    try:
        yield
    finally:
        _active_toml_data.reset(token)


def _normalize_ffdl_env_vars(
    raw_vars: Mapping[str, str | None], sections: set[str]
) -> dict[str, str | None]:
    """Normalize single-underscore FFDL_SECTION_FIELD keys to FFDL_SECTION__FIELD."""
    normalized: dict[str, str | None] = {}
    for key, val in raw_vars.items():
        if key.startswith("ffdl_") and "__" not in key[5:]:
            suffix = key[5:]
            if "_" in suffix:
                sec, field = suffix.split("_", 1)
                if sec in sections:
                    key = f"ffdl_{sec}__{field}"
        normalized[key] = val
    return normalized


class FFDLEnvSettingsSource(EnvSettingsSource):
    """Pydantic-settings environment source supporting both FFDL_SECTION__FIELD and FFDL_SECTION_FIELD."""

    def _load_env_vars(self) -> Mapping[str, str | None]:
        return _normalize_ffdl_env_vars(
            super()._load_env_vars(), set(self.settings_cls.model_fields.keys())
        )

    def prepare_field_value(
        self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool
    ) -> Any:
        is_complex = value_is_complex or self._field_is_complex(field)[0]
        if isinstance(value, str) and not value.strip() and is_complex:
            return []
        return super().prepare_field_value(field_name, field, value, value_is_complex)

    def decode_complex_value(
        self, field_name: str, field: FieldInfo, value: Any
    ) -> Any:
        try:
            return super().decode_complex_value(field_name, field, value)
        except ValueError:
            if isinstance(value, str):
                return [item.strip() for item in value.split(",") if item.strip()]
            raise


class FFDLDotEnvSettingsSource(DotEnvSettingsSource):
    """Pydantic-settings dotenv source supporting both FFDL_SECTION__FIELD and FFDL_SECTION_FIELD."""

    def _load_env_vars(self) -> Mapping[str, str | None]:
        return _normalize_ffdl_env_vars(
            super()._load_env_vars(), set(self.settings_cls.model_fields.keys())
        )

    def prepare_field_value(
        self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool
    ) -> Any:
        is_complex = value_is_complex or self._field_is_complex(field)[0]
        if isinstance(value, str) and not value.strip() and is_complex:
            return []
        return super().prepare_field_value(field_name, field, value, value_is_complex)

    def decode_complex_value(
        self, field_name: str, field: FieldInfo, value: Any
    ) -> Any:
        try:
            return super().decode_complex_value(field_name, field, value)
        except ValueError:
            if isinstance(value, str):
                return [item.strip() for item in value.split(",") if item.strip()]
            raise


class TomlDictSettingsSource(PydanticBaseSettingsSource):
    """Settings source reading from the active TOML configuration dictionary."""

    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
        data = _active_toml_data.get()
        if not data:
            return None, field_name, False
        return data.get(field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        data = _active_toml_data.get()
        return dict(data) if data else {}


class AppConfig(BaseSettings):
    """Main application configuration container and validator."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        env_prefix="FFDL_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            FFDLEnvSettingsSource(settings_cls),
            FFDLDotEnvSettingsSource(
                settings_cls,
                env_file=settings_cls.model_config.get("env_file"),
                env_file_encoding=settings_cls.model_config.get("env_file_encoding"),
            ),
            TomlDictSettingsSource(settings_cls),
            file_secret_settings,
        )

    # Configuration sections
    email: EmailConfig
    calibre: CalibreConfig
    pushbullet: PushbulletConfig = Field(default_factory=PushbulletConfig)
    apprise: AppriseConfig = Field(default_factory=AppriseConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    process: ProcessConfig = Field(default_factory=ProcessConfig)
    web: WebConfig = Field(default_factory=WebConfig)

    # Application settings
    version: str = Field(default="6.16.2", description="Application version")

    @property
    def resume_uncompleted_on_startup(self) -> bool:
        return self.retry.resume_uncompleted_on_startup

    @property
    def max_workers(self) -> int:
        return self.process.max_workers

    @max_workers.setter
    def max_workers(self, value: int) -> None:
        self.process.max_workers = value

    @model_validator(mode="after")
    def validate_cross_sections(self) -> AppConfig:
        """Validates cross-section dependencies and local paths."""
        if self.calibre and self.calibre.path:
            path_str = self.calibre.path.strip()
            if not path_str.startswith(("http://", "https://")):
                calibre_path = Path(path_str)
                if not calibre_path.exists():
                    ff_logging.log(
                        f"Warning: Calibre library path does not exist: {path_str}\n"
                        "Please ensure the path is correct or the library is accessible.",
                        "WARNING",
                    )

        return self
