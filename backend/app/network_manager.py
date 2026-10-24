from dataclasses import dataclass
from pathlib import Path
import os
import re
import subprocess
import hashlib
import json
import tempfile
import ipaddress

from .secrets import Credentials


class NetworkManagerError(RuntimeError):
    pass


class NmcliRunner:
    def run(self, args: list[str], timeout: float = 90, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            input=input_text,
            timeout=timeout,
            env={**os.environ, "LC_ALL": "C"},
        )


@dataclass
class ActiveConnection:
    connection_id: str
    name: str
    interface: str | None = None
    vpn_ip: str | None = None
    remote_endpoint: str | None = None
    transport: str | None = None
    connected_since: float | None = None
    bytes_in: int = 0
    bytes_out: int = 0


class NetworkManagerAdapter:
    def __init__(self, runner=None, plugin_paths=None):
        self.runner = runner or NmcliRunner()
        self.imported: dict[str, str] = {}
        self.fingerprints: dict[str, str] = {}
        self.endpoints: dict[str, str] = {}
        self.plugin_paths = plugin_paths or [
            Path("/usr/lib/NetworkManager/VPN/nm-openvpn-service.name"),
            Path("/usr/lib/NetworkManager/VPN/nm-openvpn-service"),
            Path("/usr/libexec/nm-openvpn-service"),
            Path("/usr/libexec/NetworkManager/VPN/nm-openvpn-service"),
            Path("/lib/NetworkManager/VPN/nm-openvpn-service.name"),
            Path("/lib/NetworkManager/VPN/nm-openvpn-service"),
        ]

    def health(self):
        try:
            nm = self.runner.run(["nmcli", "-t", "-f", "RUNNING", "general"], 5).returncode == 0
            plugin = any(self._valid_plugin_path(path) for path in self.plugin_paths)
            return {"network_manager": nm, "openvpn_plugin": plugin}
        except (OSError, subprocess.TimeoutExpired):
            return {"network_manager": False, "openvpn_plugin": False}

    @staticmethod
    def _valid_plugin_path(path: Path) -> bool:
        if not path.is_file():
            return False
        if path.name.endswith(".name"):
            return True
        return bool(path.stat().st_mode & 0o111)

    def import_profile(self, profile, endpoint: str | None = None) -> str:
        if endpoint and endpoint not in {server.host for server in profile.servers}:
            raise NetworkManagerError("endpoint is not part of this profile")
        content = profile.path.read_text()
        fingerprint = hashlib.sha256((content + (endpoint or "")).encode()).hexdigest()
        existing = self.imported.get(profile.id)
        if existing and self.fingerprints.get(profile.id) == fingerprint:
            return existing
        try:
            if endpoint:
                lines = [line for line in content.splitlines() if not line.strip().startswith("remote ")]
                server = next(server for server in profile.servers if server.host == endpoint)
                lines.insert(0, f"remote {server.host} {server.port}")
                with tempfile.TemporaryDirectory(prefix="northstar-profile-") as directory:
                    path = Path(directory) / profile.path.name
                    path.write_text("\n".join(lines) + "\n")
                    result = self.runner.run(["nmcli", "connection", "import", "type", "openvpn", "file", str(path)])
            else:
                result = self.runner.run(["nmcli", "connection", "import", "type", "openvpn", "file", str(profile.path)])
        except (OSError, subprocess.TimeoutExpired):
            raise NetworkManagerError("profile import unavailable")
        if result.returncode:
            raise NetworkManagerError("profile import failed")
        match = re.search(r"\b([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\b", result.stdout)
        if not match:
            raise NetworkManagerError("profile import returned no connection id")
        connection_id = match.group(1)
        name = f"Namecheap VPN / {profile.country_code} {profile.city} / {profile.transport.upper()}"
        try:
            renamed = self.runner.run(["nmcli", "connection", "modify", "uuid", connection_id, "connection.id", name])
        except (OSError, subprocess.TimeoutExpired):
            raise NetworkManagerError("profile rename unavailable")
        if renamed.returncode:
            raise NetworkManagerError("profile rename failed")
        self.imported[profile.id] = connection_id
        self.fingerprints[profile.id] = fingerprint
        self.endpoints[profile.id] = endpoint or ""
        return connection_id

    def connect(self, connection_id: str, credentials: Credentials) -> None:
        try:
            configured = self.runner.run(["nmcli", "connection", "modify", "uuid", connection_id, "vpn.user-name", credentials.username])
        except (OSError, subprocess.TimeoutExpired):
            raise NetworkManagerError("credential configuration unavailable")
        if configured.returncode:
            raise NetworkManagerError("credential configuration failed")
        try:
            result = self.runner.run(["nmcli", "--ask", "connection", "up", "uuid", connection_id], input_text=f"{credentials.password}\n")
        except (OSError, subprocess.TimeoutExpired):
            raise NetworkManagerError("connection unavailable")
        if result.returncode:
            raise NetworkManagerError("connection failed")

    def disconnect(self, connection_id: str) -> None:
        try:
            result = self.runner.run(["nmcli", "connection", "down", "uuid", connection_id])
        except (OSError, subprocess.TimeoutExpired):
            raise NetworkManagerError("disconnect unavailable")
        if result.returncode:
            raise NetworkManagerError("disconnect failed")

    def active(self):
        try:
            result = self.runner.run(["nmcli", "-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show", "--active"], 5)
            if result.returncode:
                return None
            for line in result.stdout.splitlines():
                fields = line.split(":")
                if len(fields) < 4:
                    continue
                name, connection_id, kind, device = fields[:4]
                if kind != "vpn":
                    continue
                if not name.startswith(("Namecheap VPN / ", "NCVPN-")):
                    continue
                details = self.runner.run(["nmcli", "-t", "-f", "connection.timestamp,vpn.data", "connection", "show", "uuid", connection_id], 5)
                values = {
                    key: value
                    for key, value in (item.split(":", 1) for item in details.stdout.splitlines() if ":" in item)
                }
                vpn_data = values.get("vpn.data", "")
                remote = re.search(r"(?:^|, )remote = ([^,\\]+)", vpn_data)
                transport = "tcp" if "proto-tcp = yes" in vpn_data else "udp"
                if device.startswith(("tun", "tap")):
                    interface = device
                    vpn_ip = self._vpn_ip(interface)
                    endpoint = self._active_endpoint(interface)
                else:
                    runtime = self.runner.run(["nmcli", "-t", "-f", "IP4,VPN", "connection", "show", "uuid", connection_id], 5)
                    addresses = re.findall(r"IP4\.ADDRESS\[\d+\]:([^/\n]+)/", runtime.stdout)
                    gateway = re.search(r"VPN\.GATEWAY:([^\n]+)", runtime.stdout)
                    endpoint = gateway.group(1) if gateway else None
                    interfaces = self.runner.run(["ip", "-j", "-4", "address", "show"], 5)
                    interface = vpn_ip = None
                    for link in json.loads(interfaces.stdout or "[]"):
                        if link.get("ifname") == device:
                            continue
                        for address in link.get("addr_info", []):
                            if address.get("local") in addresses:
                                interface, vpn_ip = link["ifname"], address["local"]
                                break
                if not endpoint and interface:
                    endpoint = self._routed_endpoint(interface)
                endpoint = endpoint or (remote.group(1) if remote else None)
                rx, tx = self._interface_counters(interface)
                return ActiveConnection(
                    connection_id,
                    name,
                    interface,
                    vpn_ip,
                    endpoint,
                    transport,
                    float(values.get("connection.timestamp", "0") or 0) or None,
                    rx,
                    tx,
                )
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        return None

    @staticmethod
    def _interface_counters(interface: str | None) -> tuple[int, int]:
        if not interface:
            return 0, 0
        try:
            rx = int(Path(f"/sys/class/net/{interface}/statistics/rx_bytes").read_text())
            tx = int(Path(f"/sys/class/net/{interface}/statistics/tx_bytes").read_text())
            return rx, tx
        except (OSError, ValueError):
            return 0, 0

    def _routed_endpoint(self, interface):
        result = self.runner.run(["ip", "-j", "-4", "route", "show", "table", "main"], 5)
        routes = json.loads(result.stdout or "[]")
        metrics = {route.get("metric") for route in routes if route.get("dev") == interface and route.get("dst") == "default"}
        candidates = []
        for route in routes:
            try:
                address = ipaddress.IPv4Address(route.get("dst", ""))
            except ValueError:
                continue
            if address.is_global and route.get("dev") != interface and route.get("protocol") == "static" and route.get("metric") in metrics:
                candidates.append(str(address))
        return candidates[0] if len(candidates) == 1 else None

    def _vpn_ip(self, interface: str | None) -> str | None:
        if not interface:
            return None
        try:
            result = self.runner.run(["nmcli", "-t", "-f", "IP4.ADDRESS", "device", "show", interface], 5)
            for line in result.stdout.splitlines():
                if ":" in line:
                    address = line.split(":", 1)[1].split("/", 1)[0]
                    if address:
                        return address
        except (OSError, subprocess.TimeoutExpired):
            pass
        return None

    def _active_endpoint(self, interface: str | None) -> str | None:
        if not interface:
            return None
        try:
            result = self.runner.run(["nmcli", "-t", "-f", "VPN.GATEWAY", "device", "show", interface], 5)
            for line in result.stdout.splitlines():
                if ":" in line:
                    endpoint = line.split(":", 1)[1]
                    if endpoint:
                        return endpoint
        except (OSError, subprocess.TimeoutExpired):
            pass
        return None
