import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "ipv6_guard_helper", Path(__file__).resolve().parents[2] / "system" / "windows_helper.py"
)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


def test_guard_uses_fixed_script_and_action(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"blocked": True}))

    monkeypatch.setattr(helper.subprocess, "run", run)
    helper.IPv6Guard().enable()
    args, kwargs = calls[0]
    assert args[-2:] == ["-Action", "Enable"]
    assert args[-3].endswith("windows-ipv6-guard.ps1")
    assert kwargs["timeout"] == 20
    assert "shell" not in kwargs


@pytest.mark.parametrize("result", [
    SimpleNamespace(returncode=1, stdout=""),
    SimpleNamespace(returncode=0, stdout="bad json"),
    SimpleNamespace(returncode=0, stdout='{"blocked":false}'),
    SimpleNamespace(returncode=0, stdout='{"blocked":"true"}'),
])
def test_guard_fails_closed(monkeypatch, result):
    monkeypatch.setattr(helper.subprocess, "run", lambda *a, **k: result)
    with pytest.raises(helper.HelperError):
        helper.IPv6Guard().enable()


def test_guard_timeout_fails_closed(monkeypatch):
    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired("powershell", 20)

    monkeypatch.setattr(helper.subprocess, "run", run)
    with pytest.raises(helper.HelperError):
        helper.IPv6Guard().enable()


def test_guard_must_succeed_before_process_launch(tmp_path, monkeypatch):
    state = helper.HelperState(tmp_path)
    monkeypatch.setattr(helper, "read_profile", lambda *a: "profile")
    monkeypatch.setattr(helper, "sanitize_profile", lambda *a: ("config", [("vpn.example", 1194)], "udp"))
    monkeypatch.setattr(helper, "ensure_public_endpoint", lambda *a: None)
    calls = []

    def fail():
        calls.append("guard")
        raise helper.HelperError("guard failed")

    monkeypatch.setattr(state.ipv6_guard, "enable", fail)
    monkeypatch.setattr(helper.subprocess, "Popen", lambda *a, **k: calls.append("process"))
    with pytest.raises(helper.HelperError):
        state.connect("profile1", "unused.ovpn", username="test", password="test")
    assert calls == ["guard"]


def test_only_explicit_disconnect_releases_guard(tmp_path, monkeypatch):
    state = helper.HelperState(tmp_path)
    calls = []
    monkeypatch.setattr(state.ipv6_guard, "disable", lambda: calls.append("release"))
    state.disconnect_locked()
    assert calls == []
    state.disconnect()
    assert calls == ["release"]


def test_lost_guard_stops_vpn(tmp_path, monkeypatch):
    state = helper.HelperState(tmp_path)
    calls = []
    state.process = SimpleNamespace(poll=lambda: None, terminate=lambda: calls.append("stop"), wait=lambda **k: None)
    monkeypatch.setattr(state.ipv6_guard, "blocked", lambda: False)
    health = state.health()
    assert calls == ["stop"]
    assert health["connected"] is False
    assert health["ipv6_blocked"] is False


def test_failed_guard_release_is_reported(tmp_path, monkeypatch):
    state = helper.HelperState(tmp_path)

    def fail():
        raise helper.HelperError("IPv6 remains blocked")

    monkeypatch.setattr(state.ipv6_guard, "disable", fail)
    result = helper.handle_request(state, {"action": "disconnect", "token": "x" * 48}, "x" * 48)
    assert result == {"ok": False, "error": "IPv6 remains blocked"}


def test_shutdown_signals_event_before_waiting():
    calls = []
    process = SimpleNamespace(poll=lambda: None, wait=lambda **k: calls.append("wait"),
                              terminate=lambda: calls.append("terminate"), kill=lambda: calls.append("kill"))
    event = SimpleNamespace(signal=lambda: calls.append("signal"), close=lambda: calls.append("close"))
    helper.stop_openvpn(process, event)
    assert calls == ["signal", "wait", "close"]


def test_shutdown_timeout_falls_back_and_closes_event():
    calls = []

    def wait(**kwargs):
        calls.append("wait")
        if calls.count("wait") == 1:
            raise subprocess.TimeoutExpired("openvpn", 15)

    process = SimpleNamespace(poll=lambda: None, wait=wait, kill=lambda: calls.append("kill"))
    event = SimpleNamespace(signal=lambda: calls.append("signal"), close=lambda: calls.append("close"))
    helper.stop_openvpn(process, event)
    assert calls == ["signal", "wait", "kill", "wait", "close"]
