import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location("protection_service", Path(__file__).resolve().parents[2] / "system/protection_service.py")
helper = importlib.util.module_from_spec(spec)


@pytest.fixture(autouse=True)
def load_helper():
    spec.loader.exec_module(helper)


def policy(**values):
    return {"ipv6_protection": True, "dns_protection": True, "kill_switch": False, "allow_lan": False, **values}


def test_ipv6_block_applies_before_vpn_and_dns_allows_only_bootstrap():
    rules = helper.render_rules(policy(), None, [{"ip": "203.0.113.5", "port": 443}], preparing=True)
    assert "meta nfproto ipv6 reject" in rules
    assert "udp dport 53 accept" in rules
    assert "flush ruleset" not in rules


def test_connected_rules_allow_tunnel_before_dns_rejection():
    rules = helper.render_rules(policy(), "tun0", [])
    assert rules.index('oifname "tun0" accept') < rules.index("udp dport 53 reject")
    assert "tcp dport 53 reject" in rules
    assert "udp dport 53 accept" not in rules


def test_kill_switch_blocks_both_families_without_tunnel():
    rules = helper.render_rules(policy(kill_switch=True), None, [])
    assert "reject with icmpx type admin-prohibited" in rules
    assert "ip daddr 192.168.0.0/16 accept" not in rules


@pytest.mark.parametrize("interface", ['tun0"; flush ruleset;', "wlp3s0", "../tun0"])
def test_helper_rejects_untrusted_interface(interface):
    with pytest.raises(ValueError):
        helper.render_rules(policy(), interface, [])


def test_helper_rejects_endpoint_injection_and_invalid_ports():
    for endpoint in ({"ip": "1.1.1.1; flush ruleset", "port": 443}, {"ip": "1.1.1.1", "port": -1}):
        with pytest.raises(ValueError):
            helper.render_rules(policy(), None, [endpoint])


def test_policy_validation_rejects_non_boolean_or_extra_fields():
    with pytest.raises(ValueError):
        helper.validate_policy({**policy(), "kill_switch": "false"})
    with pytest.raises(ValueError):
        helper.validate_policy({**policy(), "command": "sh"})


def test_peer_authentication_requires_configured_uid():
    helper.authorize_peer(1000, 1000)
    with pytest.raises(PermissionError):
        helper.authorize_peer(1001, 1000)


def test_failed_activation_releases_ordinary_rules_but_not_kill_switch(tmp_path):
    calls = []
    controller = helper.ProtectionController(tmp_path / "state.json", apply=lambda text: calls.append(text), discover=lambda: None)
    controller.handle({"action": "configure", "policy": policy()})
    controller.handle({"action": "prepare", "endpoints": [{"ip": "203.0.113.5", "port": 443}]})
    controller.handle({"action": "release"})
    assert calls[-1].strip() == "destroy table inet northstar_vpn"
    controller.handle({"action": "configure", "policy": policy(kill_switch=True)})
    controller.handle({"action": "release"})
    assert "reject with icmpx type admin-prohibited" in calls[-1]


def test_preparation_timeout_cleans_up_without_ui(tmp_path):
    now = [0.0]
    calls = []
    controller = helper.ProtectionController(tmp_path / "state.json", apply=calls.append, discover=lambda: None, clock=lambda: now[0])
    controller.handle({"action": "prepare", "endpoints": []})
    now[0] = 121
    controller.reconcile()
    assert calls[-1].strip() == "destroy table inet northstar_vpn"


def test_controller_recovers_kill_switch_setting_after_restart(tmp_path):
    path = tmp_path / "state.json"
    first = helper.ProtectionController(path, apply=lambda _: None, discover=lambda: None)
    first.handle({"action": "configure", "policy": policy(kill_switch=True)})
    calls = []
    second = helper.ProtectionController(path, apply=calls.append, discover=lambda: None)
    second.reconcile()
    assert "reject with icmpx type admin-prohibited" in calls[-1]


def test_prepared_rules_survive_old_tunnel_disappearing_during_switch(tmp_path):
    tunnel = ["tun0"]
    calls = []
    controller = helper.ProtectionController(tmp_path / "state.json", apply=calls.append, discover=lambda: tunnel[0])
    controller.handle({"action": "prepare", "endpoints": []})
    tunnel[0] = None
    controller.reconcile()
    assert "meta nfproto ipv6 reject" in calls[-1]


def test_commit_requires_verified_tunnel(tmp_path):
    controller = helper.ProtectionController(tmp_path / "state.json", apply=lambda _: None, discover=lambda: None)
    with pytest.raises(RuntimeError, match="tunnel"):
        controller.handle({"action": "commit"})


def test_socket_permissions_set_before_changing_owner(monkeypatch):
    calls = []
    class SocketPath:
        def chmod(self, mode):
            calls.append(("chmod", mode))
    monkeypatch.setattr(helper.os, "chown", lambda path, uid, gid: calls.append(("chown", uid)))
    helper.secure_socket(SocketPath(), 1000)
    assert calls == [("chmod", 0o600), ("chown", 1000)]


def test_active_endpoint_is_preserved_during_preparation(tmp_path):
    calls = []
    controller = helper.ProtectionController(tmp_path / "state.json", apply=calls.append, discover=lambda: None)
    controller.handle({"action": "prepare", "endpoints": [{"ip": "203.0.113.5", "port": 443}]})
    controller.handle({"action": "prepare", "endpoints": []})
    assert "ip daddr 203.0.113.5" in calls[-1]


def test_lan_exception_does_not_bypass_dns_protection():
    rules = helper.render_rules(policy(allow_lan=True), "tun0", [])
    assert rules.index("udp dport 53 reject") < rules.index("ip daddr 192.168.0.0/16 accept")


def test_saved_kill_switch_is_applied_before_failed_discovery(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(helper.json.dumps({"policy": policy(kill_switch=True), "endpoints": []}))
    calls = []
    def unavailable():
        raise RuntimeError("NetworkManager is starting")
    controller = helper.ProtectionController(path, apply=calls.append, discover=unavailable)
    with pytest.raises(RuntimeError):
        controller.reconcile()
    assert calls and "reject with icmpx type admin-prohibited" in calls[0]


def test_disabled_protection_skips_confirmation_without_helper(tmp_path):
    from app.settings import SettingsStore
    from app.protection import ProtectionClient
    settings = SettingsStore(tmp_path / "settings.json")
    settings.save({"ipv6_protection": False, "dns_protection": False, "kill_switch": False})
    client = ProtectionClient(settings, str(tmp_path / "missing.sock"))
    assert client.confirm()["required"] is False
