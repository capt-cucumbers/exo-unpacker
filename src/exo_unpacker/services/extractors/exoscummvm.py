import logging
from pathlib import Path
from typing import Any

from exo_unpacker.services.extractors.base import BaseExtractor

logger = logging.getLogger(__name__)


class EXoScummVMExtractor(BaseExtractor):
    platform_image_dir: str = "ScummVM"

    def extract_overlay_files(self, game_data: dict[str, Any], game_dir: Path) -> None:
        # Extracts configurations from !ScummVMmetadata.zip
        self._extract_zip_overlay(
            game_data=game_data,
            game_dir=game_dir,
            config_key="dos_metadata_zip_subdir",
            default_zip_subdir="eXoScummVM/Content/!ScummVMmetadata.zip",
            default_prefix_tpl="eXo/eXoScummVM/!ScummVM/{shortname}/",
        )
