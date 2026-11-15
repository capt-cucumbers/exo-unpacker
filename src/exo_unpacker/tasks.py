import logging
import shutil
from pathlib import Path

from exo_unpacker.core import config
from exo_unpacker.services.database import MetadataDatabase
from exo_unpacker.services.extractor import GameExtractor

logger = logging.getLogger(__name__)


def unpack_release(release_key: str | None = None, skip_errors: bool = False) -> tuple[int, int, int]:
    """
    Unpack every game in a release, defaulting to the configured default release.
    Returns:
        An (ok, skipped, error) count tuple.
    """
    release_key = release_key or config.settings.default_release
    logger.info(f"\n-- {release_key}: unpack")

    try:
        db = MetadataDatabase(config.settings, release_key)
        db.ensure_cached()
        db.load()
    except Exception as e:
        logger.error(f"  Failed to load database: {e}")
        return 0, 0, 1

    games = sorted(db.games.values(), key=lambda x: x["title"])
    extractor = GameExtractor(config.settings, db, release_key=release_key)

    total = len(games)
    ok = skipped = errors = 0

    for idx, game in enumerate(games, 1):
        title = game["title"]
        game_id = game["id"]
        logger.info(f"\n[{idx}/{total}] {title}")
        try:
            extractor.extract_game(game_id_or_title=game_id)
            ok += 1
        except FileNotFoundError:
            logger.warning(f"  Skipped (Zip not found): {title}")
            skipped += 1
        except Exception as e:
            logger.error(f"  Failed extracting '{title}': {e}")
            errors += 1
            if not skip_errors:
                return ok, skipped, errors

    logger.info(f"\nDone — OK: {ok}  Skipped: {skipped}  Errors: {errors}")
    return ok, skipped, errors


def clean_output(force: bool = False) -> int:
    """
    Delete every output root configured for any release.
    Returns:
        The exit code (0 for success, 1 if any deletions failed).
    """
    dirs_to_clean = sorted(
        {
            Path(release[key]).resolve()
            for release in config.settings.releases.values()
            for key in ("games_root_dir", "metadata_root_dir", "media_root_dir", "util_root_dir")
            if key in release
        }
    )

    if not dirs_to_clean:
        logger.info("  No output directories found in config.")
        return 0

    logger.warning("The following directories and ALL their contents will be permanently deleted:")
    logger.warning("-" * 80)
    for d in dirs_to_clean:
        logger.warning(f"  {d}")
    logger.warning("-" * 80)

    if not force:
        confirm = input("Are you sure you want to proceed? [y/N]: ")
        if confirm.lower() != "y":
            logger.info("  Clean operation aborted.")
            return 0

    errors = 0
    for d in dirs_to_clean:
        if d.exists():
            try:
                shutil.rmtree(d)
                logger.info(f"  Deleted: {d}")
            except Exception as e:
                errors += 1
                logger.error(f"  Failed to delete {d}: {e}")
        else:
            logger.info(f"  Skipped (does not exist): {d}")

    if errors:
        logger.error(f"Clean completed with {errors} error(s).")
        return 1

    logger.info("Clean completed!")
    return 0
