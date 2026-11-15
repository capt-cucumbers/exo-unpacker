import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from exo_unpacker.core.utils import read_json, save_json

logger = logging.getLogger(__name__)


class ManifestManager:
    """Manages the manifest JSON file tracking extracted games."""

    def __init__(self, manifest_path: Path | str) -> None:
        self.manifest_path: Path = Path(manifest_path)
        self.data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Load the manifest data from disk."""
        self.data = read_json(self.manifest_path)
        logger.debug(f"  Loaded manifest from {self.manifest_path}")

    def save(self) -> None:
        """Save the manifest data to disk."""
        try:
            save_json(self.data, self.manifest_path)
            logger.debug(f"  Saved manifest to {self.manifest_path}")
        except Exception as e:
            logger.error(f"  Failed to save manifest to {self.manifest_path}: {e}")
            raise

    def update_game(
        self,
        game_id: str,
        game_dict: dict[str, Any],
        metadata_dict: dict[str, Any],
        media_dict: dict[str, Any],
        platform: str = "MS-DOS",
        game_source: str = "exodos",
    ) -> dict[str, Any]:
        """Update or create a game entry conforming to the v2 manifest schema."""
        existing = self.data.get(game_id, {})

        now_iso = datetime.now().isoformat()
        global_id = existing.get("global_id") or game_dict.get("global_id") or str(uuid.uuid4())
        added_at = existing.get("added_at") or game_dict.get("added_at") or now_iso
        updated_at = (
            game_dict.get("updated_at") or metadata_dict.get("updated_at") or media_dict.get("updated_at") or now_iso
        )

        custom_fields = list(game_dict.get("custom_fields", []))
        if game_dict.get("source_licence") and not any(cf.get("name") == "Source Licence" for cf in custom_fields):
            custom_fields.append({"name": "Source Licence", "value": game_dict["source_licence"]})

        entry = {
            "global_id": global_id,
            "game_id": game_id,
            "game_source": game_source,
            "platform": platform,
            "game_name": game_dict.get("game_name", ""),
            "game_folder": game_dict.get("game_folder", ""),
            "game_dir": game_dict.get("game_dir", ""),
            "game_version": game_dict.get("game_version", ""),
            "application_path": game_dict.get("application_path", ""),
            "application_arguments": game_dict.get("application_arguments", ""),
            "config_app_path": game_dict.get("config_app_path", ""),
            "config_app_arguments": game_dict.get("config_app_arguments", ""),
            "is_installed": game_dict.get("is_installed", True),
            "is_favorite": game_dict.get("is_favorite", False),
            "is_broken": game_dict.get("is_broken", False),
            "is_portable": game_dict.get("is_portable", False),
            "is_hidden": game_dict.get("is_hidden", False),
            "use_dosbox": game_dict.get("use_dosbox", False),
            "dosbox_config_path": game_dict.get("dosbox_config_path", ""),
            "dosbox_version_path": game_dict.get("dosbox_version_path", ""),
            "status": game_dict.get("status", "extracted"),
            "progress": str(game_dict.get("progress", "")),
            "metadata_source": game_dict.get("metadata_source", game_source),
            "metadata_id": game_dict.get("metadata_id", game_id),
            "media_source": game_dict.get("media_source", game_source),
            "media_id": game_dict.get("media_id", game_id),
            "metadata": metadata_dict,
            "media": media_dict,
            "addl_apps": game_dict.get("addl_apps", []),
            "custom_fields": custom_fields,
            "extras": game_dict.get("extras", {}),
            "added_at": added_at,
            "updated_at": updated_at,
        }

        if existing != entry:
            self.data[game_id] = entry
            self.save()

        return entry

    def remove_game(self, game_id: str) -> bool:
        """
        Removes a game entry from the manifest.
        Args:
            game_id: The ID of the game to remove.
        Returns:
            True if removed, False if not found.
        """
        removed = self.data.pop(game_id, None) is not None
        if removed:
            self.save()
        return removed
