import platform

from app.main import manager


def test_platform_specific_vpn_adapter_is_selected():
    if platform.system() == "Windows":
        from app.windows_openvpn import WindowsOpenVpnAdapter

        assert isinstance(manager, WindowsOpenVpnAdapter)
    else:
        from app.network_manager import NetworkManagerAdapter

        assert isinstance(manager, NetworkManagerAdapter)


def test_windows_adapter_rejects_endpoint_outside_profile(tmp_path):
    if platform.system() != "Windows":
        return
    from app.profiles import Profile
    from app.windows_openvpn import WindowsOpenVpnAdapter

    path = tmp_path / "NCVPN-US-Chicago-TCP.ovpn"
    path.write_text("client\n")
    profile = Profile("profile-1", path, "tcp", "US", "Chicago", False)
    adapter = WindowsOpenVpnAdapter(root=tmp_path)
    try:
        adapter.import_profile(profile, "attacker.example")
    except Exception as exc:
        assert "endpoint" in str(exc)
    else:
        raise AssertionError("expected endpoint validation error")


def test_windows_health_reports_helper_and_platform_capabilities(monkeypatch):
    from app.windows_openvpn import WindowsOpenVpnAdapter

    adapter = WindowsOpenVpnAdapter()
    adapter._request = lambda action, **values: {
        "ok": True,
        "openvpn": True,
        "connected": False,
    }
    health = adapter.health()
    assert health["platform"] == "windows"
    assert health["vpn_backend"] == "openvpn-helper"
    assert health["reachable"] is True
    assert health["helper"] == {"available": True}
    assert health["openvpn_exe"] is True
    assert health["openvpn_plugin"] is True
    # network_manager stays false: it is only kept for frontend compatibility.
    assert health["network_manager"] is False
    assert health["protection_available"] is False


def test_windows_health_reports_helper_unreachable():
    from app.network_manager import NetworkManagerError
    from app.windows_openvpn import WindowsOpenVpnAdapter

    adapter = WindowsOpenVpnAdapter()

    def fail(action, **values):
        raise NetworkManagerError("helper connection closed")

    adapter._request = fail
    health = adapter.health()
    assert health["reachable"] is False
    assert health["helper"] == {"available": False}
    assert health["network_manager"] is False
