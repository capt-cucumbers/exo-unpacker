import contextlib
import json
import logging
import os
import shutil
import sys
import tomllib
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# --- Platform Setup ---


def enable_ansi_utf8() -> None:
    """Enable ANSI escape sequences and UTF-8 output on Windows consoles."""
    if sys.platform != "win32":
        return
    os.system("")
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]


# --- File I/O ---


def read_toml(path: str | Path | None, default: Any = None) -> Any:
    """Load data from a TOML file with specified fallback."""
    fallback = {} if default is None else default
    if not path:
        return fallback

    p = Path(path)
    if not p.exists():
        return fallback

    try:
        with p.open("rb") as f:
            return tomllib.load(f)
    except Exception as e:
        logger.error(f"Failed to read TOML from {path}: {e}")

    return fallback


def read_json(path: str | Path | None, default: Any = None) -> Any:
    """Load data from a JSON file with specified fallback."""
    fallback = {} if default is None else default
    if not path:
        return fallback

    p = Path(path)
    if not p.exists():
        return fallback

    try:
        with p.open("r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read JSON from {path}: {e}")

    return fallback


def save_json(data: Any, path: Path | str, **kwargs: Any) -> None:
    """Serialize data to disk atomically (tmp file + replace), raising on failure."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = p.with_suffix(".tmp")

    kwargs.setdefault("indent", 4)
    kwargs.setdefault("ensure_ascii", False)
    kwargs.setdefault("sort_keys", True)

    try:
        tmp_path.write_text(json.dumps(data, **kwargs), encoding="utf-8")
        tmp_path.replace(p)
    except Exception as e:
        logger.error(f"Failed to save JSON file {path}: {e}")
        tmp_path.unlink(missing_ok=True)
        raise


def backup_file(path: str | Path | None) -> bool:
    """Create a .bak redundancy copy of a file if it exists."""
    if not path:
        return False

    p = Path(path)
    if not p.exists():
        return False

    try:
        backup_p = p.with_suffix(p.suffix + ".bak")
        shutil.copyfile(p, backup_p)
        logger.info(f"Successfully created backup: {backup_p}")
        return True
    except Exception as e:
        logger.error(f"Failed to backup file {path}: {e}")

    return False


def get_safe_filename(filename: str, illegal_char_override: list[str] | None = None, replacement_char: str = "") -> str:
    """Sanitize a filename by stripping Windows-illegal characters and trailing dots."""
    illegal_chars = ["<", ">", ":", '"', "/", "\\", "|", "?", "*"]
    if illegal_char_override:
        illegal_chars = illegal_char_override
    cleaned_name = filename
    for char in illegal_chars:
        cleaned_name = cleaned_name.replace(char, replacement_char)
    return cleaned_name.strip().rstrip(".")
