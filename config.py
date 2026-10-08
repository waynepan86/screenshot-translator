import os
import json
import sys
import copy
import winreg
import tempfile
from pathlib import Path
from runtime_paths import resolve_paths
from languages import valid_language

DEFAULT_CONFIG = {
    "hotkey_region": "F1",
    "hotkey_fullscreen": "F2",
    "save_dir": os.path.join(os.path.expanduser("~"), "Pictures"),
    "auto_start": False,
    "ocr_review": True,
    # "auto" keeps the key-free Google -> MyMemory chain. Any other value
    # names an engine from translator.ENGINE_LABELS and is tried first.
    "trans_engine": "auto",
    "trans_source": "auto",
    "trans_target": "zh-CN",
    "config_version": 2,
    # Credentials per engine, shaped like translator.ENGINE_FIELDS.
    "trans_api": {
        "azure": {"key": "", "region": "global"},
        "llm": {"base_url": "https://api.deepseek.com/v1", "key": "", "model": "deepseek-chat"},
        "baidu": {"appid": "", "secret": ""},
        "youdao": {"appid": "", "secret": ""},
        "deepl": {"key": ""},
    },
}

class ConfigManager:
    def __init__(self, app_dir=None, user_data_dir=None, portable=None):
        # deepcopy, not copy: a shallow copy would let edits to trans_api leak
        # into DEFAULT_CONFIG and corrupt the fallback values.
        self.config = copy.deepcopy(DEFAULT_CONFIG)
        self.paths = resolve_paths(app_dir, user_data_dir, portable)
        self.migrated_from = None
        self.load()

    def load(self):
        destination = self.paths.config_file
        legacy = self.paths.legacy_config
        source = destination if destination.exists() else legacy if legacy.exists() else None
        if source is not None:
            try:
                loaded = json.loads(source.read_text(encoding="utf-8-sig"))
                if not isinstance(loaded, dict):
                    raise ValueError("配置根节点不是对象")
            except (ValueError, OSError) as exc:
                raise RuntimeError(f"无法读取配置文件：{source}。原文件已保留，请检查文件内容与权限。") from exc
            self._merge(self.config, loaded)
            # Upgrades keep 1.x's automatic direction; fresh installs default to Simplified Chinese.
            if "trans_target" not in loaded:
                self.config["trans_target"] = "auto"
            self.config["trans_source"] = valid_language(self.config.get("trans_source"))
            self.config["trans_target"] = valid_language(self.config.get("trans_target"), "zh-CN")
            self.config["config_version"] = 2
            if source != destination:
                self.save()
                self.migrated_from = source
        else:
            self.save()

    def _merge(self, base, loaded):
        """Merges saved values over the defaults, descending into nested dicts.

        A plain dict.update() would replace trans_api wholesale, so credential
        fields introduced in a later version would vanish for anyone with an
        older config.json on disk.
        """
        for key, value in loaded.items():
            if key in base and type(value) is not type(base[key]):
                raise RuntimeError(f"配置字段 {key} 的类型不正确，原文件已保留。")
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                self._merge(base[key], value)
            else:
                base[key] = value

    def save(self):
        path = self.paths.config_file
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=".config-", suffix=".tmp", delete=False) as f:
                temporary = Path(f.name)
                json.dump(self.config, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def get(self, key):
        return self.config.get(key, DEFAULT_CONFIG.get(key))

    def import_legacy(self, path):
        """Import an explicitly selected old config without modifying the source."""
        path = Path(path)
        try:
            loaded = json.loads(path.read_text(encoding='utf-8-sig'))
            if not isinstance(loaded, dict):
                raise ValueError('配置根节点不是对象')
        except (ValueError, OSError) as exc:
            raise RuntimeError('所选文件不是可读取的配置文件，现有配置未修改。') from exc
        values = copy.deepcopy(DEFAULT_CONFIG)
        self._merge(values, loaded)
        values['trans_source'] = valid_language(values.get('trans_source'))
        values['trans_target'] = valid_language(loaded.get('trans_target'), 'auto')
        values['config_version'] = 2
        self.update(values)

    def set(self, key, value):
        self.update({key: value})

    def update(self, values):
        previous = copy.deepcopy(self.config)
        try:
            self._merge(self.config, values)
            self.save()
        except (OSError, RuntimeError):
            self.config = previous
            raise
        if "auto_start" in values and previous.get("auto_start") != values["auto_start"]:
            self.update_startup_registry(values["auto_start"])

    def update_startup_registry(self, enable):
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "LightweightScreenshotTool"

        # Determine startup command
        if getattr(sys, 'frozen', False):
            # Compiled executable
            cmd = f'"{sys.executable}"'
        else:
            # Script running via Python
            script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "main.py"))
            cmd = f'"{sys.executable}" "{script_path}" --minimized'

        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            if enable:
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, app_name)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception as e:
            print(f"Failed to update startup registry: {e}")
