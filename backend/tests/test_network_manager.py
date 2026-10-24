from types import SimpleNamespace

from app.network_manager import NetworkManagerAdapter
from app.profiles import Profile
from app.secrets import Credentials


class Runner:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def run(self, args, timeout=90, input_text=None):
        self.calls.append((args, timeout, input_text))
        return next(self.responses)


def result(stdout="", returncode=0):
    return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)


def profile(tmp_path):
    path = tmp_path / "NCVPN-DE-Frankfurt-UDP.ovpn"
    path.write_text("client\n")
    return Profile("profile-1", path, "udp", "DE", "Frankfurt", False)


def test_import_returns_uuid_and_connect_uses_same_uuid(tmp_path):
    runner = Runner([result("Connection 'imported' (12345678-1234-1234-1234-123456789abc) successfully added.\n"), result(), result(), result(),])
    adapter = NetworkManagerAdapter(runner)

    connection_id = adapter.import_profile(profile(tmp_path))
    adapter.connect(connection_id, Credentials("user", "secret"))

    assert connection_id == "12345678-1234-1234-1234-123456789abc"
    assert runner.calls[2][0] == ["nmcli", "connection", "modify", "uuid", connection_id, "vpn.user-name", "user"]
    assert runner.calls[3][0] == ["nmcli", "--ask", "connection", "up", "uuid", connection_id]
    assert runner.calls[3][2] == "secret\n"
    assert "secret" not in " ".join(runner.calls[3][0])


def test_active_parses_uuid_and_runtime_details():
    runner = Runner([
        result("Namecheap VPN / DE Frankfurt / UDP:12345678-1234-1234-1234-123456789abc:vpn:tun0\n"),
        result("connection.timestamp:1700000000\nvpn.data:proto-tcp = no, remote = fra-c01.vpn.example:1194\n"),
        result("IP4.ADDRESS[1]:10.8.0.2/24\n"),
        result("VPN.GATEWAY:203.0.113.10\n"),
    ])
    active = NetworkManagerAdapter(runner).active()

    assert active.connection_id == "12345678-1234-1234-1234-123456789abc"
    assert active.name == "Namecheap VPN / DE Frankfurt / UDP"
    assert active.interface == "tun0"
    assert active.vpn_ip == "10.8.0.2"
    assert active.remote_endpoint == "203.0.113.10"


def test_health_detects_openvpn_plugin_service_not_generic_vpn_connection(monkeypatch, tmp_path):
    plugin = tmp_path / "nm-openvpn-service"
    plugin.write_text("")
    plugin.chmod(0o755)
    runner = Runner([result("running\n")])
    adapter = NetworkManagerAdapter(runner, plugin_paths=[plugin])

    health = adapter.health()

    assert health == {"network_manager": True, "openvpn_plugin": True}
    assert len(runner.calls) == 1


def test_health_detects_openvpn_service_marker(tmp_path):
    marker = tmp_path / "nm-openvpn-service.name"
    marker.write_text("[VPN Service]\nname=org.freedesktop.NetworkManager.openvpn\n")
    runner = Runner([result("running\n")])
    adapter = NetworkManagerAdapter(runner, plugin_paths=[marker])

    assert adapter.health() == {"network_manager": True, "openvpn_plugin": True}


def test_health_ignores_non_executable_service_file(tmp_path):
    plugin = tmp_path / "nm-openvpn-service"
    plugin.write_text("")
    runner = Runner([result("running\n")])
    adapter = NetworkManagerAdapter(runner, plugin_paths=[plugin])

    assert adapter.health() == {"network_manager": True, "openvpn_plugin": False}


def test_active_uses_tunnel_not_underlying_wifi():
    runner = Runner([
        result("Namecheap VPN / AU Melbourne / TCP:12345678-1234-1234-1234-123456789abc:vpn:wlp3s0\n"),
        result("connection.timestamp:1700000000\nvpn.data:proto-tcp = yes, remote = mel.example:443\n"),
        result("IP4.ADDRESS[1]:172.21.88.98/23\nVPN.GATEWAY:103.209.254.175\n"),
        result('[{"ifname":"wlp3s0","addr_info":[{"local":"192.168.1.181"}]},{"ifname":"tun0","addr_info":[{"local":"172.21.88.98"}]}]'),
    ])
    active = NetworkManagerAdapter(runner).active()
    assert active.interface == "tun0"
    assert active.vpn_ip == "172.21.88.98"
    assert active.remote_endpoint == "103.209.254.175"


def test_profile_change_invalidates_cached_import(tmp_path):
    p = profile(tmp_path)
    runner = Runner([
        result("Connection 'one' (12345678-1234-1234-1234-123456789abc) added."), result(),
        result("Connection 'two' (12345678-1234-1234-1234-123456789def) added."), result(),
    ])
    adapter = NetworkManagerAdapter(runner)
    first = adapter.import_profile(p)
    p.path.write_text("client\nremote new.example 1194\n")
    assert adapter.import_profile(p) != first


def test_endpoint_override_rejects_host_outside_profile(tmp_path):
    import pytest
    from app.network_manager import NetworkManagerError
    with pytest.raises(NetworkManagerError, match="endpoint"):
        NetworkManagerAdapter(Runner([])).import_profile(profile(tmp_path), "attacker.example")


def test_routed_endpoint_matches_vpn_default_route_metric():
    runner = Runner([result('[{"dst":"default","dev":"tun0","metric":50},{"dst":"default","dev":"wlp3s0","metric":600},{"dst":"108.171.108.135","dev":"wlp3s0","protocol":"static","metric":50},{"dst":"192.168.1.1","dev":"wlp3s0","protocol":"static","metric":50}]')])
    assert NetworkManagerAdapter(runner)._routed_endpoint("tun0") == "108.171.108.135"
