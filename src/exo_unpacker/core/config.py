import logging
from dataclasses import dataclass
from pathlib import Path

from exo_unpacker.core.utils import read_toml
from exo_unpacker.models import FileConfig, ReleaseConfig

logger = logging.getLogger(__name__)

PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]
CONFIG_PATH: Path = PROJECT_ROOT / "config.toml"


def _load_file_config() -> FileConfig:
    """Load config.toml tolerantly, warning on unknown keys."""
    data = read_toml(CONFIG_PATH, {})
    for key in sorted(set(data) - {"settings", "releases"}):
        logger.warning(f"Unknown config.toml key: '{key}'")
    return FileConfig.from_dict(data)


@dataclass(frozen=True)
class Settings:
    """Runtime settings resolved from config.toml (env → file → defaults)."""

    default_release: str
    releases: dict[str, ReleaseConfig]
    config_path: Path

    @classmethod
    def load(cls, file: FileConfig) -> "Settings":
        """Build Settings from a parsed FileConfig."""
        return cls(
            default_release=file.default_release,
            releases=file.releases,
            config_path=CONFIG_PATH,
        )

    def get_release_config(self, release_name: str | None = None) -> ReleaseConfig:
        """Return a release's config, defaulting to the configured default."""
        key = release_name or self.default_release
        if key not in self.releases:
            raise KeyError(f"Release config '{key}' not defined in config.toml")
        return self.releases[key]

    def resolve_release_path(self, key: str, release_name: str | None = None) -> Path | None:
        """Resolve a configured release path against PROJECT_ROOT, or None if unset."""
        raw = self.get_release_config(release_name).get(key)
        if not raw:
            return None
        p = Path(raw)
        return p if p.is_absolute() else PROJECT_ROOT / p

    def get_manifest_path(self, release_name: str | None = None) -> Path:
        """Resolve the release's manifest JSON path against the project root."""
        raw = self.get_release_config(release_name)["manifest_path"]
        p = Path(raw)
        return p if p.is_absolute() else PROJECT_ROOT / p

    def get_template_path(self, template_key: str, release_name: str | None = None) -> Path | None:
        """Resolve a template path (e.g. setup_template), or None when unset."""
        return self.resolve_release_path(template_key, release_name)


settings: Settings = Settings.load(_load_file_config())
