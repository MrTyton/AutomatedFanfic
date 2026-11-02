"""Calibre configuration schema and preservation modes."""

from enum import Enum
from pathlib import Path
from typing import Literal

import ff_logging
from pydantic import BaseModel, Field, field_validator, model_validator


class MetadataPreservationMode(str, Enum):
    """Enumeration of metadata preservation strategies for Calibre updates."""

    REMOVE_ADD = "remove_add"
    PRESERVE_METADATA = "preserve_metadata"
    ADD_FORMAT = "add_format"


UpdateMethod = Literal["update", "update_always", "force", "update_no_force"]


class CalibreConfig(BaseModel):
    """Configuration model for Calibre e-book library integration."""

    path: str = Field(default="", description="Path to Calibre library or server URL")
    username: str | None = Field(default=None, description="Calibre username")
    password: str | None = Field(default=None, description="Calibre password")
    default_ini: str | None = Field(
        default=None, description="Path to defaults.ini file"
    )
    personal_ini: str | None = Field(
        default=None, description="Path to personal.ini file"
    )
    update_method: UpdateMethod = Field(
        default="update",
        description="Fanficfare update method: 'update', 'update_always', 'force', or 'update_no_force'",
    )
    metadata_preservation_mode: MetadataPreservationMode = Field(
        default=MetadataPreservationMode.REMOVE_ADD,
        description="Metadata preservation strategy: 'remove_add', 'preserve_metadata', or 'add_format'",
    )
    update_only: bool = Field(
        default=False,
        description="Only update stories already in Calibre; drop emailed URLs for new stories",
    )

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        """Validates Calibre library path or server URL."""
        if not v or not v.strip():
            return v

        path_str = v.strip()
        if "://" in path_str or path_str.startswith("http"):
            return path_str

        path_obj = Path(path_str)
        if not path_obj.exists():
            ff_logging.log_debug(
                f"Warning: Calibre path {path_str} does not exist locally"
            )

        return path_str

    @model_validator(mode="after")
    def validate_authentication(self) -> CalibreConfig:
        """Validates authentication credential consistency."""
        if self.username and not self.password:
            ff_logging.log_debug("Warning: Username provided without password")
        elif self.password and not self.username:
            ff_logging.log_debug("Warning: Password provided without username")

        return self

    def is_configured(self) -> bool:
        """Checks if Calibre configuration is complete and ready for use."""
        return bool(self.path and self.path.strip())
