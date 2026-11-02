"""Notification configuration schemas for Pushbullet and Apprise."""

from pydantic import BaseModel, Field, field_validator, model_validator


class PushbulletConfig(BaseModel):
    """Configuration model for Pushbullet notification service."""

    enabled: bool = Field(default=False, description="Enable Pushbullet notifications")
    api_key: str | None = Field(default=None, description="Pushbullet API key")
    device: str | None = Field(default=None, description="Target device name")

    @model_validator(mode="after")
    def validate_pushbullet(self) -> PushbulletConfig:
        """Validates Pushbullet configuration consistency."""
        if self.enabled and not self.api_key:
            raise ValueError("Pushbullet api_key is required when enabled=True")

        return self


class AppriseConfig(BaseModel):
    """Configuration model for Apprise notification services."""

    urls: list[str] = Field(
        default_factory=list, description="List of Apprise notification URLs"
    )

    @field_validator("urls")
    @classmethod
    def validate_urls(cls, v: object) -> list[str]:
        """Validates and normalizes the list of Apprise service URLs."""
        if not isinstance(v, list):
            raise ValueError("Apprise URLs must be a list")

        return [
            url.strip() for url in v if url and isinstance(url, str) and url.strip()
        ]
