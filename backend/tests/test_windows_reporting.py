import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

HELPER_PATH = Path(__file__).resolve().parents[2] / "system" / "windows_helper.py"
SPEC = importlib.util.spec_from_file_location("northstar_windows_reporting", HELPER_PATH)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)

SNAPSHOT = """OpenVPN STATISTICS
Updated,2026-01-01 00:00:00
TUN/TAP read bytes,123456
TUN/TAP write bytes,987654
TCP/UDP read bytes,999999
TCP/UDP write bytes,222222
END
"""


@pytest.fixture
def state(tmp_path):
    return helper.HelperState(tmp_path)


def test_status_counters_have_client_receive_send_directions():
    assert helper.HelperState._parse_status_counters(SNAPSHOT) == (987654, 123456)
    assert helper.HelperState._parse_status_counters(SNAPSHOT.replace("\n", "\r\n")) == (987654, 123456)


@pytest.mark.parametrize("text", [
    "", SNAPSHOT.replace("END", ""), SNAPSHOT.replace("123456", "-1"),
    SNAPSHOT.replace("123456", "1.2"),
    SNAPSHOT.replace("TUN/TAP read bytes,123456\n", ""),
    SNAPSHOT.replace("END", "TUN/TAP read bytes,5\nEND"),
    SNAPSHOT.replace("OpenVPN STATISTICS", "TITLE,OpenVPN"),
])
def test_incomplete_or_invalid_status_counters_are_rejected(text):
    assert helper.HelperState._parse_status_counters(text) is None


def test_zero_status_counters_are_valid():
    assert helper.HelperState._parse_status_counters(
        SNAPSHOT.replace("123456", "0").replace("987654", "0")
    ) == (0, 0)


def test_status_file_works_without_adapter_or_powershell(state, tmp_path, monkeypatch):
    status_path = tmp_path / "status.txt"
    status_path.write_text(SNAPSHOT, encoding="utf-8")
    def unexpected(*args, **kwargs):
        pytest.fail("Complete status snapshots must not query Windows")
    monkeypatch.setattr(helper.subprocess, "run", unexpected)
    assert state._counters(None, status_path) == (987654, 123456)


@pytest.mark.parametrize("contents", [None, SNAPSHOT.replace("END", ""), "x" * 65537])
def test_missing_partial_or_oversized_status_falls_back_to_dotnet(state, tmp_path, monkeypatch, contents):
    status_path = tmp_path / "status.txt"
    if contents is not None:
        status_path.write_text(contents, encoding="utf-8")
    def run(args, **kwargs):
        assert "NetworkInterface" in args[-1]
        assert "GetIPv4Statistics" in args[-1]
        assert "Get-NetAdapterStatistics" not in args[-1]
        assert kwargs["env"]["NS_IFACE"] == "Ethernet 3"
        return SimpleNamespace(returncode=0, stdout="100\n200\n")
    monkeypatch.setattr(helper.subprocess, "run", run)
    assert state._counters("Ethernet 3", status_path) == (100, 200)


def test_tunnel_ip_uses_selected_assigned_address_not_push_reply(state, tmp_path, monkeypatch):
    # A deliberately different pushed address must never become the display IP.
    state.log_path = tmp_path / "synthetic.log"
    state.log_path.write_text("PUSH_REPLY,ifconfig 10.8.0.1 255.255.255.0\n", encoding="utf-8")
    def run(args, **kwargs):
        assert "GetIPProperties" in args[-1]
        assert "Name -eq $env:NS_IFACE" in args[-1]
        assert "Get-NetAdapter" not in args[-1]
        assert kwargs["env"]["NS_IFACE"] == "Ethernet 3"
        return SimpleNamespace(returncode=0, stdout="0.0.0.0\n169.254.1.2\n127.0.0.1\ninvalid\n10.8.0.27\n")
    monkeypatch.setattr(helper.subprocess, "run", run)
    assert state._tunnel_ip("Ethernet 3") == "10.8.0.27"


def test_missing_interface_does_not_select_unrelated_adapter(state, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("No selected interface should produce unknown address/counters")
    monkeypatch.setattr(helper.subprocess, "run", unexpected)
    assert state._tunnel_ip(None) is None
    assert state._counters(None) == (0, 0)


@pytest.mark.parametrize("result", [
    SimpleNamespace(returncode=1, stdout="10.8.0.27\n"),
    SimpleNamespace(returncode=0, stdout="169.254.1.2\n"),
])
def test_invalid_or_failed_address_query_is_unknown(state, monkeypatch, result):
    monkeypatch.setattr(helper.subprocess, "run", lambda *args, **kwargs: result)
    assert state._tunnel_ip("Ethernet 3") is None


def test_query_failures_do_not_break_reporting(state, monkeypatch):
    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired("powershell", 5)
    monkeypatch.setattr(helper.subprocess, "run", run)
    assert state._tunnel_ip("Ethernet 3") is None
    assert state._counters("Ethernet 3") == (0, 0)


def test_status_passes_selected_interface_and_status_path(state, tmp_path, monkeypatch):
    state.process = SimpleNamespace(poll=lambda: None)
    state.connection_id = "test-vpn"
    state.status_path = tmp_path / "status.txt"
    monkeypatch.setattr(state, "_interface_name", lambda: "Ethernet 3")
    def tunnel_ip(interface):
        assert interface == "Ethernet 3"
        return "10.8.0.27"
    def counters(interface, status_path):
        assert interface == "Ethernet 3"
        assert status_path == state.status_path
        return 987654, 123456
    monkeypatch.setattr(state, "_tunnel_ip", tunnel_ip)
    monkeypatch.setattr(state, "_counters", counters)
    result = state.status()
    assert result["vpn_ip"] == "10.8.0.27"
    assert result["bytes_in"] == 987654
    assert result["bytes_out"] == 123456
