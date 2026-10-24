from fastapi.testclient import TestClient
from pathlib import Path

import app.main as main
from app.secrets import Credentials
from app.profiles import Profile, Server


class Store:
    def __init__(self):
        self.value = None

    def get(self):
        return self.value

    def save(self, value):
        self.value = value

    def clear(self):
        self.value = None


def test_credentials_api_never_returns_password(monkeypatch):
    store = Store()
    monkeypatch.setattr(main, "store", store)
    client = TestClient(main.app)

    response = client.put("/api/settings/credentials", headers={"X-CSRF-Token": "local-ui"}, json={"username": "user", "password": "secret"})

    assert response.status_code == 200
    assert response.json() == {"configured": True, "username": "user"}
    assert client.get("/api/settings/credentials").json() == {"configured": True, "username": "user"}
    assert "secret" not in response.text


def test_state_change_requires_csrf_token():
    response = TestClient(main.app).post("/api/disconnect")

    assert response.status_code == 403


def test_built_frontend_is_served_without_intercepting_api(monkeypatch, tmp_path):
    index = tmp_path / "index.html"
    index.write_text("<html>built</html>")
    monkeypatch.setattr(main, "frontend_dist", tmp_path)
    main.mount_frontend()
    client = TestClient(main.app)

    assert client.get("/").status_code == 200
    assert client.get("/api/health").status_code == 200


def test_profiles_api_returns_remote_servers_without_credentials(monkeypatch):
    profile = Profile("profile-1", Path("profile.ovpn"), "udp", "US", "Chicago", False, (Server("cmb-c01.vpn.wlvpn.com", 1194),))
    monkeypatch.setattr(main.catalog, "list", lambda: [profile])

    response = TestClient(main.app).get("/api/profiles")

    assert response.status_code == 200
    assert response.json()["profiles"][0]["servers"] == [{"host": "cmb-c01.vpn.wlvpn.com", "port": 1194}]
    assert "password" not in response.text.lower()


def test_settings_api_rejects_unavailable_protocol():
    response = TestClient(main.app).put("/api/settings", headers={"X-CSRF-Token": "local-ui"}, json={"transport": "wireguard"})
    assert response.status_code == 400


def test_api_rejects_foreign_origin_even_with_csrf_header():
    response = TestClient(main.app).post("/api/disconnect", headers={"X-CSRF-Token": "local-ui", "Origin": "https://attacker.example"})
    assert response.status_code == 403


def test_speed_test_calls_diagnostics_module(monkeypatch):
    from app import diagnostics
    monkeypatch.setattr(diagnostics, "run_cloudflare_speed_test", lambda: {"download_mbps": 12})
    response = TestClient(main.app).post("/api/speed-test", headers={"X-CSRF-Token": "local-ui"})
    assert response.status_code == 200
    assert response.json()["download_mbps"] == 12


def test_failed_switch_is_not_success_when_old_tunnel_remains(monkeypatch):
    monkeypatch.setattr(main.service, "connect", lambda *args: {"state": "connected", "error": "Protection setup failed; old tunnel remains"})
    response = TestClient(main.app).post("/api/connect", headers={"X-CSRF-Token": "local-ui"}, json={"profile_id": "new"})
    assert response.status_code == 502
