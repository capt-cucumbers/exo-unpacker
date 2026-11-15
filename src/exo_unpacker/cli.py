import argparse
import logging
import sys
from pathlib import Path

from exo_unpacker import tasks
from exo_unpacker.core import config
from exo_unpacker.core.logger import setup_logger
from exo_unpacker.core.utils import enable_ansi_utf8
from exo_unpacker.services.database import MetadataDatabase
from exo_unpacker.services.extractor import GameExtractor

enable_ansi_utf8()

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argparse parser."""
    parser = argparse.ArgumentParser(description="eXo Unpacker - Extract and conform games from eXo releases.")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    # Command: cache-db
    p_cache = subparsers.add_parser("cache-db", help="Cache the metadata XML database locally")
    p_cache.add_argument("--force", action="store_true", help="Force database refresh")

    # Command: list
    p_list = subparsers.add_parser("list", help="List games from metadata database")
    p_list.add_argument("--limit", type=int, default=50, help="Maximum number of games to display")

    # Command: search
    p_search = subparsers.add_parser("search", help="Search games in metadata database")
    p_search.add_argument("query", type=str, help="Search query")

    # Command: unpack
    p_unpack = subparsers.add_parser("unpack", help="Unpack a game by ID or Title")
    p_unpack.add_argument("game", type=str, help="Game ID or exact Title")

    # Optional path overrides for unpack
    path_group = p_unpack.add_argument_group("Path Overrides")
    path_group.add_argument("--games-root", type=Path, help="Override default games root directory")
    path_group.add_argument("--metadata-root", type=Path, help="Override default metadata root directory")
    path_group.add_argument("--media-root", type=Path, help="Override default media root directory")

    # Command: unpack-release
    p_unpack_rel = subparsers.add_parser("unpack-release", help="Unpack all games in a release")
    p_unpack_rel.add_argument("--release", type=str, default=None, help="Release key to unpack")
    p_unpack_rel.add_argument("--skip-errors", action="store_true", help="Continue on error")

    # Command: unpack-all
    p_unpack_all = subparsers.add_parser("unpack-all", help="Unpack all games across every configured release")
    p_unpack_all.add_argument("--skip-errors", action="store_true", help="Continue on error")

    # Command: clear
    p_clear = subparsers.add_parser("clear", help="Clear a conformed/extracted game")
    p_clear.add_argument("game", type=str, help="Game ID or exact Title")

    # Command: clean
    p_clean = subparsers.add_parser("clean", help="Clean all extracted output directories")
    p_clean.add_argument("--force", action="store_true", help="Bypass confirmation prompt")

    return parser


def main() -> int:
    """Run the CLI entry point."""
    parser = build_parser()

    args = parser.parse_args()

    setup_logger(verbose=args.verbose)

    if not args.command:
        parser.print_help()
        return 0

    if not config.settings.default_release and args.command in {"unpack-release", "unpack-all"}:
        logger.error("config.toml is missing or incomplete - run setup.bat first.")
        return 1

    # db is only needed for single-release commands
    db = None
    needs_db = args.command in {"cache-db", "list", "search", "unpack", "clear"}
    if needs_db:
        try:
            db = MetadataDatabase(config.settings)
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            return 1

    if args.command == "cache-db":
        try:
            logger.info("\n-- cache-db")
            db.ensure_cached(force=args.force)
            logger.info("  Database cached successfully.")
        except Exception as e:
            logger.error(f"  Failed to cache database: {e}")
            return 1

    elif args.command == "list":
        try:
            logger.info(f"\n-- list (Showing first {args.limit} games)")
            db.load()
            games = sorted(db.games.values(), key=lambda x: x["title"])
            print("-" * 80)
            for g in games[: args.limit]:
                print(f"[{g['id']}] {g['title']} ({g['shortname']})")
        except Exception as e:
            logger.error(f"  Failed to list games: {e}")
            return 1

    elif args.command == "search":
        try:
            logger.info(f"\n-- search for '{args.query}'")
            db.load()
            results = db.search(args.query)
            logger.info(f"  Found {len(results)} matches.")
            print("-" * 80)
            for g in sorted(results, key=lambda x: x["title"]):
                print(f"[{g['id']}] {g['title']} ({g['shortname']})")
        except Exception as e:
            logger.error(f"  Search failed: {e}")
            return 1

    elif args.command == "unpack":
        try:
            logger.info(f"\n-- unpack: {args.game}")
            db.load()
            extractor = GameExtractor(config.settings, db)
            extractor.extract_game(
                game_id_or_title=args.game,
                games_root=args.games_root,
                metadata_root=args.metadata_root,
                media_root=args.media_root,
            )
            logger.info("  Unpack sequence completed successfully!")
        except Exception as e:
            logger.error(f"  Unpack failed: {e}")
            return 1

    elif args.command == "clear":
        try:
            logger.info(f"\n-- clear: {args.game}")
            db.load()
            extractor = GameExtractor(config.settings, db)
            extractor.clear_game(args.game)
            logger.info("  Clear sequence completed successfully!")
        except Exception as e:
            logger.error(f"  Clear failed: {e}")
            return 1

    elif args.command == "unpack-release":
        _, _, errs = tasks.unpack_release(args.release, skip_errors=args.skip_errors)
        return 1 if errs > 0 and not args.skip_errors else 0

    elif args.command == "unpack-all":
        releases = list(config.settings.releases.keys())
        if not releases:
            logger.error("No releases defined in config.toml.")
            return 1

        logger.info(f"\n-- unpack-all: {len(releases)} release(s)")
        total_ok = total_skip = total_err = 0

        for release_key in releases:
            ok, skip, err = tasks.unpack_release(release_key, skip_errors=args.skip_errors)
            total_ok += ok
            total_skip += skip
            total_err += err

        logger.info(f"\n  All releases complete — OK: {total_ok}  Skipped: {total_skip}  Errors: {total_err}")
        return 1 if total_err > 0 and not args.skip_errors else 0

    elif args.command == "clean":
        logger.info("\n-- clean")
        return tasks.clean_output(force=args.force)

    return 0


if __name__ == "__main__":
    sys.exit(main())
