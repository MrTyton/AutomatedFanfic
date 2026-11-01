"""Email configuration schema and validators."""

from __future__ import annotations

import ff_logging
from pydantic import BaseModel, Field, field_validator, model_validator


class EmailConfig(BaseModel):
    """Configuration model for email monitoring and authentication."""

    email: str = Field(
        default="", description="Email authentication (username or full email address)"
    )
    password: str = Field(default="", description="Email password or app password")
    server: str = Field(default="", description="IMAP server address")
    mailbox: str = Field(default="INBOX", description="Mailbox to monitor")
    sleep_time: int = Field(
        default=60, ge=1, description="Sleep time between checks in seconds"
    )
    disabled_sites: list[str] = Field(
        default_factory=list,
        description="List of site identifiers to disable processing for (notification only)",
    )
    imap_idle: bool = Field(
        default=False,
        description="Use IMAP IDLE push notifications instead of polling",
    )

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        """Validates and normalizes the email field."""
        return v.strip() if v else v

    @field_validator("server")
    @classmethod
    def validate_server(cls, v: str) -> str:
        """Validates and normalizes the server address."""
        return v.strip() if v else v

    @model_validator(mode="before")
    @classmethod
    def handle_legacy_ffnet_disable(cls, values: object) -> object:
        """Handle backward compatibility with old ffnet_disable configuration."""
        if isinstance(values, dict):
            if "ffnet_disable" in values and "disabled_sites" not in values:
                if values.get("ffnet_disable", False):
                    values["disabled_sites"] = ["fanfiction"]
                else:
                    values["disabled_sites"] = []
                values.pop("ffnet_disable", None)
                ff_logging.log(
                    "Migrating deprecated 'ffnet_disable' to 'disabled_sites'",
                    "WARNING",
                )
        return values

    def is_configured(self) -> bool:
        """Checks if email configuration is complete and ready for use."""
        return bool(self.email and self.password and self.server)
