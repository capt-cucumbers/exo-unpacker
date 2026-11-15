from dataclasses import dataclass, field
from typing import Any, TypedDict

# --- Config ---


def _as_str(value: Any, default: str = "") -> str:
    """Coerce value to str, falling back to default when missing."""
    return str(value) if value is not None else default


def _as_releases(value: Any) -> dict[str, dict[str, Any]]:
    """Coerce the [releases] table to dict-of-dicts, dropping non-table entries."""
    if not isinstance(value, dict):
        return {}
    releases: dict[str, dict[str, Any]] = {}
    for key, entry in value.items():
        if isinstance(entry, dict):
            releases[str(key)] = {str(k): v for k, v in entry.items()}
    return releases


@dataclass(frozen=True)
class FileConfig:
    """Shape of config.toml — one field per documented key."""

    default_release: str = ""
    releases: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "FileConfig":
        """Build a FileConfig from raw TOML data, coercing values tolerantly."""
        return cls(
            default_release=_as_str(data.get("settings", {}).get("default_release")),
            releases=_as_releases(data.get("releases", {})),
        )


class ReleaseConfig(TypedDict, total=False):
    """Shape of a [releases.\"<key>\"] block in config.toml."""

    name: str
    extractor_type: str
    platform: str
    source: str
    source_dir: str
    game_zips_subdir: str
    metadata_zip_subdir: str
    dos_metadata_zip_subdir: str
    gamedata_zip_subdir: str
    xml_db_path: str
    manifest_path: str
    games_root_dir: str
    metadata_root_dir: str
    media_root_dir: str
    util_zip_subdir: str
    util_root_dir: str
    ignores_path: str
    overrides_path: str
    setup_template: str
    zip_internal_prefix: str
    util_sub_extracts: list[dict[str, Any]]


# --- Manifests ---


class ManifestMetadata(TypedDict, total=False):
    """The metadata block of a manifest entry (!metadata.info)."""

    game_id: str
    game_source: str
    metadata_dir: str
    metadata_source: str
    metadata_id: str
    title: str
    release_date: str
    release_type: str
    developer: str
    publisher: str
    region: str
    genre: str
    play_mode: str
    max_players: int | None
    rating: str
    series: str
    video_url: str
    wikipedia_url: str
    description: str
    field_sources: dict[str, str]
    added_at: str
    updated_at: str


class AssetSources(TypedDict):
    """Source provider attribution per media asset slot."""

    image_paths: dict[str, str]
    video_paths: dict[str, str]
    manual_path: str
    music_path: str


class ManifestMedia(TypedDict, total=False):
    """The media block of a manifest entry (!media.info)."""

    game_id: str
    game_source: str
    media_dir: str
    media_source: str
    media_id: str
    image_paths: dict[str, str]
    video_paths: dict[str, str]
    manual_path: str
    music_path: str
    asset_sources: AssetSources
    added_at: str
    updated_at: str


class ManifestEntry(TypedDict, total=False):
    """A single game entry in a release manifest JSON file."""

    global_id: str
    game_id: str
    game_source: str
    platform: str
    game_name: str
    game_folder: str
    game_dir: str
    game_version: str
    application_path: str
    application_arguments: str
    config_app_path: str
    config_app_arguments: str
    is_installed: bool
    is_favorite: bool
    is_broken: bool
    is_portable: bool
    is_hidden: bool
    use_dosbox: bool
    dosbox_config_path: str
    dosbox_version_path: str
    status: str
    progress: str
    metadata_source: str
    metadata_id: str
    media_source: str
    media_id: str
    metadata: ManifestMetadata
    media: ManifestMedia
    addl_apps: list[dict[str, Any]]
    custom_fields: list[dict[str, Any]]
    extras: dict[str, Any]
    added_at: str
    updated_at: str


# --- Ignore / Override Files ---


class IgnoreEntry(TypedDict, total=False):
    """A single ignored game entry in ignores/<release>.json."""

    game_folder: str
    reason: str


class OverrideEntry(TypedDict, total=False):
    """A single override entry in overrides/<release>.json."""

    game_folder: str
    overrides: dict[str, str]


IgnoresFile = dict[str, IgnoreEntry]
OverridesFile = dict[str, OverrideEntry]
