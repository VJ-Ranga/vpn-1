import json
import socket
import time


class ProtectionClient:
    def __init__(self, settings, path="/run/northstar-vpn/control.sock"):
        self.settings, self.path = settings, path

    def request(self, action, **values):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(12)
                client.connect(self.path)
                client.sendall(json.dumps({"action": action, **values}).encode() + b"\n")
                data = bytearray()
                while b"\n" not in data:
                    chunk = client.recv(4096)
                    if not chunk or len(data) > 65536:
                        raise RuntimeError("Invalid protection response")
                    data.extend(chunk)
                response = json.loads(data.split(b"\n", 1)[0])
                if not response.get("ok"):
                    raise RuntimeError(response.get("error", "Protection update failed"))
                return response
        except OSError as exc:
            raise RuntimeError("Install the protection helper: run scripts/install-protection.sh with sudo.") from exc

    def status(self):
        try:
            return self.request("status")
        except (RuntimeError, ValueError) as exc:
            return {"available": False, "active": False, "error": str(exc)}

    def configure(self, values):
        policy = {key: values[key] for key in ("ipv6_protection", "dns_protection", "kill_switch", "allow_lan")}
        if any(policy[key] for key in ("ipv6_protection", "dns_protection", "kill_switch")) or self.status()["available"]:
            return self.request("configure", policy=policy)

    def prepare(self, profile):
        values = self.settings.get()
        if not any(values[key] for key in ("ipv6_protection", "dns_protection", "kill_switch")):
            return
        self.configure(values)
        self.request("prepare", endpoints=[])
        endpoints = []
        for server in profile.servers:
            try:
                for item in socket.getaddrinfo(server.host, server.port, socket.AF_INET, socket.SOCK_STREAM):
                    endpoint = {"ip": item[4][0], "port": server.port}
                    if endpoint not in endpoints:
                        endpoints.append(endpoint)
            except OSError:
                continue
        if not endpoints:
            raise RuntimeError("No VPN endpoints resolved. Check your internet connection.")
        self.request("prepare", endpoints=endpoints)

    def confirm(self):
        if not any(self.settings.get()[key] for key in ("ipv6_protection", "dns_protection", "kill_switch")):
            return {"required": False, "available": False, "active": False}
        for attempt in range(10):
            try:
                return self.request("commit")
            except RuntimeError as exc:
                if "tunnel" not in str(exc) or attempt == 9:
                    raise
                time.sleep(0.3)

    def release(self):
        if self.status()["available"]:
            self.request("release")
