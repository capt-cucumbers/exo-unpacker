import logging
import re
import shutil
import string
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from exo_unpacker.core.config import Settings
from exo_unpacker.core.utils import get_safe_filename, read_json, save_json
from exo_unpacker.models import ReleaseConfig
from exo_unpacker.services.database import MetadataDatabase
from exo_unpacker.services.image_processor import ImageProcessor
from exo_unpacker.services.manifest import ManifestManager

logger = logging.getLogger(__name__)

# Module-level compiled patterns (avoids recompiling on every call)
_RE_YEAR_SUFFIX: re.Pattern[str] = re.compile(r"\s*\(\d{4}\)")
_RE_GAMEDIR: re.Pattern[str] = re.compile(r"(?i)for %%I in \(\.\) do set GameDir=%%~nxI")
_RE_GAMENAME_BLOCK: re.Pattern[str] = re.compile(
    r"(?i)for %%f in \(\*\^\)\.bat\) do set GameName2=%%f\r?\n"
    r"set GameName=%GameName2:~0,-4%\r?\n"
    r"set IndexName=%GameName:~0,-7%"
)
_RE_UTIL_PATH: re.Pattern[str] = re.compile(r"\.\.\\\.\.\\\.\.\\util")
_RE_THREE_CD: re.Pattern[str] = re.compile(r"(?m)^cd \.\.\r?\ncd \.\.\r?\ncd \.\.")
_RE_CALL_INSTALL: re.Pattern[str] = re.compile(r"(?i)call install\.bat")


def _now_iso() -> str:
    return datetime.now().isoformat()


class BaseExtractor:
    """Base class for all extraction strategies."""

    platform_image_dir: str = ""

    def __init__(self, config: Settings, db: MetadataDatabase, release_key: str | None = None) -> None:
        self.config: Settings = config
        self.db: MetadataDatabase = db
        self.release_key: str = release_key or self.config.default_release
        self.image_processor: ImageProcessor = ImageProcessor()
        self.manifest_manager: ManifestManager = ManifestManager(self.config.get_manifest_path(self.release_key))

        release_config = self.config.get_release_config(self.release_key)
        self.release_config: ReleaseConfig = release_config
        self.platform: str | None = release_config.get("platform")
        self.source: str | None = release_config.get("source")
        self.game_source: str = str(release_config.get("extractor_type") or "").strip().lower()
        self.source_dir: Path = Path(release_config["source_dir"])
        self.game_zips_subdir: str = release_config["game_zips_subdir"]

        if not self.platform or not self.game_source:
            raise ValueError("Release configuration must define 'platform' and 'extractor_type'.")

        self.ignores_path: Path | None = self.config.resolve_release_path("ignores_path", self.release_key)
        self.overrides_path: Path | None = self.config.resolve_release_path("overrides_path", self.release_key)
        self._ignores_data: Any = None
        self._overrides_data: Any = None

    @staticmethod
    def _safe_extract_path(dest_root: Path, rel_member: str) -> Path:
        """Resolve rel_member under dest_root or raise ValueError on path traversal."""
        normalized = rel_member.replace("\\", "/")
        if normalized.startswith("/") or (len(normalized) >= 2 and normalized[1] == ":" and normalized[0].isalpha()):
            raise ValueError(f"Unsafe archive member path: {rel_member}")
        parts = [part for part in normalized.split("/") if part and part != "."]
        if any(part == ".." for part in parts) or not parts:
            raise ValueError(f"Unsafe archive member path: {rel_member}")
        root_resolved = dest_root.resolve()
        target = root_resolved.joinpath(*parts).resolve()
        if target == root_resolved or not target.is_relative_to(root_resolved):
            raise ValueError(f"Archive member escapes target directory: {rel_member}")
        return target

    @classmethod
    def _safe_extract_zip(
        cls,
        z: zipfile.ZipFile,
        dest_root: Path,
        members: list[str] | None = None,
        prefix: str = "",
    ) -> None:
        """Safely extract selected zip members under dest_root with path-traversal guards."""
        dest_root.mkdir(parents=True, exist_ok=True)
        selected = members if members is not None else z.namelist()
        targets: list[tuple[str, Path, bool]] = []
        for member in selected:
            if prefix:
                if not member.startswith(prefix):
                    continue
                rel_path = member[len(prefix) :]
                if not rel_path:
                    continue
            else:
                rel_path = member

            if member.endswith("/"):
                if not rel_path.strip("/"):
                    continue
                dest = cls._safe_extract_path(dest_root, rel_path)
                targets.append((member, dest, True))
            else:
                dest = cls._safe_extract_path(dest_root, rel_path)
                targets.append((member, dest, False))

        for member, dest, is_dir in targets:
            if is_dir:
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(member))

    @staticmethod
    def _strip_exo_suffixes(filename: str) -> str:
        stem = filename.rsplit(".", 1)[0]
        ext = filename.rsplit(".", 1)[1] if "." in filename else ""
        stem = re.sub(r"-front$", "", stem, flags=re.IGNORECASE)
        stem = re.sub(r"-back$", "", stem, flags=re.IGNORECASE)
        return f"{stem}.{ext}" if ext else stem

    @staticmethod
    def _launchbox_matches(filename: str, game_id: str | None, title: str | None, rom_name: str | None) -> bool:
        game_id = (game_id or "").lower()
        title = title or ""
        rom_name = (rom_name or "").rsplit(".", 1)[0].lower()

        def sanitize_for_exact_match(text: str) -> str:
            return re.sub(r'[<>:"/\\|?*\']+', "_", text).lower()

        def sanitize_for_stripped_match(text: str) -> str:
            text = re.sub(r"\([^)]*\)", "", text)
            text = re.sub(r"\[[^]]*\]", "", text)
            text = re.sub(r"\{[^}]*\}", "", text)
            text = text.lower()
            words = text.split()
            words = [w for w in words if w not in ("a", "an", "and", "the")]
            text = " ".join(words)
            return re.sub(r"[!\-.&',:\"/\\?\s]", "", text)

        stem = filename.rsplit(".", 1)[0].lower()

        # 1. Match Game ID
        if game_id and game_id in stem:
            return True

        stem_no_suffix = re.sub(r"-\d+$", "", stem)

        # 2. Match exact title
        if stem_no_suffix == sanitize_for_exact_match(title):
            return True

        # 3. Match ROM / application filename
        if rom_name and stem_no_suffix == rom_name:
            return True

        # 4. Match stripped title
        stripped_stem = sanitize_for_stripped_match(stem)
        stripped_title = sanitize_for_stripped_match(title)
        return bool(stripped_stem and stripped_stem == stripped_title)

    @property
    def ignores(self) -> Any:
        """Get the list of ignored game IDs."""
        if self._ignores_data is None:
            self._ignores_data = read_json(self.ignores_path, default=[])
        return self._ignores_data

    @property
    def overrides(self) -> Any:
        """Get the overrides dictionary."""
        if self._overrides_data is None:
            self._overrides_data = read_json(self.overrides_path, default={})
        return self._overrides_data

    def extract_game(
        self,
        game_id_or_title: str,
        games_root: Path | None = None,
        metadata_root: Path | None = None,
        media_root: Path | None = None,
    ) -> dict[str, Any] | None:
        """Extract a game and process its metadata and media."""
        game_data = self._require_game(game_id_or_title)
        game_id = game_data["id"]

        if game_id in self.ignores:
            logger.info(f"  Skipping extraction for {game_id}: Game is ignored.")
            return None

        games_root = Path(games_root or self.release_config["games_root_dir"])
        metadata_root = Path(metadata_root or self.release_config["metadata_root_dir"])
        media_root = Path(media_root or self.release_config["media_root_dir"])

        shortname = game_data["shortname"]
        title = game_data["title"]
        bat_name = game_data["bat_name"]

        if not shortname or not bat_name:
            logger.warning(f"  Skipping {game_id}: Game data has invalid launch paths. Title: '{title}'")
            return None

        now_iso = datetime.now().isoformat()
        existing_entry = self.manifest_manager.data.get(game_id, {})
        global_id = existing_entry.get("global_id") or str(uuid.uuid4())
        added_at = existing_entry.get("added_at") or now_iso
        metadata_added_at = existing_entry.get("metadata", {}).get("added_at") or now_iso
        media_added_at = existing_entry.get("media", {}).get("added_at") or now_iso

        folder_name = self._get_folder_name(game_data)
        if game_id in self.overrides:
            override_data = self.overrides[game_id].get("overrides", {})
            if "title" in override_data:
                title = override_data["title"]

        try:
            game_zip_path = self._locate_and_stage_zip(bat_name, folder_name, games_root)
        except Exception as e:
            logger.error(f"  Failed to locate or stage zip for {title}: {e}")
            raise

        game_dir = games_root / folder_name
        game_dir.mkdir(parents=True, exist_ok=True)

        try:
            self._extract_tools()
            self.extract_overlay_files(game_data, game_dir)
        except Exception as e:
            logger.error(f"  Failed to extract tools or overlay for {title}: {e}")
            raise

        metadata_dir, media_dir, media_subdirs = self._setup_output_dirs(folder_name, metadata_root, media_root)

        processed_images = self.extract_and_process_images(
            game_data=game_data,
            raw_images_dir=media_subdirs["raw_images"],
            processed_images_dir=media_subdirs["processed_images"],
        )

        manual_path, music_path, video_paths = self.extract_extra_media(
            game_data=game_data,
            zip_filename=Path(game_zip_path).name,
            game_dir=game_dir,
            media_dir=media_dir,
            manuals_dir=media_subdirs["manuals"],
            music_dir=media_subdirs["music"],
            videos_dir=media_subdirs["videos"],
        )

        game_info = self._build_game_info(
            game_data,
            game_dir,
            global_id,
            game_id,
            title,
            shortname,
            added_at,
            now_iso,
        )
        metadata_info = self._build_metadata_info(
            game_data,
            game_id,
            title,
            metadata_dir,
            metadata_added_at,
            now_iso,
        )
        media_info = self._build_media_info(
            game_id,
            media_dir,
            processed_images,
            video_paths,
            music_path,
            manual_path,
            media_added_at,
            now_iso,
        )

        save_json(game_info, game_dir / "!game.info")
        save_json(metadata_info, metadata_dir / "!metadata.info")
        save_json(media_info, media_dir / "!media.info")
        logger.info(f"  Wrote .info files for {title}")

        manifest_entry = self.manifest_manager.update_game(
            game_id=game_id,
            game_dict=game_info,
            metadata_dict=metadata_info,
            media_dict=media_info,
            platform=self.platform,
            game_source=self.game_source,
        )
        logger.info(f"  Manifest registered for {title}")

        self._apply_bat_templates(
            game_data=game_data,
            game_dir=game_dir,
            bat_name=bat_name,
            game_zip_path=game_zip_path,
            shortname=shortname,
        )

        return manifest_entry

    def clear_game(self, game_id_or_title: str) -> None:
        """Clear a game's extracted files and manifest entry."""
        game_data = self._require_game(game_id_or_title)
        game_id = game_data["id"]
        title = game_data["title"]

        logger.info(f"  Clearing game: {title} ({game_id})...")

        manifest_entry = self.manifest_manager.data.get(game_id)
        if manifest_entry:
            game_dir = Path(manifest_entry["game_dir"]) if manifest_entry.get("game_dir") else None
            metadata_dir = (
                Path(manifest_entry["metadata"]["metadata_dir"])
                if manifest_entry.get("metadata", {}).get("metadata_dir")
                else None
            )
            media_dir = (
                Path(manifest_entry["media"]["media_dir"]) if manifest_entry.get("media", {}).get("media_dir") else None
            )
        else:
            folder_name = self._get_folder_name(game_data)
            game_dir = Path(self.release_config["games_root_dir"]) / folder_name if folder_name else None
            metadata_dir = Path(self.release_config["metadata_root_dir"]) / folder_name if folder_name else None
            media_dir = Path(self.release_config["media_root_dir"]) / folder_name if folder_name else None

        for label, directory in (
            ("game", game_dir),
            ("metadata", metadata_dir),
            ("media", media_dir),
        ):
            if directory and directory.exists():
                try:
                    shutil.rmtree(directory)
                    logger.info(f"  Deleted {label} directory: {directory}")
                except Exception as exc:
                    logger.error(f"  Failed to delete {label} directory {directory}: {exc}")

        if self.manifest_manager.remove_game(game_id):
            logger.info(f"  Removed manifest entry for {title}")
        else:
            logger.info(f"  No manifest entry to remove for {title}")

    # --- BAT patching ---

    def _apply_bat_templates(
        self, game_data: dict[str, Any], game_dir: Path, bat_name: str, game_zip_path: Path, shortname: str
    ) -> None:
        game_dir = Path(game_dir)
        template_vars = {
            "util_dir": self.release_config.get("util_root_dir", ""),
            "games_root_dir": self.release_config.get("games_root_dir", ""),
            "game_zip_path": str(game_zip_path),
            "shortname": shortname,
        }

        setup_tpl_path = self.config.get_template_path("setup_template", self.release_key)
        if setup_tpl_path and Path(setup_tpl_path).exists():
            self._render_template(setup_tpl_path, game_dir / "!config.bat", template_vars)
            logger.info("  Written !config.bat from template.")
        else:
            logger.debug("  No setup_template configured; skipping !config.bat.")

        orig_bat = game_dir / bat_name
        if bat_name and orig_bat.exists():
            self._patch_launch_bat(orig_bat, game_dir / "!launch.bat", shortname, bat_name)

        # Remove original overlay bats
        for orig_name in (bat_name, Path(game_data.get("configuration_path", "")).name):
            if not orig_name:
                continue
            orig = game_dir / orig_name
            if orig.exists() and orig.name not in ("!launch.bat", "!config.bat"):
                try:
                    orig.unlink()
                    logger.info(f"  Removed original overlay bat: {orig.name}")
                except Exception as exc:
                    logger.warning(f"  Failed to remove original overlay bat {orig.name}: {exc}")

    def _patch_launch_bat(self, orig_bat: Path, dest: Path, shortname: str, bat_name: str) -> None:
        """
        Apply all regex patches to the original bat and write it as !launch.bat.
        Args:
            orig_bat: The original batch file path.
            dest: The destination path for the patched batch file.
            shortname: The shortname of the game.
            bat_name: The original name of the batch file.
        """
        try:
            content = orig_bat.read_text(encoding="cp437")
        except Exception as exc:
            logger.error(f"  Failed to read {orig_bat}: {exc}")
            return

        bat_basename = Path(bat_name).stem
        bat_basename_no_year = _RE_YEAR_SUFFIX.sub("", bat_basename)

        content = _RE_GAMEDIR.sub(f"set GameDir={shortname}", content)
        content = _RE_GAMENAME_BLOCK.sub(
            f"set GameName={bat_basename}\nset IndexName={bat_basename_no_year}",
            content,
        )
        content = _RE_UTIL_PATH.sub(r"..\\..\\util", content)
        content = _RE_THREE_CD.sub("cd ..\ncd ..", content)
        content = _RE_CALL_INSTALL.sub("call !config.bat", content)
        content = content.replace("\r\n", "\n").replace("\r", "\n")

        try:
            dest.write_text(content, encoding="utf-8", newline="\r\n")
            logger.info(f"  Generated !launch.bat from {orig_bat.name}")
        except Exception as exc:
            logger.error(f"  Failed to write !launch.bat: {exc}")

    @staticmethod
    def _render_template(template_path: Path | str, dest_path: Path | str, variables: dict[str, str]) -> None:
        """
        Substitute ${variable} placeholders and write with CRLF line endings.
        Args:
            template_path: Path to the template file.
            dest_path: Path to the destination file.
            variables: Variables to substitute into the template.
        """
        raw = Path(template_path).read_text(encoding="utf-8")
        rendered = string.Template(raw).safe_substitute(variables)
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text(rendered, encoding="utf-8", newline="\r\n")

    # --- Tool extraction ---

    def _extract_tools(self) -> None:
        """Extract the release util zip to util_root_dir (once per release)."""
        util_zip_subdir = self.release_config.get("util_zip_subdir")
        util_root_dir = self.release_config.get("util_root_dir")

        if not util_zip_subdir or not util_root_dir:
            logger.debug("  util_zip_subdir or util_root_dir not configured; skipping.")
            return

        util_root = Path(util_root_dir)
        sentinel = util_root / ".extracted"
        if sentinel.exists():
            logger.debug(f"  Util already extracted at {util_root}; skipping.")
            return

        util_zip_path = self.source_dir / util_zip_subdir
        if not util_zip_path.exists():
            logger.warning(f"  Util zip not found at {util_zip_path}; skipping.")
            return

        logger.info(f"  Extracting util tools from {util_zip_path} to {util_root}...")
        if util_root.exists():
            shutil.rmtree(util_root, ignore_errors=True)
        util_root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(util_zip_path, "r") as z:
            self._safe_extract_zip(z, util_root)

        util_sub_extracts = self.release_config.get("util_sub_extracts", [])
        if util_sub_extracts:
            self._extract_sub_archives_configured(util_root, util_sub_extracts)
        else:
            self._extract_sub_archives_legacy(util_root)

        sentinel.touch()
        logger.info(f"  Util tools extracted to {util_root}")

    def _extract_sub_archives_configured(self, util_root: Path, sub_extracts: list[dict[str, Any]]) -> None:
        for sub_config in sub_extracts:
            pattern = sub_config.get("archive_pattern", "")
            includes = sub_config.get("include", [])
            dest_str = (
                sub_config.get("dest", "{util_root}")
                .replace("{platform_root}", str(util_root.parent))
                .replace("{util_root}", str(util_root))
            )
            dest_dir = Path(dest_str)
            dest_dir.mkdir(parents=True, exist_ok=True)

            for matched_zip in util_root.glob(pattern):
                logger.info(f"  Extracting {matched_zip.name} to {dest_dir} (filters: {includes})...")
                try:
                    with zipfile.ZipFile(matched_zip, "r") as z:
                        members = (
                            [m for m in z.namelist() if any(m.startswith(i) or m == i for i in includes)]
                            if includes
                            else None
                        )
                        try:
                            self._safe_extract_zip(z, dest_dir, members=members)
                        except Exception as exc:
                            logger.error(f"  Failed to extract {matched_zip.name}: {exc}")
                except Exception as exc:
                    logger.error(f"  Failed to open {matched_zip.name}: {exc}")
                finally:
                    self._try_unlink(matched_zip)

    def _extract_sub_archives_legacy(self, util_root: Path) -> None:
        """
        Legacy sub-archive extraction: EXT* goes to parent, OPT* stays in util_root.
        Args:
            util_root: The root directory for utilities.
        """
        destinations = {
            "EXT*.zip": util_root.parent,
            "OPT*.zip": util_root,
        }
        for pattern, dest in destinations.items():
            for archive in util_root.glob(pattern):
                logger.info(f"  Extracting sub-archive {archive.name} to {dest}...")
                try:
                    with zipfile.ZipFile(archive, "r") as z:
                        try:
                            self._safe_extract_zip(z, dest)
                        except Exception as exc:
                            logger.error(f"  Failed to extract {archive.name}: {exc}")
                except Exception as exc:
                    logger.error(f"  Failed to open {archive.name}: {exc}")
                finally:
                    self._try_unlink(archive)

    @staticmethod
    def _try_unlink(path: Path) -> None:
        for i in range(3):
            try:
                path.unlink()
                return
            except PermissionError:
                if i < 2:
                    time.sleep(0.1)
                else:
                    logger.warning(f"  Could not delete {path} (PermissionError); ignoring.")

    # --- Media extraction ---

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
        """
        Extract extra media files (manuals, music, videos).
        Args:
            game_data: The game data dictionary.
            zip_filename: The name of the source zip file.
            game_dir: The game's extraction directory.
            media_dir: The root media directory.
            manuals_dir: The manuals directory.
            music_dir: The music directory.
            videos_dir: The videos directory.
        Returns:
            A tuple containing (manual_path, music_path, video_paths_dict).
        """
        manual_path_in_media = ""
        video_paths_in_media: dict[str, str] = {}

        media_dir = Path(media_dir)
        manuals_dir = Path(manuals_dir)
        videos_dir = Path(videos_dir)

        metadata_zip_subdir = self.release_config.get("metadata_zip_subdir")
        if not metadata_zip_subdir:
            return manual_path_in_media, "", video_paths_in_media

        metadata_zip = self.source_dir / metadata_zip_subdir
        if not metadata_zip.exists():
            return manual_path_in_media, "", video_paths_in_media

        p_dir = self.platform_image_dir or self.platform
        video_mappings = {
            "marquee": f"Videos/{p_dir}/Marquee/",
            "recordings": f"Videos/{p_dir}/Recordings/",
            "theme": f"Videos/{p_dir}/Theme/",
            "trailer": f"Videos/{p_dir}/Trailer/",
            "trailer_default": f"Videos/{p_dir}/",
        }

        with zipfile.ZipFile(metadata_zip, "r") as z:
            zip_paths = z.namelist()

            # Pre-filter videos for this game to optimize lookup
            game_videos = []
            for path in zip_paths:
                if not path.startswith(f"Videos/{p_dir}/") or path.endswith("/"):
                    continue
                filename = path.split("/")[-1]
                if self._launchbox_matches(
                    filename, game_data.get("id"), game_data.get("title"), game_data.get("bat_name")
                ):
                    game_videos.append(path)

            manual_path_in_media = self._extract_manual(
                z, zip_paths, game_data.get("manual_path"), manuals_dir, media_dir
            )

            for video_key, zip_dir in video_mappings.items():
                for matched in game_videos:
                    if not matched.startswith(zip_dir):
                        continue
                    if video_key == "trailer_default":
                        subpath = matched[len(zip_dir) :]
                        if "/" in subpath:
                            continue
                    actual_key = "trailer" if video_key == "trailer_default" else video_key
                    dest = self._safe_extract_path(videos_dir, Path(matched.replace("\\", "/")).name)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(z.read(matched))
                    video_paths_in_media[actual_key] = "./" + dest.relative_to(media_dir).as_posix()
                    logger.info(f"  Extracted video ({actual_key}): {dest.name}")

        return manual_path_in_media, "", video_paths_in_media

    @staticmethod
    def _extract_manual(
        z: zipfile.ZipFile,
        zip_paths: list[str],
        manual_path_in_db: str | None,
        manuals_dir: Path,
        media_dir: Path,
    ) -> str:
        if not manual_path_in_db:
            return ""
        norm = manual_path_in_db.replace("\\", "/")
        matched = next((p for p in zip_paths if p.lower() == norm.lower()), None)
        if not matched:
            return ""
        dest = BaseExtractor._safe_extract_path(manuals_dir, Path(matched.replace("\\", "/")).name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(z.read(matched))
        logger.info(f"  Extracted manual: {dest.name}")
        return "./" + dest.relative_to(media_dir).as_posix()

    def extract_and_process_images(
        self,
        game_data: dict[str, Any],
        raw_images_dir: Path,
        processed_images_dir: Path,
    ) -> dict[str, str]:
        """
        Extract the game's images from the metadata zip and process each one.
        Args:
            game_data: The game data dictionary.
            raw_images_dir: Directory to write the raw extracted images.
            processed_images_dir: Directory to write the processed images.
        Returns:
            Mapping of image key to its media-relative path.
        """
        raw_images_dir = Path(raw_images_dir)
        processed_images_dir = Path(processed_images_dir)

        metadata_zip_subdir = self.release_config.get("metadata_zip_subdir")
        if not metadata_zip_subdir:
            return {}

        metadata_zip = self.source_dir / metadata_zip_subdir
        if not metadata_zip.exists():
            logger.warning(f"  Metadata zip not found at {metadata_zip}; skipping images.")
            return {}

        p_dir = self.platform_image_dir or self.platform
        image_mappings = {
            "advertisement_flyer_back": f"Images/{p_dir}/Advertisement Flyer - Back/",
            "advertisement_flyer_front": f"Images/{p_dir}/Advertisement Flyer - Front/",
            "background": f"Images/{p_dir}/Fanart - Background/",
            "box_3d": f"Images/{p_dir}/Box - 3D/",
            "box_back": f"Images/{p_dir}/Box - Back/",
            "box_full": f"Images/{p_dir}/Box - Full/",
            "box_spine": f"Images/{p_dir}/Box - Spine/",
            "cart_3d": f"Images/{p_dir}/Cart - 3D/",
            "cart_back": f"Images/{p_dir}/Cart - Back/",
            "cart_front": f"Images/{p_dir}/Cart - Front/",
            "cover": f"Images/{p_dir}/Box - Front/",
            "disc": f"Images/{p_dir}/Disc/",
            "hero": f"Images/{p_dir}/Fanart - Background/",
            "logo": f"Images/{p_dir}/Clear Logo/",
            "screenshot": f"Images/{p_dir}/Screenshot - Gameplay/",
            "screenshot_game_over": f"Images/{p_dir}/Screenshot - Game Over/",
            "screenshot_game_select": f"Images/{p_dir}/Screenshot - Game Select/",
            "screenshot_game_title": f"Images/{p_dir}/Screenshot - Game Title/",
            "screenshot_high_scores": f"Images/{p_dir}/Screenshot - High Scores/",
        }

        processed_images: dict[str, str] = {}
        extracted_paths: set[str] = set()

        with zipfile.ZipFile(metadata_zip, "r") as z:
            zip_paths = z.namelist()

            # Pre-filter all matching images for this game to optimize lookup
            game_images: list[str] = []
            for path in zip_paths:
                if not path.startswith(f"Images/{p_dir}/") or path.endswith("/"):
                    continue
                filename = path.split("/")[-1]
                name = self._strip_exo_suffixes(filename)
                if self._launchbox_matches(
                    name, game_data.get("id"), game_data.get("title"), game_data.get("bat_name")
                ):
                    game_images.append(path)

            def get_img_key(zip_path: str) -> str:
                for key, zip_dir in image_mappings.items():
                    if zip_path.startswith(zip_dir):
                        return key
                parts = zip_path.split("/")
                if len(parts) >= 2:
                    folder = parts[-2]
                    return folder.lower().replace(" - ", "_").replace("-", "_").replace(" ", "_")
                return "unknown"

            images_by_key: dict[str, list[str]] = {}
            for path in game_images:
                key = get_img_key(path)
                if key not in images_by_key:
                    images_by_key[key] = []
                images_by_key[key].append(path)

            for img_key, matched_for_key in images_by_key.items():
                for idx, matched_zip_path in enumerate(matched_for_key):
                    parts = matched_zip_path.split("/")
                    subfolder = parts[-2] if len(parts) >= 2 else ""
                    raw_dest = self._safe_extract_path(raw_images_dir, f"{subfolder}/{parts[-1]}")
                    raw_dest.parent.mkdir(parents=True, exist_ok=True)

                    if matched_zip_path not in extracted_paths:
                        raw_dest.write_bytes(z.read(matched_zip_path))
                        extracted_paths.add(matched_zip_path)

                    target_name = img_key if idx == 0 else f"{img_key}-{idx + 1:02d}"
                    proc_path = self.image_processor.process_image(
                        image_type=target_name,
                        source_path=raw_dest,
                        destination_dir=processed_images_dir,
                        target_name=target_name,
                    )
                    if proc_path:
                        processed_images[target_name] = "./Images/processed/" + Path(proc_path).name
                    else:
                        processed_images[target_name] = (
                            "./Images/raw/" + Path(raw_dest).parent.name + "/" + Path(raw_dest).name
                        )

        return processed_images

    def extract_overlay_files(self, game_data: dict[str, Any], game_dir: Path) -> None:
        """Extract platform-specific overlay/config files into the game directory."""
        pass

    def _extract_zip_overlay(
        self,
        game_data: dict[str, Any],
        game_dir: Path,
        config_key: str,
        default_zip_subdir: str,
        default_prefix_tpl: str,
    ) -> None:
        game_dir = Path(game_dir)
        shortname = game_data["shortname"]

        metadata_zip_subdir = self.release_config.get(config_key, default_zip_subdir)
        if not metadata_zip_subdir:
            logger.warning(f"  {config_key} not configured; skipping overlay extraction.")
            return

        metadata_zip = self.source_dir / metadata_zip_subdir
        if not metadata_zip.exists():
            raise FileNotFoundError(f"Metadata zip not found at: {metadata_zip}")

        inner_prefix_tpl = self.release_config.get("zip_internal_prefix", default_prefix_tpl)
        inner_prefix = inner_prefix_tpl.format(shortname=shortname)

        with zipfile.ZipFile(metadata_zip, "r") as z:
            zip_paths = z.namelist()

            if not any(p.startswith(inner_prefix) for p in zip_paths):
                prefix_base = default_prefix_tpl.split("{shortname}")[0]
                inner_prefix = next(
                    (p for p in zip_paths if p.endswith("/") and f"/{shortname}/" in p and p.startswith(prefix_base)),
                    inner_prefix,
                )
                logger.info(f"  Resolved zip prefix: {inner_prefix}")

            self._safe_extract_zip(z, game_dir, prefix=inner_prefix)

    # --- Internal helpers ---

    def _get_folder_name(self, game_data: dict[str, Any]) -> str:
        title = game_data.get("title", "")
        game_id = game_data.get("id")

        folder_name = get_safe_filename(title)
        year_str = game_data.get("release_date", "Unknown")[:4]
        if year_str and year_str not in ("Unkn", "Unknown"):
            folder_name = f"{folder_name} ({year_str})"

        override_folder = self.overrides.get(game_id, {}).get("overrides", {}).get("folder_name")
        return override_folder or folder_name

    def _require_game(self, game_id_or_title: str) -> dict[str, Any]:
        game_data = self.db.get_game(game_id_or_title)
        if not game_data:
            raise ValueError(f"Game not found in database: {game_id_or_title}")
        return game_data

    def _locate_and_stage_zip(self, bat_name: str, folder_name: str, games_root: Path) -> Path:
        """
        Find the source game zip and copy it into the game's Source/ subdirectory.
        Args:
            bat_name: Name of the bat file.
            folder_name: Name of the game folder.
            games_root: Root directory for games.
        Returns:
            The path to the local staged zip.
        """
        zip_filename = bat_name.rsplit(".", 1)[0] + ".zip"
        search_base = self.source_dir / self.game_zips_subdir
        game_zip_path = search_base / zip_filename

        if not game_zip_path.exists():
            game_zip_path = next(search_base.rglob(zip_filename), None) if search_base.exists() else None
            if not game_zip_path:
                raise FileNotFoundError(f"Game archive not found: {zip_filename}")
            logger.info(f"  Found game zip recursively at: {game_zip_path}")

        source_dir = games_root / folder_name / "Source"
        source_dir.mkdir(parents=True, exist_ok=True)
        local_zip = source_dir / zip_filename

        if not local_zip.exists():
            logger.info(f"  Copying game archive to: {local_zip}")
            shutil.copy2(game_zip_path, local_zip)

        return local_zip

    def _setup_output_dirs(
        self, folder_name: str, metadata_root: Path, media_root: Path
    ) -> tuple[Path, Path, dict[str, Path]]:
        """Create and return metadata/media directories for a game."""
        metadata_dir = metadata_root / folder_name
        media_dir = media_root / folder_name

        raw_images = media_dir / "Images" / "raw"
        processed_images = media_dir / "Images" / "processed"
        manual_images = media_dir / "Images" / "manual"
        music_dir = media_dir / "Music"
        manuals_dir = media_dir / "Manuals"
        videos_dir = media_dir / "Videos"

        for d in (
            metadata_dir,
            raw_images,
            processed_images,
            manual_images,
            music_dir,
            manuals_dir,
            videos_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

        subdirs: dict[str, Path] = {
            "raw_images": raw_images,
            "processed_images": processed_images,
            "manual_images": manual_images,
            "music": music_dir,
            "manuals": manuals_dir,
            "videos": videos_dir,
        }
        return metadata_dir, media_dir, subdirs

    def _build_game_info(
        self,
        game_data: dict[str, Any],
        game_dir: Path,
        global_id: str,
        game_id: str,
        title: str,
        shortname: str,
        added_at: str,
        updated_at: str,
    ) -> dict[str, Any]:
        game_dir = Path(game_dir)
        custom_fields: list[dict[str, Any]] = []
        if source_licence := game_data.get("source_licence"):
            custom_fields.append({"name": "Source Licence", "value": source_licence})

        return {
            "global_id": global_id,
            "game_id": game_id,
            "game_source": self.game_source,
            "platform": self.platform,
            "game_name": title,
            "game_folder": shortname,
            "game_dir": str(game_dir),
            "game_version": game_data.get("version", ""),
            "application_path": str(game_dir / "!launch.bat"),
            "application_arguments": "",
            "config_app_path": str(game_dir / "!config.bat") if game_data.get("configuration_path") else "",
            "config_app_arguments": "",
            "is_installed": False,
            "is_favorite": game_data.get("favorite", False),
            "is_broken": game_data.get("broken", False),
            "is_portable": game_data.get("portable", False),
            "is_hidden": game_data.get("hide", False),
            "use_dosbox": game_data.get("use_dosbox", False),
            "dosbox_config_path": game_data.get("dosbox_config_path", ""),
            "dosbox_version_path": game_data.get("custom_dosbox_version_path", ""),
            "status": game_data.get("status", ""),
            "progress": str(game_data.get("progress", "")),
            "addl_apps": [],
            "custom_fields": custom_fields,
            "extras": {},
            "added_at": added_at,
            "updated_at": updated_at,
        }

    def _build_metadata_info(
        self,
        game_data: dict[str, Any],
        game_id: str,
        title: str,
        metadata_dir: Path,
        added_at: str,
        updated_at: str,
    ) -> dict[str, Any]:
        max_players = game_data.get("max_players")
        field_values: dict[str, Any] = {
            "title": title,
            "release_date": game_data.get("release_date", ""),
            "release_type": game_data.get("release_type", ""),
            "developer": game_data.get("developer", ""),
            "publisher": game_data.get("publisher", ""),
            "region": game_data.get("region", ""),
            "genre": game_data.get("genres", ""),
            "play_mode": game_data.get("play_mode", ""),
            "max_players": max_players,
            "rating": game_data.get("rating", ""),
            "series": game_data.get("series", ""),
            "video_url": game_data.get("video_url", ""),
            "wikipedia_url": game_data.get("wikipedia_url", ""),
            "description": game_data.get("notes", ""),
        }
        field_sources = {k: (self.game_source if (v is not None and v != "") else "") for k, v in field_values.items()}
        return {
            "game_id": game_id,
            "game_source": self.game_source,
            "metadata_dir": str(metadata_dir),
            "metadata_source": self.game_source,
            "metadata_id": game_id,
            "title": title,
            "release_date": field_values["release_date"],
            "release_type": field_values["release_type"],
            "developer": field_values["developer"],
            "publisher": field_values["publisher"],
            "region": field_values["region"],
            "rating": field_values["rating"],
            "genre": field_values["genre"],
            "series": field_values["series"],
            "play_mode": field_values["play_mode"],
            "max_players": max_players,
            "video_url": field_values["video_url"],
            "wikipedia_url": field_values["wikipedia_url"],
            "description": field_values["description"],
            "field_sources": field_sources,
            "added_at": added_at,
            "updated_at": updated_at,
        }

    def _build_media_info(
        self,
        game_id: str,
        media_dir: Path,
        image_paths: dict[str, str],
        video_paths: dict[str, str],
        music_path: str,
        manual_path: str,
        added_at: str,
        updated_at: str,
    ) -> dict[str, Any]:
        return {
            "game_id": game_id,
            "game_source": self.game_source,
            "media_dir": str(media_dir),
            "media_source": self.game_source,
            "media_id": game_id,
            "image_paths": image_paths,
            "video_paths": video_paths,
            "music_path": music_path,
            "manual_path": manual_path,
            "asset_sources": {
                "image_paths": dict.fromkeys(image_paths, self.game_source),
                "video_paths": dict.fromkeys(video_paths, self.game_source),
                "manual_path": self.game_source if manual_path else "",
                "music_path": self.game_source if music_path else "",
            },
            "added_at": added_at,
            "updated_at": updated_at,
        }
