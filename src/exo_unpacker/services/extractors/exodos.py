import logging
import zipfile
from pathlib import Path
from typing import Any

from exo_unpacker.services.extractors.base import BaseExtractor

logger = logging.getLogger(__name__)


class EXoDOSExtractor(BaseExtractor):
    platform_image_dir: str = "MS-DOS"

    def extract_overlay_files(self, game_data: dict[str, Any], game_dir: Path) -> None:
        source_dir = Path(self.source_dir)
        game_dir = Path(game_dir)
        shortname = game_data["shortname"]

        dos_metadata_zip_subdir = self.release_config.get("dos_metadata_zip_subdir")
        if not dos_metadata_zip_subdir:
            logger.warning("  dos_metadata_zip_subdir not configured for this release, skipping overlay extraction.")
            return

        dos_metadata_zip = source_dir / dos_metadata_zip_subdir
        logger.info(f"  Extracting DOS configurations from {dos_metadata_zip}...")
        if not dos_metadata_zip.exists():
            raise FileNotFoundError(f"DOS metadata zip not found at: {dos_metadata_zip}")

        # The internal path prefix configuration inside !DOSmetadata.zip
        internal_prefix_tpl = self.release_config.get("zip_internal_prefix", "eXo/eXoDOS/!dos/{shortname}/")
        inner_prefix = internal_prefix_tpl.format(shortname=shortname)

        with zipfile.ZipFile(dos_metadata_zip, "r") as z:
            self._safe_extract_zip(z, game_dir, prefix=inner_prefix)

    def extract_extra_media(
        self,
        game_data: dict[str, Any],
        zip_filename: str,
        game_dir: Path,
        media_dir: Path,
        manuals_dir: Path,
        music_dir: Path,
        videos_dir: Path,
    ) -> tuple[str, str, dict[str, str]]:
        shortname = game_data["shortname"]
        source_dir = Path(self.source_dir)
        game_dir = Path(game_dir)
        media_dir = Path(media_dir)
        manuals_dir = Path(manuals_dir)
        music_dir = Path(music_dir)
        videos_dir = Path(videos_dir)

        manual_path_in_media = ""
        music_path_in_media = ""
        video_paths_in_media: dict[str, str] = {}

        # Default path for GameData zip
        gamedata_subdir = self.release_config.get("gamedata_zip_subdir", "eXoDOS/Content/GameData/eXoDOS")
        gamedata_zip_path = source_dir / gamedata_subdir / zip_filename

        if gamedata_zip_path.exists():
            logger.info(f"  Extracting extra game media from {gamedata_zip_path}...")
            with zipfile.ZipFile(gamedata_zip_path, "r") as z:
                # Internal prefix for Extras folder in GameData zip
                extras_prefix_tpl = self.release_config.get("zip_internal_prefix", "eXo/eXoDOS/!dos/{shortname}/")
                extras_prefix = extras_prefix_tpl.format(shortname=shortname) + "Extras/"

                for member in z.namelist():
                    # Handle Manuals
                    if member.startswith("Manuals/"):
                        if member.endswith("/"):
                            continue
                        filename = Path(member.replace("\\", "/")).name
                        dest = self._safe_extract_path(manuals_dir, filename)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(z.read(member))
                        manual_path_in_media = "./" + dest.relative_to(media_dir).as_posix()
                        logger.info(f"  Extracted manual: {filename}")

                    # Handle Music
                    elif member.startswith("Music/"):
                        if member.endswith("/"):
                            continue
                        filename = Path(member.replace("\\", "/")).name
                        dest = self._safe_extract_path(music_dir, filename)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(z.read(member))
                        music_path_in_media = "./" + dest.relative_to(media_dir).as_posix()
                        logger.info(f"  Extracted music: {filename}")

                    # Handle Videos
                    elif member.startswith("Videos/"):
                        if member.endswith("/"):
                            continue
                        filename = Path(member.replace("\\", "/")).name
                        dest = self._safe_extract_path(videos_dir, filename)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(z.read(member))

                        video_rel = "./" + dest.relative_to(media_dir).as_posix()
                        actual_key = "recordings"  # default if unknown

                        # E.g. "Videos/Trailer/game.mp4" -> type is "trailer"
                        parts = member.split("/")
                        if len(parts) >= 3:
                            subfolder = parts[1].lower()
                            if subfolder in [
                                "marquee",
                                "recordings",
                                "theme",
                                "trailer",
                            ]:
                                actual_key = subfolder

                        video_paths_in_media[actual_key] = video_rel
                        logger.info(f"  Extracted video ({actual_key}): {filename}")

                    elif member.startswith(extras_prefix):
                        if member.endswith("/"):
                            continue
                        rel_path = member[len(extras_prefix) :]
                        dest = self._safe_extract_path(game_dir / "Extras", rel_path)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(z.read(member))
                        logger.info(f"  Extracted extra: {rel_path}")

        return manual_path_in_media, music_path_in_media, video_paths_in_media
