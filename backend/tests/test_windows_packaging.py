import importlib.util
import hashlib
import hmac
import json
from pathlib import Path
import sys

import pytest

import windows_entry


def load_packaged_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "app" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_adapter_uses_only_installed_token_and_endpoint(monkeypatch, tmp_path):
    resources = tmp_path / "resources"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(resources / "backend" / "NorthstarBackend.exe"))
    monkeypatch.setenv("ProgramData", str(tmp_path / "ProgramData"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("VPN_WINDOWS_HELPER_TOKEN", "untrusted")
    monkeypatch.setenv("VPN_WINDOWS_HELPER_HOST", "192.0.2.1")
    monkeypatch.setenv("VPN_WINDOWS_HELPER_PORT", "invalid")
    monkeypatch.setenv("VPN_PROFILE_ROOT", str(tmp_path / "untrusted-profiles"))
    module = load_packaged_module("app._packaged_windows", "windows_openvpn.py")
    token = tmp_path / "ProgramData" / "NorthstarVPN" / "helper.token"
    token.parent.mkdir(parents=True)
    token.write_text("installed-token\n", encoding="utf-8")
    adapter = module.WindowsOpenVpnAdapter(token="also-untrusted", helper_host="remote", helper_port=1)
    assert module.token_path() == token
    assert adapter.token == "installed-token"
    assert (adapter.helper_host, adapter.helper_port) == ("127.0.0.1", 8799)
    assert adapter.root == resources / "profiles"
    token.unlink()
    assert module.WindowsOpenVpnAdapter().token == ""


def test_frozen_main_finds_installed_frontend_and_profiles(monkeypatch, tmp_path):
    resources = tmp_path / "resources"
    frontend = resources / "frontend" / "dist"
    frontend.mkdir(parents=True)
    (frontend / "index.html").write_text("packaged UI", encoding="utf-8")
    (resources / "profiles").mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(resources / "backend" / "NorthstarBackend.exe"))
    monkeypatch.setenv("VPN_PROFILE_ROOT", str(tmp_path / "untrusted"))
    module = load_packaged_module("app._packaged_main", "main.py")
    assert module.ROOT == resources
    assert module.frontend_dist == frontend
    assert module.catalog.root == resources / "profiles"
    assert any(getattr(route, "name", None) == "frontend" for route in module.app.routes)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.0.2.1", "localhost", "example.com"])
def test_entry_rejects_non_loopback_bind_without_starting_server(monkeypatch, host):
    monkeypatch.setattr(windows_entry.uvicorn, "run", lambda *args, **kwargs: pytest.fail("server started"))
    with pytest.raises(SystemExit):
        windows_entry.main(["--host", host])


@pytest.mark.parametrize("port", ["0", "65536", "invalid"])
def test_entry_rejects_invalid_port(port):
    with pytest.raises(SystemExit):
        windows_entry.main(["--port", port])


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_entry_starts_uvicorn_without_access_or_credential_logging(monkeypatch, host):
    calls = []
    monkeypatch.setattr(windows_entry.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    windows_entry.main(["--host", host, "--port", "12345"])
    assert calls == [(("app.main:app",), dict(host=host, port=12345, access_log=False,
                                           loop="asyncio", http="h11", ws="none"))]


class HelperSocket:
    def __init__(self, challenge_response=None):
        self.sent = []
        self.replies = []
        self.challenge_response = challenge_response
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def sendall(self, data):
        message = json.loads(data)
        self.sent.append(message)
        if message["action"] == "challenge":
            assert set(message) == {"action", "nonce"}
            assert len(message["nonce"]) == 64
            bytes.fromhex(message["nonce"])
            proof = hmac.new(b"installed-token", b"northstar-helper-v1:" + message["nonce"].encode("ascii"), hashlib.sha256).hexdigest()
            response = self.challenge_response if self.challenge_response is not None else {"ok": True, "proof": proof}
        else:
            response = {"ok": True}
        self.replies.append(json.dumps(response).encode() + b"\n")

    def recv(self, size):
        return self.replies.pop(0) if self.replies else b""


def packaged_adapter(monkeypatch, connection):
    from app import windows_openvpn

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(windows_openvpn, "read_token_file", lambda: "installed-token")
    connections = []

    def create_connection(endpoint, timeout):
        connections.append(endpoint)
        assert endpoint == ("127.0.0.1", 8799)
        return connection

    monkeypatch.setattr(windows_openvpn.socket, "create_connection", create_connection)
    return windows_openvpn.WindowsOpenVpnAdapter(), connections


@pytest.mark.parametrize("response", [
    {"ok": True, "proof": "0" * 64},
    {"ok": True, "proof": "non-ascii-\u2603"},
    {"ok": True},
    {"ok": True, "proof": 123},
    {"ok": False, "proof": "0" * 64},
    [],
])
def test_frozen_adapter_never_sends_credentials_to_unverified_helper(monkeypatch, response):
    from app.network_manager import NetworkManagerError

    connection = HelperSocket(response)
    adapter, connections = packaged_adapter(monkeypatch, connection)
    with pytest.raises(NetworkManagerError, match="helper authentication failed"):
        adapter._request("connect", username="private-user", password="private-password")
    assert len(connections) == 1
    assert len(connection.sent) == 1
    assert connection.sent[0]["action"] == "challenge"
    assert connection.closed


def test_frozen_adapter_authenticates_then_sends_request_on_same_socket(monkeypatch):
    connection = HelperSocket()
    adapter, connections = packaged_adapter(monkeypatch, connection)
    assert adapter._request("connect", username="private-user", password="private-password") == {"ok": True}
    assert len(connections) == 1
    assert [message["action"] for message in connection.sent] == ["challenge", "connect"]
    assert connection.sent[1] == {"action": "connect", "token": "installed-token", "username": "private-user", "password": "private-password"}
    assert connection.closed


def test_development_adapter_preserves_single_request_protocol(monkeypatch):
    from app import windows_openvpn

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    connection = HelperSocket()
    monkeypatch.setattr(windows_openvpn.socket, "create_connection", lambda *args, **kwargs: connection)
    adapter = windows_openvpn.WindowsOpenVpnAdapter(token="development-token")
    assert adapter._request("health") == {"ok": True}
    assert connection.sent == [{"action": "health", "token": "development-token"}]
