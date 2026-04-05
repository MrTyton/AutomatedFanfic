"""Atomic TOML file writer with backup support.

Uses tomlkit to preserve comments and formatting in user-edited config files.
All writes go through a temp-file → rename dance for crash safety.
"""

import shutil
import tempfile
from pathlib import Path

import tomlkit
import tomllib


class TomlWriter:
    """Read, modify, and atomically write TOML config files."""

    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path)

    def read_raw(self) -> dict:
        """Read current TOML as a plain dict (stdlib tomllib)."""
        with open(self.config_path, "rb") as f:
            return tomllib.load(f)

    def read_tomlkit(self) -> tomlkit.TOMLDocument:
        """Read current TOML preserving comments/formatting (tomlkit)."""
        with open(self.config_path, encoding="utf-8") as f:
            return tomlkit.load(f)

    def backup(self) -> Path:
        """Copy the current file to ``<name>.toml.bak``. Returns backup path."""
        backup_path = self.config_path.with_suffix(".toml.bak")
        shutil.copy2(self.config_path, backup_path)
        return backup_path

    def write_section(self, section: str, values: dict) -> Path:
        """Merge *values* into *section*, back up the old file, write atomically.

        Returns the backup path so callers can roll back if needed.
        """
        doc = self.read_tomlkit()
        backup_path = self.backup()

        if section in doc:
            for key, value in values.items():
                doc[section][key] = value
        else:
            doc[section] = values

        self._atomic_write(doc)
        return backup_path

    def _atomic_write(self, doc: tomlkit.TOMLDocument) -> None:
        """Write *doc* to a temp file in the same directory, then rename."""
        parent = self.config_path.parent
        parent.mkdir(parents=True, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(dir=parent, prefix=".config_", suffix=".tmp")
        try:
            with open(fd, "w", encoding="utf-8") as f:
                f.write(tomlkit.dumps(doc))
            # Atomic rename (same filesystem)
            Path(tmp_path).replace(self.config_path)
        except Exception:
            # Clean up temp file on failure
            Path(tmp_path).unlink(missing_ok=True)
            raise
