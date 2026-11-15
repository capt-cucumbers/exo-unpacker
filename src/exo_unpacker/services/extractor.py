import logging
from pathlib import Path
from typing import Any

from exo_unpacker.core.config import Settings
from exo_unpacker.services.database import MetadataDatabase
from exo_unpacker.services.extractors.base import BaseExtractor
from exo_unpacker.services.extractors.exoappleiigs import EXoAppleIIGSExtractor
from exo_unpacker.services.extractors.exodos import EXoDOSExtractor
from exo_unpacker.services.extractors.exodreamm import EXoDREAMMExtractor
from exo_unpacker.services.extractors.exoscummvm import EXoScummVMExtractor
from exo_unpacker.services.extractors.exowin3x import EXoWin3xExtractor
from exo_unpacker.services.extractors.exowin9x import EXoWin9xExtractor

logger = logging.getLogger(__name__)

EXTRACTOR_REGISTRY: dict[str, type[BaseExtractor]] = {
    "exodos": EXoDOSExtractor,
    "exowin3x": EXoWin3xExtractor,
    "exoappleiigs": EXoAppleIIGSExtractor,
    "exoscummvm": EXoScummVMExtractor,
    "exodreamm": EXoDREAMMExtractor,
    "exowin9x": EXoWin9xExtractor,
}


class GameExtractor:
    """Main orchestrator for extracting games."""

    def __init__(self, config: Settings, db: MetadataDatabase, release_key: str | None = None) -> None:
        self.config: Settings = config
        self.db: MetadataDatabase = db
        self.release_key: str = release_key or self.config.default_release

    def _get_extractor_strategy(self) -> BaseExtractor:
        release_config = self.config.get_release_config(self.release_key)
        ext_type = release_config.get("extractor_type", "exodos")

        extractor_class = EXTRACTOR_REGISTRY.get(ext_type)
        if not extractor_class:
            raise ValueError(f"Unknown extractor type: {ext_type}")

        logger.debug(f"  Using extractor strategy '{ext_type}' for release '{self.release_key}'")
        return extractor_class(self.config, self.db, self.release_key)

    def extract_game(
        self,
        game_id_or_title: str,
        games_root: Path | None = None,
        metadata_root: Path | None = None,
        media_root: Path | None = None,
    ) -> dict[str, Any] | None:
        """
        Extract a game by its ID or title.
        Args:
            game_id_or_title: The game ID or exact title.
            games_root: Root directory for game files.
            metadata_root: Root directory for metadata.
            media_root: Root directory for media.
        Returns:
            The manifest entry for the extracted game.
        """
        strategy = self._get_extractor_strategy()
        return strategy.extract_game(
            game_id_or_title=game_id_or_title,
            games_root=games_root,
            metadata_root=metadata_root,
            media_root=media_root,
        )

    def clear_game(self, game_id_or_title: str) -> None:
        """
        Clear a game's extracted files and manifest entry.
        Args:
            game_id_or_title: The game ID or exact title.
        """
        strategy = self._get_extractor_strategy()
        return strategy.clear_game(game_id_or_title)
