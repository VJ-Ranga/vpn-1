import json
import os
from pathlib import Path
import threading

DEFAULTS = {"transport": "udp", "theme": "light", "ipv6_protection": True, "dns_protection": True, "kill_switch": False, "allow_lan": False, "auto_reconnect": False}


class SettingsStore:
    def __init__(self, path=None):
        self.path = Path(path or Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config")) / "northstar-vpn/settings.json")
        self.lock = threading.RLock()

    def get(self):
        with self.lock:
            try:
                return {**DEFAULTS, **self.validate(json.loads(self.path.read_text()))}
            except (OSError, ValueError, TypeError):
                return dict(DEFAULTS)

    @staticmethod
    def validate(values):
        if not isinstance(values, dict) or set(values) - set(DEFAULTS):
            raise ValueError("Unknown setting")
        for key, value in values.items():
            if key == "transport" and value not in ("tcp", "udp"):
                raise ValueError("Choose TCP or UDP")
            if key == "theme" and value not in ("light", "dark", "system"):
                raise ValueError("Invalid theme")
            if type(DEFAULTS[key]) is bool and type(value) is not bool:
                raise ValueError("Invalid setting value")
        return values

    def save(self, values):
        with self.lock:
            values = {**self.get(), **self.validate(values)}
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(values))
            temporary.chmod(0o600)
            temporary.replace(self.path)
            return values
