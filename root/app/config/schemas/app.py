"""Root application configuration model combining all subsystem schemas."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
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


class FFDLEnvSettingsSource(EnvSettingsSource):
    """Pydantic-settings environment source supporting both FFDL_SECTION__FIELD and FFDL_SECTION_FIELD."""

    def _load_env_vars(self) -> Mapping[str, str | None]:
        raw_vars = super()._load_env_vars()
        normalized: dict[str, str | None] = {}
        sections = set(self.settings_cls.model_fields.keys())
        for key, val in raw_vars.items():
            if key.startswith("ffdl_") and "__" not in key[5:]:
                suffix = key[5:]
                if "_" in suffix:
                    sec, field = suffix.split("_", 1)
                    if sec in sections:
                        key = f"ffdl_{sec}__{field}"
            normalized[key] = val
        return normalized

    def decode_complex_value(
        self, field_name: str, field: FieldInfo, value: Any
    ) -> Any:
        try:
            return super().decode_complex_value(field_name, field, value)
        except ValueError:
            if isinstance(value, str):
                return [item.strip() for item in value.split(",") if item.strip()]
            raise


class AppConfig(BaseSettings):
    """Main application configuration container and validator."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
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
            FFDLEnvSettingsSource(settings_cls),
            init_settings,
            dotenv_settings,
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
    version: str = Field(default="1.3.23", description="Application version")

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
