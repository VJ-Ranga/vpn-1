import importlib.util
from pathlib import Path

import pytest

HELPER_PATH = Path(__file__).resolve().parents[2] / "system" / "windows_helper.py"
SPEC = importlib.util.spec_from_file_location("northstar_windows_helper", HELPER_PATH)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)

SAMPLE = """client
dev tun
proto tcp
remote a.example.com 443
remote b.example.com 443
remote-random
resolv-retry infinite
nobind
persist-key
persist-tun
persist-remote-ip
verify-x509-name a-example name-prefix
remote-cert-tls server
auth-user-pass
verb 3
auth SHA256
data-ciphers AES-256-GCM:AES-256-CBC
data-ciphers-fallback AES-256-CBC
tls-cipher TLS-DHE-RSA-WITH-AES-256-CBC-SHA
<ca>
-----BEGIN CERTIFICATE-----
AAAA
-----END CERTIFICATE-----
</ca>
"""


def test_official_style_profile_is_rebuilt_safely():
    config, remotes, transport = helper.sanitize_profile(SAMPLE)
    assert transport == "tcp"
    assert remotes == [("a.example.com", 443), ("b.example.com", 443)]
    assert "proto tcp-client" in config
    assert "remote a.example.com 443" in config
    assert "remote b.example.com 443" in config
    assert "remote-random" in config
    assert "remote-cert-tls server" in config
    assert "verify-x509-name a-example name-prefix" in config
    assert "data-ciphers AES-256-GCM:AES-256-CBC" in config
    assert "auth SHA256" in config
    assert "<ca>" in config and "</ca>" in config
    # auth-user-pass is supplied by the helper on the command line, not copied.
    assert "auth-user-pass" not in config


def test_endpoint_selection_replaces_remote_list():
    config, remotes, _ = helper.sanitize_profile(SAMPLE, "b.example.com", 443)
    assert remotes == [("b.example.com", 443)]
    assert "remote b.example.com 443" in config
    assert "remote a.example.com 443" not in config


@pytest.mark.parametrize(
    "directive",
    [
        "plugin evil.dll",
        "script-security 2",
        "up C:\\evil.exe",
        "down C:\\evil.exe",
        "win-sys C:\\Users\\Public",
        "config other.ovpn",
        "log C:\\Windows\\Temp\\x.log",
        "ca ca.crt",
        "pkcs12 bundle.p12",
        "management 127.0.0.1 9000",
        "allow-nonadmin",
        "compress",
    ],
)
def test_dangerous_directives_are_rejected(directive):
    with pytest.raises(ValueError):
        helper.sanitize_profile(SAMPLE + directive + "\n")


def test_unknown_directives_are_rejected():
    with pytest.raises(ValueError):
        helper.sanitize_profile(SAMPLE + "totally-new-option value\n")


def test_external_auth_file_is_rejected():
    with pytest.raises(ValueError):
        helper.sanitize_profile(SAMPLE.replace("auth-user-pass", "auth-user-pass creds.txt"))


def test_profile_requires_inline_ca():
    with pytest.raises(ValueError):
        helper.sanitize_profile(SAMPLE.replace("<ca>\n-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n</ca>", ""))


def test_endpoint_injection_and_mismatch_are_rejected():
    with pytest.raises(ValueError):
        helper.sanitize_profile(SAMPLE, "a.example.com\nplugin evil.dll", 443)
    with pytest.raises(ValueError):
        helper.sanitize_profile(SAMPLE, "attacker.example", 443)
    with pytest.raises(ValueError):
        helper.sanitize_profile(SAMPLE, "a.example.com", 444)


@pytest.mark.parametrize("value", [True, False, 0, 65536, "not-a-port", None, -1])
def test_invalid_ports_are_rejected(value):
    with pytest.raises(ValueError):
        helper.validate_port(value)


@pytest.mark.parametrize("host", ["-evil", "a b", "a;b", "a\\b", "a#b", "a\nb", "", "a" * 254])
def test_invalid_endpoints_are_rejected(host):
    with pytest.raises(ValueError):
        helper.validate_endpoint(host)


def test_private_endpoint_is_rejected(monkeypatch):
    monkeypatch.setattr(helper, "ALLOW_PRIVATE_ENDPOINTS", False)
    with pytest.raises(ValueError):
        helper.ensure_public_endpoint("127.0.0.1", 1194)


def test_read_profile_rejects_traversal_and_extension(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.ovpn"
    outside.write_text("client\n")
    with pytest.raises(ValueError):
        helper.read_profile(outside, root)
    wrong = root / "profile.txt"
    wrong.write_text("client\n")
    with pytest.raises(ValueError):
        helper.read_profile(wrong, root)


def test_authorization_is_constant_time_and_rejects_bad_types():
    token = "x" * 48
    assert helper.authorized({"token": token}, token)
    assert not helper.authorized({"token": "y" * 48}, token)
    assert not helper.authorized({"token": 123}, token)
    assert not helper.authorized({"token": "\u2603" * 48}, token)


def test_handle_request_rejects_unauthorized_and_non_dict(tmp_path):
    state = helper.HelperState(tmp_path)
    assert helper.handle_request(state, ["not-a-dict"], "x" * 48)["error"] == "invalid request"
    assert helper.handle_request(state, {"token": "wrong", "action": "health"}, "x" * 48)["error"] == "unauthorized"


def test_load_token_rejects_missing_and_weak(tmp_path, monkeypatch):
    missing = tmp_path / "helper.token"
    monkeypatch.setattr(helper, "token_path", lambda: missing)
    monkeypatch.delenv("VPN_WINDOWS_HELPER_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        helper.load_token(None)
    with pytest.raises(SystemExit):
        helper.load_token("short")
    with pytest.raises(SystemExit):
        helper.load_token("northstar-dev-token")
    token = "z" * 48
    assert helper.load_token(token) == token


def test_load_token_reads_restricted_file(tmp_path, monkeypatch):
    token_file = tmp_path / "helper.token"
    token_file.write_text("q" * 48, encoding="utf-8")
    monkeypatch.setattr(helper, "token_path", lambda: token_file)
    monkeypatch.delenv("VPN_WINDOWS_HELPER_TOKEN", raising=False)
    assert helper.load_token(None) == "q" * 48
