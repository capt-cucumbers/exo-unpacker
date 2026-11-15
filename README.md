# eXo Unpacker

[![CI](https://github.com/capt-cucumbers/exo-unpacker/actions/workflows/ci.yml/badge.svg)](https://github.com/capt-cucumbers/exo-unpacker/actions/workflows/ci.yml)
[![Python 3.11-3.13](https://img.shields.io/badge/python-3.11--3.13-blue.svg)](https://www.python.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D6.svg)](https://www.microsoft.com/windows)

Batch extractor for eXo retro game collections (eXoDOS, eXoWin3x, eXoAppleIIGS, eXoScummVM, eXoDREAMM, and eXoWin9x). It unpacks game and metadata zips into standalone game, metadata, and media folders, builds `!launch.bat` / `!config.bat` scripts, crops/conforms artwork, and writes JSON manifests that LaunchBox tools can import directly.

## What It Does

- Supports eXoDOS, eXoWin3x, eXoAppleIIGS, eXoScummVM, eXoDREAMM, and eXoWin9x archive layouts.
- Generates standalone `!launch.bat` and `!config.bat` scripts so games run without using the stock eXo installer.
- Cleans up artwork (crops letterboxing, preserves pixel art sharpness, pads backgrounds when needed).
- Writes per-release manifests to `manifests/<source>.json` for downstream tools like `launchbox-game-updater` and `launchbox-sync-plugin`.

---

## Requirements

**Windows only.** Generates Windows batch scripts and expects Windows paths and eXo collection archives.

- [Python](https://www.python.org/) 3.11–3.13 (in `PATH` or configured via `.python-path`)
- [Poetry](https://python-poetry.org/) (installed globally)
- Original eXo collection archives (game zips, metadata zips, and utility bundles)

## Installation

Run `setup.bat` from the repository root to create `.venv/`, install dependencies, and copy `.dist` config templates:

```powershell
setup.bat
```

Use `setup.bat --dev` to include dev tools (`pytest`, `ruff`), or `setup.bat --config` to only create missing config files.

### Configuration Templates

| Template | Live File | Purpose |
| :--- | :--- | :--- |
| `config.dist.toml` | `config.toml` | Release definitions, input archive paths, and output directories. |
| `manifest.dist.json` | `manifests/<source>.json` | Reference example of the generated v2 manifest format (not copied by `setup.bat`). |
| `ignores/*.dist.json` | `ignores/*.json` | Titles to skip per collection release. |
| `overrides/*.dist.json` | `overrides/*.json` | Per-game metadata and path overrides per collection release. |

## Configuration

### 1. Releases & Paths (`config.toml`)

Edit `config.toml` at the repository root to point each release to your eXo source directory and output roots:

```toml
[settings]
default_release = "eXoDOS_v6.04"

[releases."eXoDOS_v6.04"]
name = "eXoDOS v6.04"
extractor_type = "exodos"
platform = "MS-DOS"
source = "eXoDOS"
source_dir = "D:\\eXo\\eXoDOS"
games_root_dir = "C:\\eXo\\Games\\PC\\MS-DOS\\eXoDOS"
metadata_root_dir = "C:\\eXo\\Metadata\\PC\\MS-DOS\\eXoDOS"
media_root_dir = "C:\\eXo\\Media\\PC\\MS-DOS\\eXoDOS"
```

### 2. Ignores & Overrides (`ignores/`, `overrides/`)

Edit `ignores/<release>.json` and `overrides/<release>.json` to exclude games or override extracted paths and fields.

---

## Usage

Commands run through `run.bat <command>` (or `python launch.py`):

```powershell
# Cache XML metadata databases into data/
.\run.bat cache-db

# List cached games sorted by title
.\run.bat list

# Search cached games by title, genre, developer, or shortname
.\run.bat search "Carmen Sandiego"

# Unpack a single game by ID or exact title
.\run.bat unpack <GameID_or_ExactTitle>

# Unpack every game in one release
.\run.bat unpack-release --release eXoDOS_v6.04 --skip-errors

# Unpack all configured releases
.\run.bat unpack-all --skip-errors

# Remove one game's extracted output and manifest entry
.\run.bat clear <GameID_or_ExactTitle>

# Delete all configured output root directories
.\run.bat clean --force
```

## CLI Reference

### Commands

| Command | Description |
| :--- | :--- |
| `cache-db [--force]` | Build or refresh the local cached XML metadata database in `data/`. |
| `list [--limit N]` | List cached games alphabetically by title. |
| `search <query>` | Substring search across title, genre, developer, publisher, and shortname. |
| `unpack <game> [--games-root PATH] [--metadata-root PATH] [--media-root PATH]` | Extract a single game by ID or exact title, with optional destination overrides. |
| `unpack-release [--release KEY] [--skip-errors]` | Extract every game in one configured release. |
| `unpack-all [--skip-errors]` | Extract every configured release sequentially. |
| `clear <game>` | Remove a single game's output folders and manifest record. |
| `clean [--force]` | Delete all configured output directories. |

### Top-Level Flags

| Flag | Description |
| :--- | :--- |
| `-v, --verbose` | Enable debug logging (`run.bat cli -v <command>`). |

### Output Directory Layout

Extracted files are organized under `{platform}/{source}/{shortname}`:

```text
C:\eXo\
├── Games\PC\[Platform]\[Source]\[Shortname]\
│   ├── !launch.bat       # Generated game launch script
│   ├── !config.bat       # Setup / configuration script
│   ├── Source\           # Copied game archive
│   └── !game.info        # Saved launch and app metadata
├── Metadata\PC\[Platform]\[Source]\[Shortname]\
│   └── !metadata.info    # Saved descriptive metadata
└── Media\PC\[Platform]\[Source]\[Shortname]\
    ├── Images\
    ├── Videos\
    ├── Manuals\
    └── !media.info       # Saved media path index
```

## Related Projects

- **[`launchbox-game-updater`](https://github.com/capt-cucumbers/launchbox-game-updater)** — CLI/TUI tool that imports generated `manifests/*.json` files into LaunchBox XMLs and copies staged artwork.
- **[`launchbox-sync-plugin`](https://github.com/capt-cucumbers/launchbox-sync-plugin)** — LaunchBox desktop plugin that syncs generated manifests directly inside LaunchBox.
