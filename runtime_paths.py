"""One data root for installed apps; an explicit, self-contained portable mode."""
import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    app_dir: Path
    data_dir: Path
    portable: bool

    @property
    def config_file(self):
        return self.data_dir / "config.json"

    @property
    def legacy_config(self):
        return self.app_dir / "config.json"

    @property
    def cache_dir(self):
        return self.data_dir / "cache"

    @property
    def log_dir(self):
        return self.data_dir / "logs"


def resolve_paths(app_dir=None, user_data_dir=None, portable=None):
    app_dir = Path(app_dir or (Path(sys.executable).parent if getattr(sys, "frozen", False)
                              else Path(__file__).parent)).resolve()
    if portable is None:
        portable = (app_dir / "portable.flag").is_file() or "--portable" in sys.argv
    if portable:
        data_dir = app_dir / "data"
    elif user_data_dir is not None:
        data_dir = Path(user_data_dir).resolve()
    else:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        data_dir = base / "ScreenshotTranslator"
    return AppPaths(app_dir, data_dir, bool(portable))
