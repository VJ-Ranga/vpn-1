#!/usr/bin/env python3
"""Root-owned, UID-authenticated firewall service. Uses only the standard library."""
import argparse
import ipaddress
import itertools
import json
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import time

DEFAULT_POLICY = {"ipv6_protection": True, "dns_protection": True, "kill_switch": False, "allow_lan": False}
TABLE = "northstar_vpn"


def validate_policy(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT_POLICY) or any(type(v) is not bool for v in value.values()):
        raise ValueError("Invalid protection policy")
    return dict(value)


def validate_endpoints(values):
    if not isinstance(values, list) or len(values) > 512:
        raise ValueError("Invalid endpoint list")
    result = []
    for value in values:
        address = ipaddress.ip_address(value["ip"])
        port = value["port"]
        if address.version != 4 or type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("Invalid VPN endpoint")
        result.append({"ip": str(address), "port": port})
    return result


def render_rules(policy, interface, endpoints, preparing=False):
    policy = validate_policy(policy)
    endpoints = validate_endpoints(endpoints)
    if interface is not None and not re.fullmatch(r"(?:tun|tap)[a-zA-Z0-9_-]{0,11}", interface):
        raise ValueError("Invalid tunnel interface")
    if not (interface or preparing or policy["kill_switch"]):
        return f"destroy table inet {TABLE}\n"
    rules = ['oifname "lo" accept', "udp sport 68 udp dport 67 accept", "udp sport 546 udp dport 547 accept", "icmpv6 type { nd-router-solicit, nd-router-advert, nd-neighbor-solicit, nd-neighbor-advert } accept"]
    if interface:
        rules.append(f'oifname "{interface}" accept')
    for endpoint in endpoints:
        rules.append(f'ip daddr {endpoint["ip"]} meta l4proto {{ tcp, udp }} th dport {endpoint["port"]} accept')
    if preparing and not interface:
        rules.extend(["meta nfproto ipv4 udp dport 53 accept", "meta nfproto ipv4 tcp dport 53 accept"])
    elif policy["dns_protection"]:
        rules.extend(["udp dport 53 reject", "tcp dport 53 reject"])
    if policy["allow_lan"]:
        rules.extend(["ip daddr 10.0.0.0/8 accept", "ip daddr 172.16.0.0/12 accept", "ip daddr 192.168.0.0/16 accept", "ip6 daddr { fc00::/7, fe80::/10 } accept"])
    if policy["ipv6_protection"]:
        rules.append("meta nfproto ipv6 reject")
    if policy["kill_switch"]:
        rules.append("reject with icmpx type admin-prohibited")
    body = "\n".join(f"    {rule}" for rule in rules)
    return f"destroy table inet {TABLE}\ntable inet {TABLE} {{\n  chain output {{\n    type filter hook output priority -10; policy accept;\n{body}\n  }}\n}}\n"


def command(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=8, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"})
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed: {result.stderr.strip()[:160]}")
    return result.stdout


def discover_tunnel():
    """Independently verify a managed active VPN's IP against a TUN adapter."""
    active = command(["nmcli", "-t", "--escape", "no", "-f", "NAME,UUID,TYPE", "connection", "show", "--active"])
    links = json.loads(command(["ip", "-j", "-4", "address", "show"]))
    routes = json.loads(command(["ip", "-j", "-4", "route", "show", "table", "main"]))
    for line in active.splitlines():
        fields = line.rsplit(":", 2)
        if len(fields) != 3 or fields[2] != "vpn" or not fields[0].startswith("Namecheap VPN / "):
            continue
        runtime = command(["nmcli", "-t", "-f", "IP4,VPN", "connection", "show", "uuid", fields[1]])
        ips = set(re.findall(r"IP4\.ADDRESS\[\d+\]:([^/\n]+)/", runtime))
        gateway = re.search(r"VPN\.GATEWAY:([^\n]+)", runtime)
        for link in links:
            name = link.get("ifname", "")
            if re.fullmatch(r"(?:tun|tap)[a-zA-Z0-9_-]{0,11}", name) and Path(f"/sys/class/net/{name}/tun_flags").exists():
                if any(item.get("local") in ips for item in link.get("addr_info", [])):
                    metrics = {route.get("metric") for route in routes if route.get("dev") == name and route.get("dst") == "default"}
                    if not metrics:
                        continue
                    endpoints = []
                    if gateway:
                        try:
                            address = ipaddress.IPv4Address(gateway.group(1).strip())
                            endpoints = [{"ip": str(address), "port": port} for port in (443, 1194)]
                        except ValueError:
                            pass
                    for route in routes:
                        try:
                            address = ipaddress.IPv4Address(route.get("dst", ""))
                        except ValueError:
                            continue
                        if address.is_global and route.get("dev") != name and route.get("protocol") == "static" and route.get("metric") in metrics:
                            endpoints.extend({"ip": str(address), "port": port} for port in (443, 1194))
                    return {"interface": name, "endpoints": endpoints}
    return None


def apply_rules(text):
    result = subprocess.run(["/usr/sbin/nft", "-f", "-"], input=text, text=True, capture_output=True, timeout=8)
    if result.returncode:
        raise RuntimeError("Firewall update failed: " + result.stderr.strip()[:240])


def authorize_peer(uid, allowed_uid):
    if uid != allowed_uid:
        raise PermissionError("Unauthorized desktop user")


class ProtectionController:
    def __init__(self, state_path, apply=apply_rules, discover=discover_tunnel, clock=time.monotonic):
        self.state_path = Path(state_path)
        self.apply, self.discover, self.clock = apply, discover, clock
        self.policy = dict(DEFAULT_POLICY)
        self.endpoints = []
        self.deadline = 0
        self.interface = None
        self.error = None
        self.last_rules = None
        if self.state_path.exists():
            saved = json.loads(self.state_path.read_text())
            self.policy = validate_policy(saved["policy"])
            self.endpoints = validate_endpoints(saved.get("endpoints", []))

    def save(self):
        self.state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"policy": self.policy, "endpoints": self.endpoints}))
        temporary.chmod(0o600)
        temporary.replace(self.state_path)

    def reconcile(self):
        self.bootstrap()
        discovered = self.discover()
        self.interface = discovered.get("interface") if isinstance(discovered, dict) else discovered
        endpoints = list(self.endpoints)
        if isinstance(discovered, dict):
            endpoints.extend(validate_endpoints(discovered.get("endpoints", [])))
        rules = render_rules(self.policy, self.interface, endpoints, self.deadline > self.clock())
        if rules != self.last_rules:
            self.apply(rules)
            self.last_rules = rules
        self.error = None
        return self.status()

    def bootstrap(self):
        if self.last_rules is None and self.policy["kill_switch"]:
            rules = render_rules(self.policy, None, self.endpoints)
            self.apply(rules)
            self.last_rules = rules

    def status(self):
        enabled = any(self.policy[key] for key in ("ipv6_protection", "dns_protection", "kill_switch"))
        return {"available": True, "policy": self.policy, "interface": self.interface, "active": enabled and bool(self.interface or self.deadline > self.clock() or self.policy["kill_switch"]), "error": self.error}

    def handle(self, request):
        action = request.get("action")
        if action == "configure":
            previous = self.policy
            self.policy = validate_policy(request.get("policy"))
            try:
                self.reconcile()
            except Exception:
                self.policy = previous
                raise
            self.save()
        elif action == "prepare":
            incoming = validate_endpoints(request.get("endpoints", []))
            if incoming:
                self.endpoints = incoming
            self.deadline = self.clock() + 120
            self.reconcile()
            self.save()
        elif action == "release":
            self.deadline = 0
            self.reconcile()
        elif action == "commit":
            self.reconcile()
            if not self.interface:
                raise RuntimeError("VPN tunnel could not be verified")
            self.deadline = 0
            self.reconcile()
        elif action == "status":
            self.reconcile()
        else:
            raise ValueError("Unknown protection operation")
        return self.status()


def secure_socket(path, allowed_uid):
    path.chmod(0o600)
    os.chown(path, allowed_uid, -1)


def notify_ready():
    address = os.environ.get("NOTIFY_SOCKET")
    if address:
        if address.startswith("@"):
            address = "\0" + address[1:]
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notifier:
            notifier.sendto(b"READY=1", address)


def serve(allowed_uid):
    path = Path("/run/northstar-vpn/control.sock")
    path.parent.mkdir(mode=0o755, exist_ok=True)
    path.unlink(missing_ok=True)
    controller = ProtectionController("/var/lib/northstar-vpn/protection.json")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(path))
        secure_socket(path, allowed_uid)
        server.listen(8)
        server.settimeout(1)
        controller.bootstrap()
        notify_ready()
        while True:
            try:
                controller.reconcile()
            except Exception as exc:
                controller.error = str(exc)[:240]
            try:
                client, _ = server.accept()
            except socket.timeout:
                continue
            with client:
                client.settimeout(3)
                try:
                    _, uid, _ = struct.unpack("3i", client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                    authorize_peer(uid, allowed_uid)
                    data = bytearray()
                    while b"\n" not in data:
                        chunk = client.recv(4096)
                        if not chunk:
                            raise ValueError("Incomplete request")
                        data.extend(chunk)
                        if len(data) > 65536:
                            raise ValueError("Request too large")
                    value = controller.handle(json.loads(data.split(b"\n", 1)[0]))
                    reply = {"ok": True, **value}
                except Exception as exc:
                    reply = {"ok": False, "error": str(exc)[:240]}
                try:
                    client.sendall(json.dumps(reply).encode() + b"\n")
                except OSError:
                    pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--uid", type=int, required=True)
    parser.add_argument("--check", action="store_true", help="Validate every firewall policy without applying it")
    options = parser.parse_args()
    if os.geteuid() != 0 or options.uid <= 0:
        raise SystemExit("Run as root with a non-root desktop UID")
    if options.check:
        for flags in itertools.product((False, True), repeat=4):
            policy = dict(zip(DEFAULT_POLICY, flags))
            for interface, preparing in ((None, False), (None, True), ("tun0", False)):
                rules = render_rules(policy, interface, [{"ip": "203.0.113.5", "port": 443}], preparing)
                result = subprocess.run(["/usr/sbin/nft", "--check", "-f", "-"], input=rules, text=True, capture_output=True, timeout=8)
                if result.returncode:
                    raise SystemExit(result.stderr)
        print("Validated 48 firewall policy combinations without applying changes.")
    else:
        serve(options.uid)
