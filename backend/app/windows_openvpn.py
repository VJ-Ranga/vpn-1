import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import sys
from pathlib import Path

from .network_manager import ActiveConnection, NetworkManagerError

ROOT = Path(sys.executable).resolve().parent.parent / "profiles" if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
OPENVPN_EXE = Path(os.getenv("VPN_OPENVPN_EXE", r"C:\Program Files\OpenVPN\bin\openvpn.exe"))


def token_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(os.getenv("ProgramData", r"C:\ProgramData")) / "NorthstarVPN" / "helper.token"
    base = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "northstar-vpn" / "helper.token"


def read_token_file() -> str:
    try:
        return token_path().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in {"localhost"}


class WindowsOpenVpnAdapter:
    # Explicit Disconnect must also release a guard retained after a crash.
    disconnect_when_inactive = True

    def __init__(self, helper_host=None, helper_port=None, token=None, root=None):
        if getattr(sys, "frozen", False):
            self.helper_host = "127.0.0.1"
            self.helper_port = 8799
            self.token = read_token_file()
            self.root = ROOT
        else:
            self.helper_host = helper_host or os.getenv("VPN_WINDOWS_HELPER_HOST", "127.0.0.1")
            self.helper_port = int(helper_port or os.getenv("VPN_WINDOWS_HELPER_PORT", "8799"))
            self.token = token or os.getenv("VPN_WINDOWS_HELPER_TOKEN") or read_token_file()
            self.root = Path(root or os.getenv("VPN_PROFILE_ROOT", ROOT))
        self.imported = {}
        self.fingerprints = {}
        self.endpoints = {}
        self.connections = {}

    def _request(self, action, **values):
        if not is_loopback(self.helper_host):
            raise NetworkManagerError("helper host must be loopback")
        if not self.token:
            raise NetworkManagerError("helper token is not configured")
        with socket.create_connection((self.helper_host, self.helper_port), timeout=90) as client:
            data = bytearray()

            def receive():
                while b"\n" not in data:
                    chunk = client.recv(4096)
                    if not chunk:
                        raise NetworkManagerError("helper connection closed")
                    data.extend(chunk)
                    if len(data) > 65536:
                        raise NetworkManagerError("helper response too large")
                line, remaining = data.split(b"\n", 1)
                data[:] = remaining
                response = json.loads(line)
                if not isinstance(response, dict):
                    raise NetworkManagerError("invalid helper response")
                return response

            if getattr(sys, "frozen", False):
                nonce = secrets.token_hex(32)
                client.sendall(json.dumps({"action": "challenge", "nonce": nonce}).encode() + b"\n")
                try:
                    challenge = receive()
                except (ValueError, NetworkManagerError) as exc:
                    raise NetworkManagerError("helper authentication failed") from exc
                expected = hmac.new(self.token.encode(), b"northstar-helper-v1:" + nonce.encode("ascii"), hashlib.sha256).hexdigest()
                proof = challenge.get("proof")
                if challenge.get("ok") is not True or not isinstance(proof, str) or not hmac.compare_digest(proof.encode("utf-8"), expected.encode("ascii")):
                    raise NetworkManagerError("helper authentication failed")
            client.sendall(json.dumps({"token": self.token, "action": action, **values}).encode() + b"\n")
            response = receive()
            if not response.get("ok"):
                raise NetworkManagerError(response.get("error", "helper request failed"))
            return response

    def health(self):
        helper_available = False
        response = {}
        openvpn = OPENVPN_EXE.is_file()
        try:
            response = self._request("health")
            helper_available = bool(response.get("ok"))
            openvpn = bool(response.get("openvpn", openvpn))
        except (OSError, ValueError, NetworkManagerError):
            helper_available = False
        # Keep network_manager/openvpn_plugin for frontend compatibility.
        # network_manager is intentionally false because Windows does not use it.
        return {
            "platform": "windows",
            "vpn_backend": "openvpn-helper",
            "network_manager": False,
            "openvpn_plugin": openvpn,
            "reachable": helper_available,
            "helper": {"available": helper_available},
            "openvpn_exe": openvpn,
            "protection_available": False,
            "ipv6_blocked": response.get("ipv6_blocked") is True,
            "ipv6_guard_required": response.get("ipv6_guard_required") is True,
        }

    def _profile_path(self, profile) -> Path:
        path = profile.path if profile.path.is_absolute() else self.root / profile.path
        resolved = path.resolve(strict=True)
        resolved.relative_to(self.root.resolve(strict=True))
        if resolved.suffix.lower() != ".ovpn":
            raise NetworkManagerError("profile must have an .ovpn extension")
        return resolved

    def import_profile(self, profile, endpoint=None):
        if endpoint and endpoint not in {server.host for server in profile.servers}:
            raise NetworkManagerError("endpoint is not part of this profile")
        try:
            content = self._profile_path(profile).read_text(encoding="utf-8-sig")
        except (OSError, ValueError) as exc:
            raise NetworkManagerError(f"profile is not accessible: {exc}") from exc
        fingerprint = hashlib.sha256((content + (endpoint or "")).encode()).hexdigest()
        existing = self.imported.get(profile.id)
        if existing and self.fingerprints.get(profile.id) == fingerprint:
            self.connections[profile.id] = (profile, endpoint)
            return existing
        connection_id = profile.id
        self.imported[profile.id] = connection_id
        self.fingerprints[profile.id] = fingerprint
        self.endpoints[profile.id] = endpoint or ""
        self.connections[profile.id] = (profile, endpoint)
        return connection_id

    def connect(self, connection_id, credentials):
        profile, endpoint = self.connections[connection_id]
        profile_path = self._profile_path(profile)
        server = None
        if endpoint:
            server = next((item for item in profile.servers if item.host == endpoint), None)
        try:
            self._request(
                "connect",
                profile_id=profile.id,
                profile_path=str(profile_path),
                endpoint=endpoint,
                endpoint_port=server.port if server else None,
                username=credentials.username,
                password=credentials.password,
            )
        except (OSError, NetworkManagerError) as exc:
            raise NetworkManagerError(str(exc)) from exc

    def disconnect(self, connection_id):
        try:
            self._request("disconnect", connection_id=connection_id)
        except (OSError, NetworkManagerError) as exc:
            raise NetworkManagerError(str(exc)) from exc

    def active(self):
        try:
            response = self._request("status")
        except (OSError, ValueError, NetworkManagerError):
            return None
        if not response.get("connected"):
            return None
        connected_since = response.get("connected_since")
        try:
            started = float(connected_since) if connected_since is not None else None
        except (TypeError, ValueError):
            started = None
        try:
            bytes_in = int(response.get("bytes_in") or 0)
            bytes_out = int(response.get("bytes_out") or 0)
        except (TypeError, ValueError):
            bytes_in = bytes_out = 0
        return ActiveConnection(
            connection_id=response.get("connection_id") or "windows-openvpn",
            name="Northstar VPN / Windows",
            interface=response.get("interface"),
            vpn_ip=response.get("vpn_ip"),
            remote_endpoint=response.get("remote_endpoint"),
            transport=response.get("transport"),
            connected_since=started,
            bytes_in=bytes_in,
            bytes_out=bytes_out,
        )

    @property
    def endpoints(self):
        return self._endpoints

    @endpoints.setter
    def endpoints(self, value):
        self._endpoints = value
