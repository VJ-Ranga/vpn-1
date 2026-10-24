import pytest
from app.settings import SettingsStore


def test_preferences_survive_restart_and_preserve_other_values(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    assert store.get()["ipv6_protection"] is True
    store.save({"theme": "dark", "kill_switch": True})
    restored = SettingsStore(path).get()
    assert restored["theme"] == "dark"
    assert restored["kill_switch"] is True
    assert restored["dns_protection"] is True


@pytest.mark.parametrize("value", [{"kill_switch": "false"}, {"theme": "invalid"}, {"transport": "wireguard"}, {"arbitrary_command": "sh"}])
def test_unknown_or_invalid_preferences_are_rejected(tmp_path, value):
    with pytest.raises(ValueError):
        SettingsStore(tmp_path / "settings.json").save(value)
