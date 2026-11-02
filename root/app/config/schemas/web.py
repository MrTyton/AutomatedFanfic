"""Web dashboard server configuration schema."""

from pydantic import BaseModel, Field, field_validator


class WebConfig(BaseModel):
    """Configuration for the web dashboard server."""

    enabled: bool = Field(default=False, description="Enable the web dashboard server")
    host: str = Field(default="0.0.0.0", description="Host address for the web server")
    port: int = Field(
        default=8080, ge=1, le=65535, description="Port for the web server"
    )
    history_db_path: str = Field(
        default="/data/history.db",
        description="Path to the SQLite history database file",
    )
    log_file_path: str = Field(
        default="/data/automatedfanfic.log",
        description="Path to the persistent rotating log file",
    )

    @field_validator("history_db_path")
    @classmethod
    def validate_history_db_path(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        # If no file extension, treat as directory and append default filename
        basename = v.rsplit("/", 1)[-1] if "/" in v else v
        if "." not in basename:
            v = v + "/history.db"
        return v

    @field_validator("log_file_path")
    @classmethod
    def validate_log_file_path(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        basename = v.rsplit("/", 1)[-1] if "/" in v else v
        if "." not in basename:
            v = v + "/automatedfanfic.log"
        return v
