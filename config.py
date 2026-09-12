import os
import json
import sys
import copy
import winreg

DEFAULT_CONFIG = {
    "hotkey_region": "F1",
    "hotkey_fullscreen": "F2",
    "save_dir": os.path.join(os.path.expanduser("~"), "Pictures"),
    "auto_start": False,
    "ocr_review": True,
    # "auto" keeps the key-free Google -> MyMemory chain. Any other value
    # names an engine from translator.ENGINE_LABELS and is tried first.
    "trans_engine": "auto",
    # Credentials per engine, shaped like translator.ENGINE_FIELDS.
    "trans_api": {
        "azure": {"key": "", "region": "global"},
        "llm": {"base_url": "https://api.deepseek.com/v1", "key": "", "model": "deepseek-chat"},
        "baidu": {"appid": "", "secret": ""},
        "youdao": {"appid": "", "secret": ""},
        "deepl": {"key": ""},
    },
}

CONFIG_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

class ConfigManager:
    def __init__(self):
        # deepcopy, not copy: a shallow copy would let edits to trans_api leak
        # into DEFAULT_CONFIG and corrupt the fallback values.
        self.config = copy.deepcopy(DEFAULT_CONFIG)
        self.load()

    def load(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self._merge(self.config, loaded)
            except Exception as e:
                print(f"Failed to load config: {e}")
        else:
            self.save()

    def _merge(self, base, loaded):
        """Merges saved values over the defaults, descending into nested dicts.

        A plain dict.update() would replace trans_api wholesale, so credential
        fields introduced in a later version would vanish for anyone with an
        older config.json on disk.
        """
        for key, value in loaded.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                self._merge(base[key], value)
            else:
                base[key] = value

    def save(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Failed to save config: {e}")

    def get(self, key):
        return self.config.get(key, DEFAULT_CONFIG.get(key))

    def set(self, key, value):
        self.config[key] = value
        self.save()
        if key == "auto_start":
            self.update_startup_registry(value)

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
