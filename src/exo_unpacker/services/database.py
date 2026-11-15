import atexit
import contextlib
import logging
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from exo_unpacker.core.config import Settings
from exo_unpacker.models import ReleaseConfig

logger = logging.getLogger(__name__)


_CLEANUP_PATHS: set[Path] = set()


def _cleanup_registered_paths() -> None:
    """Remove any cached XML database files registered for exit cleanup."""
    for cached_path in list(_CLEANUP_PATHS):
        with contextlib.suppress(OSError):
            cached_path.unlink(missing_ok=True)
        _CLEANUP_PATHS.discard(cached_path)


atexit.register(_cleanup_registered_paths)


class MetadataDatabase:
    """Manages loading and querying the LaunchBox XML database."""

    def __init__(self, config: Settings, release_name: str | None = None) -> None:
        self.config: Settings = config
        self.actual_release: str = release_name if release_name else config.default_release
        self.release_config: ReleaseConfig = config.get_release_config(self.actual_release)

        # Local cache path - data/ directory in the project root
        self.cache_dir: Path = self.config.config_path.parent / "data"
        xml_inner_path = self.release_config["xml_db_path"]
        self.cached_xml_path: Path = self.cache_dir / f"{self.actual_release}{Path(xml_inner_path).suffix}"

        # Force re-pull at start of run by removing existing cache
        with contextlib.suppress(OSError):
            self.cached_xml_path.unlink(missing_ok=True)

        _CLEANUP_PATHS.add(self.cached_xml_path)

        self.games: dict[str, dict[str, Any]] = {}
        self.games_by_title: dict[str, dict[str, Any]] = {}

    def __enter__(self) -> "MetadataDatabase":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        """Remove the cached XML database and deregister it from exit cleanup."""
        _CLEANUP_PATHS.discard(self.cached_xml_path)
        try:
            self.cached_xml_path.unlink(missing_ok=True)
            logger.info(f"Cleaned up cached database: {self.cached_xml_path}")
        except OSError:
            pass

    def ensure_cached(self, force: bool = False) -> None:
        """Extracts the XML database from the remote zip if not cached locally."""
        if self.cached_xml_path.exists() and not force:
            return

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        source_dir = self.release_config["source_dir"]
        zip_subdir = self.release_config["metadata_zip_subdir"]
        metadata_zip_path = Path(source_dir) / zip_subdir
        xml_inner_path = self.release_config["xml_db_path"]

        logger.info(f"Extracting {xml_inner_path} from {metadata_zip_path}...")
        if not metadata_zip_path.exists():
            raise FileNotFoundError(f"Source metadata zip not found at: {metadata_zip_path}")

        try:
            with zipfile.ZipFile(metadata_zip_path, "r") as z:
                with z.open(xml_inner_path) as source_f:
                    content = source_f.read()
                    if xml_inner_path.endswith(".9x"):
                        content_str = content.decode("utf-8", errors="ignore")
                        wrapped = (
                            '<?xml version="1.0" standalone="yes"?>\n<LaunchBox>\n' + content_str + "\n</LaunchBox>"
                        )
                        content = wrapped.encode("utf-8")
                    self.cached_xml_path.write_bytes(content)
        except zipfile.BadZipFile as e:
            logger.error(f"Failed to open metadata zip: {e}")
            raise

        logger.info(f"Database cached locally at {self.cached_xml_path}")

    def load(self) -> None:
        """Loads and parses the XML database."""
        self.ensure_cached()

        logger.info(f"Loading metadata database from {self.cached_xml_path}...")
        try:
            tree = ET.parse(self.cached_xml_path)
        except ET.ParseError as e:
            logger.error(f"Failed to parse XML database: {e}")
            raise

        root = tree.getroot()

        self.games.clear()
        self.games_by_title.clear()

        for game_node in root.findall("Game"):
            game_id = game_node.findtext("ID")
            if not game_id:
                continue

            title = game_node.findtext("Title", "")
            app_path = game_node.findtext("ApplicationPath", "")
            config_path = game_node.findtext("ConfigurationPath", "")
            root_folder = game_node.findtext("RootFolder", "")

            # Parse shortname / bat from ApplicationPath
            shortname = ""
            bat_name = ""
            if app_path:
                parts = Path(app_path.replace("\\", "/")).parts
                if len(parts) >= 2:
                    shortname = parts[-2]
                    bat_name = parts[-1]

            # Parse max players as int if possible
            max_players_str = game_node.findtext("MaxPlayers", "")
            try:
                max_players = int(max_players_str) if max_players_str else 1
            except ValueError:
                max_players = 1

            game_data = {
                "id": game_id,
                "title": title,
                "shortname": shortname,
                "root_folder": root_folder,
                "version": game_node.findtext("Version", ""),
                "application_path": app_path,
                "configuration_path": config_path,
                "bat_name": bat_name,
                "favorite": game_node.findtext("Favorite", "false").lower() == "true",
                "use_dosbox": game_node.findtext("UseDosBox", "false").lower() == "true",
                "release_date": game_node.findtext("ReleaseDate", ""),
                "notes": game_node.findtext("Notes", ""),
                "developer": game_node.findtext("Developer", ""),
                "publisher": game_node.findtext("Publisher", ""),
                "genres": game_node.findtext("Genre", ""),
                "play_mode": game_node.findtext("PlayMode", ""),
                "max_players": max_players,
                "rating": game_node.findtext("Rating", ""),
                "series": game_node.findtext("Series", ""),
                "wikipedia_url": game_node.findtext("WikipediaURL", ""),
                "manual_path": game_node.findtext("ManualPath", ""),
                "source_licence": game_node.findtext("Source", ""),
            }

            self.games[game_id] = game_data
            if title:
                self.games_by_title[title.lower()] = game_data

        logger.info(f"Loaded {len(self.games)} games from database.")

    def get_game(self, game_id_or_title: str) -> dict[str, Any] | None:
        """
        Retrieve a game by its exact ID or exact title.
        Args:
            game_id_or_title: The ID or title of the game.
        Returns:
            The game data dict if found, else None.
        """
        if game_id_or_title in self.games:
            return self.games[game_id_or_title]
        return self.games_by_title.get(game_id_or_title.lower())

    def search(self, query: str) -> list[dict[str, Any]]:
        """
        Search games by title, genre, developer, or publisher.
        Args:
            query: The search query.
        Returns:
            A list of matching game data dicts.
        """
        query_lower = query.lower()

        def matches(g: dict[str, Any]) -> bool:
            return (
                query_lower in g["title"].lower()
                or query_lower in g["genres"].lower()
                or query_lower in g["developer"].lower()
                or query_lower in g["publisher"].lower()
                or query_lower in g["shortname"].lower()
            )

        return [g for g in self.games.values() if matches(g)]
