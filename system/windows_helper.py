#!/usr/bin/env python3
"""Privileged Windows helper for Northstar VPN.

The helper runs elevated, owns the OpenVPN process, and exposes a narrow
authenticated JSON protocol on loopback. Profiles are parsed and rebuilt from a
strict allowlist before OpenVPN sees them; the original file is never passed to
OpenVPN.

This is a Stage 1 development helper. It still runs from a user-controlled
checkout, so the same interactive user can influence the helper process. Move it
to an admin-owned Program Files location and a Windows service before treating
it as a security boundary.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

DEFAULT_PORT = int(os.getenv("VPN_WINDOWS_HELPER_PORT", "8799"))
OPENVPN = (r"C:\Program Files\OpenVPN\bin\openvpn.exe" if getattr(sys, "frozen", False)
           else os.getenv("VPN_OPENVPN_EXE", r"C:\Program Files\OpenVPN\bin\openvpn.exe"))
TOKEN_MIN = 32
MAX_PROFILE_BYTES = 1024 * 1024
MAX_INLINE_BYTES = 64 * 1024
MAX_REQUEST_BYTES = 64 * 1024
CONNECT_TIMEOUT = 40
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
ALLOW_PRIVATE_ENDPOINTS = os.getenv("VPN_ALLOW_PRIVATE_ENDPOINTS", "0") == "1"

# Directives that can execute code, load code, read/write arbitrary files, or
# take over the privileged process. They are rejected explicitly for a clearer
# error message; the allowlist below still rejects everything else.
DENY = {
    "plugin",
    "script-security",
    "up",
    "down",
    "dns-updown",
    "route-up",
    "route-pre-down",
    "ipchange",
    "tls-verify",
    "auth-user-pass-verify",
    "client-connect",
    "client-disconnect",
    "learn-address",
    "client-crresponse",
    "setenv",
    "setenv-safe",
    "ignore-unknown-option",
    "compat-mode",
    "config",
    "cd",
    "tmp-dir",
    "chroot",
    "user",
    "group",
    "iproute",
    "setcon",
    "daemon",
    "service",
    "inetd",
    "engine",
    "providers",
    "provider",
    "pkcs11-providers",
    "pkcs11-id",
    "cryptoapicert",
    "win-sys",
    "allow-nonadmin",
    "management",
    "management-client",
    "management-query-passwords",
    "management-query-proxy",
    "management-query-remote",
    "management-hold",
    "management-signal",
    "management-log-cache",
    "management-external-key",
    "management-external-cert",
    "management-client-auth",
    "management-client-user",
    "management-client-group",
    "management-forget-disconnect",
    "management-up-down",
    "askpass",
    "pkcs12",
    "ca",
    "cert",
    "key",
    "tls-auth",
    "tls-crypt",
    "tls-crypt-v2",
    "secret",
    "crl-verify",
    "capath",
    "dh",
    "extra-certs",
    "http-proxy-user-pass",
    "replay-persist",
    "tls-export-cert",
    "client-config-dir",
    "ifconfig-pool-persist",
    "log",
    "log-append",
    "status",
    "status-version",
    "writepid",
    "mode",
    "server",
    "server-bridge",
    "server-ipv6",
    "tls-server",
    "push",
    "push-reset",
    "push-remove",
    "client-to-client",
    "duplicate-cn",
    "ifconfig-pool",
    "port-share",
    "float",
    "remote-random-hostname",
    "local",
    "lport",
    "rport",
    "port",
    "bind",
    "http-proxy",
    "socks-proxy",
    "http-proxy-option",
    "route-nopull",
    "allow-pull-fqdn",
    "pull-filter",
    "compress",
    "comp-lzo",
    "allow-compression",
    "auth-token",
    "auth-token-user",
    "register-dns",
    "show-adapters",
    "show-net",
    "show-net-up",
    "show-valid-subnets",
    "tap-sleep",
    "pause-exit",
    "dhcp-renew",
    "dhcp-release",
}

FLAGS = {
    "client",
    "remote-random",
    "nobind",
    "persist-key",
    "persist-tun",
    "persist-remote-ip",
    "auth-nocache",
}
SINGLE = {
    "dev",
    "proto",
    "resolv-retry",
    "remote-cert-tls",
    "verb",
    "auth",
    "cipher",
    "data-ciphers",
    "data-ciphers-fallback",
    "tls-cipher",
    "tls-version-min",
    "reneg-sec",
    "connect-timeout",
    "connect-retry-max",
    "tun-mtu",
    "fragment",
    "mssfix",
}
PAIRS = {"keepalive", "connect-retry", "ping", "ping-restart"}
INLINE_TAGS = {"ca", "cert", "key", "tls-auth", "tls-crypt", "tls-crypt-v2"}
PROTOCOLS = {
    "udp": "udp",
    "udp4": "udp4",
    "udp6": "udp6",
    "tcp": "tcp-client",
    "tcp4": "tcp4-client",
    "tcp6": "tcp6-client",
    "tcp-client": "tcp-client",
    "tcp4-client": "tcp4-client",
    "tcp6-client": "tcp6-client",
}


def token_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "NorthstarVPN" / "helper.token"
    base = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "northstar-vpn" / "helper.token"


def is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in {"localhost"}


def validate_endpoint(host: str) -> str:
    if not isinstance(host, str) or not host or len(host) > 253:
        raise ValueError("invalid remote host")
    if any(char in host for char in "\r\n\t \"'\\#;"):
        raise ValueError("invalid remote host")
    if host.startswith("-") or ".." in host:
        raise ValueError("invalid remote host")
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host):
        raise ValueError("invalid remote host")
    return host


def validate_port(value) -> int:
    if isinstance(value, bool):
        raise ValueError("invalid remote port")
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid remote port") from exc
    if not 1 <= port <= 65535:
        raise ValueError("invalid remote port")
    return port


def ensure_public_endpoint(host: str, port: int) -> None:
    if ALLOW_PRIVATE_ENDPOINTS:
        return
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise ValueError(f"could not resolve remote host {host}") from exc
    if not addresses:
        raise ValueError(f"could not resolve remote host {host}")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError(f"remote host {host} resolves to a non-public address")
        if ip.version == 6 and ip.ipv4_mapped and not ip.ipv4_mapped.is_global:
            raise ValueError(f"remote host {host} resolves to a non-public address")


def read_profile(path: Path, root: Path) -> str:
    resolved = Path(path).resolve(strict=True)
    root_resolved = Path(root).resolve(strict=True)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("profile path is not allowed") from exc
    if resolved.suffix.lower() != ".ovpn":
        raise ValueError("profile must have an .ovpn extension")
    info = resolved.stat()
    if info.st_size > MAX_PROFILE_BYTES:
        raise ValueError("profile is too large")
    if getattr(info, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError("profile must not be a reparse point")
    if getattr(info, "st_nlink", 1) > 1:
        raise ValueError("profile must not be a hardlink")
    with open(resolved, "rb") as handle:
        data = handle.read(MAX_PROFILE_BYTES + 1)
    if len(data) > MAX_PROFILE_BYTES:
        raise ValueError("profile is too large")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("profile must be UTF-8 text") from exc


def _flag(option: str, args: list[str], flags: set[str]) -> None:
    if args:
        raise ValueError(f"directive '{option}' does not take a value")
    if option in flags:
        raise ValueError(f"duplicate directive '{option}'")
    flags.add(option)


def _single(values: dict, option: str, args: list[str]) -> None:
    if option in values:
        raise ValueError(f"duplicate directive '{option}'")
    values[option] = args


def sanitize_profile(text: str, endpoint: str | None = None, endpoint_port=None):
    """Return (safe_config_text, selected_remotes, transport).

    Only known-safe directives are re-emitted. All remote and inline blocks are
    generated by this function, never copied from the profile.
    """
    if len(text.encode("utf-8", "replace")) > MAX_PROFILE_BYTES:
        raise ValueError("profile is too large")
    if "\x00" in text:
        raise ValueError("profile contains invalid bytes")
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    remotes: list[tuple[str, int]] = []
    flags: set[str] = set()
    values: dict[str, list[str]] = {}
    inline: dict[str, str] = {}
    lines = text.split("\n")
    index = 0
    while index < len(lines):
        raw = lines[index]
        index += 1
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        if stripped.startswith("<"):
            if not stripped.endswith(">"):
                raise ValueError("malformed inline block")
            tag = stripped[1:-1].strip().lower()
            if not tag or tag.startswith("/"):
                raise ValueError("unexpected inline block")
            if tag not in INLINE_TAGS:
                raise ValueError(f"inline block <{tag}> is not allowed")
            if tag in inline:
                raise ValueError(f"duplicate inline block <{tag}>")
            body: list[str] = []
            closed = False
            while index < len(lines):
                candidate = lines[index]
                index += 1
                if candidate.strip().lower() == f"</{tag}>":
                    closed = True
                    break
                if candidate.strip().startswith("<") and candidate.strip().endswith(">"):
                    raise ValueError("nested inline block")
                body.append(candidate)
            if not closed:
                raise ValueError(f"unterminated inline block <{tag}>")
            content = "\n".join(body).strip("\n")
            if not content or len(content.encode("utf-8")) > MAX_INLINE_BYTES:
                raise ValueError(f"invalid inline block <{tag}>")
            inline[tag] = content
            continue
        if stripped.endswith("\\"):
            raise ValueError("line continuation is not allowed")
        try:
            parts = shlex.split(stripped, comments=False, posix=True)
        except ValueError as exc:
            raise ValueError("invalid profile syntax") from exc
        if not parts:
            continue
        option = parts[0].lower().lstrip("-")
        args = parts[1:]
        if option in DENY:
            raise ValueError(f"directive '{option}' is not allowed")
        if option in FLAGS:
            _flag(option, args, flags)
            continue
        if option == "remote":
            if not 1 <= len(args) <= 3:
                raise ValueError("invalid remote directive")
            host = validate_endpoint(args[0])
            port = validate_port(args[1]) if len(args) >= 2 else 1194
            if len(args) == 3 and args[2].lower() not in PROTOCOLS:
                raise ValueError("invalid remote protocol")
            if len(remotes) >= 64:
                raise ValueError("too many remote directives")
            remotes.append((host, port))
            continue
        if option == "auth-user-pass":
            if args:
                raise ValueError("external auth-user-pass files are not allowed")
            continue
        if option == "verify-x509-name":
            if not 1 <= len(args) <= 2:
                raise ValueError("invalid verify-x509-name directive")
            if not re.fullmatch(r"[A-Za-z0-9._:-]{1,255}", args[0]):
                raise ValueError("invalid verify-x509-name value")
            if len(args) == 2 and args[1].lower() not in {"name", "name-prefix", "subject"}:
                raise ValueError("invalid verify-x509-name mode")
            if "verify-x509-name" in values:
                raise ValueError("duplicate verify-x509-name directive")
            values["verify-x509-name"] = args
            continue
        if option in SINGLE:
            if len(args) != 1:
                raise ValueError(f"invalid directive '{option}'")
            _single(values, option, args)
            continue
        if option in PAIRS:
            if not 1 <= len(args) <= 2:
                raise ValueError(f"invalid directive '{option}'")
            _single(values, option, args)
            continue
        raise ValueError(f"unsupported directive '{option}'")

    if "client" not in flags:
        raise ValueError("profile is not a client profile")
    if "ca" not in inline:
        raise ValueError("profile must contain an inline <ca> certificate")
    if not remotes:
        raise ValueError("profile has no remote server")

    dev = values.get("dev", ["tun"])[0]
    if dev != "tun":
        raise ValueError("only 'dev tun' is supported")
    proto = PROTOCOLS.get(values.get("proto", ["udp"])[0].lower())
    if proto is None:
        raise ValueError("unsupported protocol")

    auth = values.get("auth", ["SHA256"])[0].upper()
    if auth not in {"SHA256", "SHA512"}:
        raise ValueError("unsupported auth digest")
    ciphers = values.get("data-ciphers", ["AES-256-GCM:AES-128-GCM:CHACHA20-POLY1305"])[0]
    if not re.fullmatch(r"[A-Za-z0-9:?_!+-]{1,512}", ciphers) or "?" in ciphers:
        raise ValueError("invalid data-ciphers")
    fallback = values.get("data-ciphers-fallback", [None])[0]
    if fallback is not None and not re.fullmatch(r"[A-Za-z0-9-]{1,64}", fallback):
        raise ValueError("invalid data-ciphers-fallback")
    tls_cipher = values.get("tls-cipher", [None])[0]
    if tls_cipher is not None and not re.fullmatch(r"[A-Za-z0-9:_.@=+-]{1,1024}", tls_cipher):
        raise ValueError("invalid tls-cipher")
    cipher = values.get("cipher", [None])[0]
    if cipher is not None and not re.fullmatch(r"[A-Za-z0-9-]{1,64}", cipher):
        raise ValueError("invalid cipher")
    tls_min = values.get("tls-version-min", ["1.2"])[0]
    if tls_min not in {"1.2", "1.3"}:
        raise ValueError("tls-version-min must be 1.2 or 1.3")
    verb = values.get("verb", ["3"])[0]
    if not re.fullmatch(r"[0-3]", verb):
        raise ValueError("verb must be between 0 and 3")
    resolv_retry = values.get("resolv-retry", ["infinite"])[0]
    if resolv_retry != "infinite" and not re.fullmatch(r"[0-9]{1,4}", resolv_retry):
        raise ValueError("invalid resolv-retry")
    remote_cert = values.get("remote-cert-tls", ["server"])[0].lower()
    if remote_cert != "server":
        raise ValueError("remote-cert-tls must be 'server'")

    for option in ("reneg-sec", "connect-timeout", "connect-retry-max", "tun-mtu", "fragment", "mssfix"):
        if option in values and not re.fullmatch(r"[0-9]{1,6}", values[option][0]):
            raise ValueError(f"invalid {option}")
    if "tun-mtu" in values and not 576 <= int(values["tun-mtu"][0]) <= 9000:
        raise ValueError("invalid tun-mtu")
    if "fragment" in values and not 0 <= int(values["fragment"][0]) <= 1500:
        raise ValueError("invalid fragment")
    if "mssfix" in values and not 0 <= int(values["mssfix"][0]) <= 1500:
        raise ValueError("invalid mssfix")
    if "reneg-sec" in values and not 60 <= int(values["reneg-sec"][0]) <= 86400:
        raise ValueError("invalid reneg-sec")
    for option in ("keepalive", "connect-retry", "ping", "ping-restart"):
        if option in values and not all(re.fullmatch(r"[0-9]{1,6}", item) for item in values[option]):
            raise ValueError(f"invalid {option}")

    if endpoint is not None:
        target = validate_endpoint(endpoint)
        matches = [item for item in remotes if item[0].lower() == target.lower()]
        if not matches:
            raise ValueError("endpoint is not part of this profile")
        host, port = matches[0]
        if endpoint_port is not None:
            port = validate_port(endpoint_port)
            if port != matches[0][1]:
                raise ValueError("endpoint port does not match the profile")
        selected = [(host, port)]
    else:
        selected = remotes[:32]

    output = ["client", "dev tun", f"proto {proto}"]
    output.extend(f"remote {host} {port}" for host, port in selected)
    if "remote-random" in flags and len(selected) > 1:
        output.append("remote-random")
    output.extend(
        [
            f"resolv-retry {resolv_retry}",
            "nobind",
            "persist-key",
            "persist-tun",
            "persist-remote-ip",
            "remote-cert-tls server",
        ]
    )
    if "verify-x509-name" in values:
        output.append("verify-x509-name " + " ".join(values["verify-x509-name"]))
    output.append(f"auth {auth}")
    output.append(f"data-ciphers {ciphers}")
    if fallback:
        output.append(f"data-ciphers-fallback {fallback}")
    if cipher:
        output.append(f"cipher {cipher}")
    if tls_cipher:
        output.append(f"tls-cipher {tls_cipher}")
    output.append(f"tls-version-min {tls_min}")
    output.extend(["auth-nocache", f"verb {verb}"])
    for option in ("reneg-sec", "connect-timeout", "connect-retry-max", "tun-mtu", "fragment", "mssfix", "keepalive", "connect-retry", "ping", "ping-restart"):
        if option in values:
            output.append(option + " " + " ".join(values[option]))
    for tag in ("ca", "cert", "key", "tls-auth", "tls-crypt", "tls-crypt-v2"):
        if tag in inline:
            output.append(f"<{tag}>")
            output.append(inline[tag])
            output.append(f"</{tag}>")
    transport = "tcp" if proto.startswith("tcp") else "udp"
    return "\n".join(output) + "\n", selected, transport


def validate_username(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.@+-]{1,128}", value):
        raise ValueError("invalid username")
    return value


def validate_password(value) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 1024:
        raise ValueError("invalid password")
    if not all(char.isprintable() for char in value):
        raise ValueError("invalid password")
    return value


def _icacls() -> str:
    return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "icacls.exe")


def harden_acl(path: Path, directory: bool = False) -> None:
    if os.name != "nt":
        return
    permission = "(OI)(CI)F" if directory else "F"
    try:
        result = subprocess.run(
            [_icacls(), str(path), "/inheritance:r", "/grant:r", f"*S-1-5-18:{permission}", f"*S-1-5-32-544:{permission}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise HelperError("Could not restrict privileged VPN artifact permissions.")
    except OSError as exc:
        raise HelperError("Could not set privileged VPN artifact permissions.") from exc


def secure_run_dir() -> Path:
    if os.name == "nt":
        base = Path(os.getenv("ProgramData", r"C:\ProgramData")) / "NorthstarVPN" / "runs"
        base.mkdir(parents=True, exist_ok=True)
        harden_acl(base, directory=True)
        run_dir = base / secrets.token_hex(16)
        run_dir.mkdir()
        harden_acl(run_dir, directory=True)
        return run_dir
    return Path(tempfile.mkdtemp(prefix="northstar-openvpn-"))


def write_secure(path: Path, text: str) -> None:
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, text.encode("utf-8"))
    finally:
        os.close(descriptor)
    harden_acl(path)


def safe_environment(run_dir: Path) -> dict[str, str]:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    return {
        "SystemRoot": system_root,
        "windir": system_root,
        "TEMP": str(run_dir),
        "TMP": str(run_dir),
        "PATH": os.path.join(system_root, "System32") + os.pathsep + system_root,
        "ProgramFiles": os.environ.get("ProgramFiles", r"C:\Program Files"),
        "ProgramFiles(x86)": os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        "CommonProgramFiles": os.environ.get("CommonProgramFiles", r"C:\Program Files\Common Files"),
        "ProgramData": os.environ.get("ProgramData", r"C:\ProgramData"),
    }


class HelperError(RuntimeError):
    pass


class OpenVpnExitEvent:
    """OpenVPN's Windows service exit event permits route cleanup on shutdown."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.name = "Local\\NorthstarVPN-exit-" + secrets.token_hex(24)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateEventW.restype = wintypes.HANDLE
        self.kernel.SetEvent.argtypes = [wintypes.HANDLE]
        self.kernel.SetEvent.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel.CreateEventW(None, True, False, self.name)
        if not self.handle:
            raise HelperError("Could not create the OpenVPN shutdown event.")

    def signal(self):
        if not self.kernel.SetEvent(self.handle):
            raise HelperError("Could not signal OpenVPN shutdown.")

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def stop_openvpn(process, exit_event=None):
    try:
        if process is not None and process.poll() is None:
            try:
                if exit_event:
                    exit_event.signal()
                else:
                    process.terminate()
                process.wait(timeout=15)
            except Exception:
                process.kill()
                process.wait(timeout=5)
    finally:
        if exit_event:
            exit_event.close()


class IPv6Guard:
    """System-wide IPv6 block; intentionally persists after a helper crash."""

    def _run(self, action):
        powershell = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                                 "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        root = Path(sys.executable).resolve().parent.parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
        script = root / "scripts" / "windows-ipv6-guard.ps1"
        try:
            result = subprocess.run(
                [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", str(script), "-Action", action],
                capture_output=True, text=True, timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0:
                raise HelperError("IPv6 firewall guard failed; check Windows Firewall and helper permissions."
                                  " Use scripts/windows-ipv6-guard.ps1 -Action Disable for recovery.")
            value = json.loads(result.stdout)
            if not isinstance(value, dict) or not isinstance(value.get("blocked"), bool):
                raise ValueError("invalid guard result")
            return value
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            raise HelperError("Unable to verify the IPv6 firewall guard; refusing an unprotected connection.") from exc

    def enable(self):
        if self._run("Enable")["blocked"] is not True:
            raise HelperError("IPv6 firewall block was not applied; refusing to connect.")

    def disable(self):
        if self._run("Disable").get("rule_present") is not False:
            raise HelperError("IPv6 remains blocked; use the documented recovery command.")

    def blocked(self):
        return self._run("Status")["blocked"]


class HelperState:
    def __init__(self, profile_root: Path):
        self.profile_root = profile_root
        self.lock = threading.RLock()
        self.op_lock = threading.Lock()
        self.process = None
        self.connection_id = None
        self.profile_path = None
        self.remote_endpoint = None
        self.transport = None
        self.started = None
        self.log_path = None
        self.status_path = None
        self.run_dir = None
        self.ipv6_guard = IPv6Guard()
        self.exit_event = None

    def health(self):
        try:
            blocked = self.ipv6_guard.blocked()
        except HelperError:
            blocked = False
        if self.is_connected() and not blocked:
            with self.lock:
                self.disconnect_locked()
        return {"ok": True, "openvpn": Path(OPENVPN).is_file(), "connected": self.is_connected(),
                "ipv6_blocked": blocked, "ipv6_guard_required": True}

    def is_connected(self) -> bool:
        with self.lock:
            return self.process is not None and self.process.poll() is None

    def connect(self, profile_id, profile_path, endpoint=None, endpoint_port=None, username="", password=""):
        if not isinstance(profile_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", profile_id):
            raise ValueError("invalid profile id")
        username = validate_username(username)
        password = validate_password(password)
        text = read_profile(Path(profile_path), self.profile_root)
        config, selected, transport = sanitize_profile(text, endpoint, endpoint_port)
        if endpoint is None:
            # Keep one validated endpoint so every selected remote can be checked
            # before the privileged process connects.
            first_host, first_port = selected[0]
            config, selected, transport = sanitize_profile(text, first_host, first_port)
        for host, port in selected:
            ensure_public_endpoint(host, port)

        with self.op_lock:
            # Apply and verify before touching the existing session or launching
            # OpenVPN. The rule stays in place during reconnects and on crashes.
            self.ipv6_guard.enable()
            with self.lock:
                self.disconnect_locked()
            run_dir = secure_run_dir()
            config_path = run_dir / "profile.ovpn"
            auth_path = run_dir / "auth.txt"
            log_path = run_dir / "openvpn.log"
            status_path = run_dir / "status.txt"
            process = None
            exit_event = None
            try:
                write_secure(config_path, config)
                write_secure(auth_path, f"{username}\n{password}\n")
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                command = [
                    OPENVPN,
                    "--config",
                    str(config_path),
                    "--auth-user-pass",
                    str(auth_path),
                    "--auth-nocache",
                    "--script-security",
                    "0",
                    "--route-method",
                    "ipapi",
                    "--ip-win32",
                    "ipapi",
                    "--log",
                    str(log_path),
                    "--status",
                    str(status_path),
                    "5",
                ]
                if os.name == "nt":
                    exit_event = OpenVpnExitEvent()
                    command.extend(["--service", exit_event.name, "0"])
                process = subprocess.Popen(
                    command,
                    cwd=str(run_dir),
                    env=safe_environment(run_dir),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags,
                )
                deadline = time.time() + CONNECT_TIMEOUT
                connected = False
                while time.time() < deadline:
                    if process.poll() is not None:
                        raise HelperError("OpenVPN exited before connecting. Check the helper log.")
                    try:
                        log_text = log_path.read_text(encoding="utf-8", errors="replace")[-200_000:]
                    except OSError:
                        log_text = ""
                    if "Initialization Sequence Completed" in log_text:
                        connected = True
                        break
                    time.sleep(0.5)
                if not connected:
                    raise HelperError("OpenVPN connection timed out")
            except Exception:
                stop_openvpn(process, exit_event)
                shutil.rmtree(run_dir, ignore_errors=True)
                raise

            with self.lock:
                self.process = process
                self.exit_event = exit_event
                self.connection_id = profile_id
                self.profile_path = str(profile_path)
                self.remote_endpoint = f"{selected[0][0]}:{selected[0][1]}"
                self.transport = transport
                self.started = time.time()
                self.log_path = log_path
                self.status_path = status_path
                self.run_dir = run_dir
                return {"ok": True, "connection_id": profile_id, "connected_since": self.started}

    def disconnect_locked(self):
        process = self.process
        exit_event = self.exit_event
        run_dir = self.run_dir
        self.process = None
        self.exit_event = None
        self.connection_id = None
        self.profile_path = None
        self.remote_endpoint = None
        self.transport = None
        self.started = None
        self.log_path = None
        self.status_path = None
        self.run_dir = None
        stop_openvpn(process, exit_event)
        if run_dir is not None:
            shutil.rmtree(run_dir, ignore_errors=True)

    def disconnect(self, connection_id=None):
        with self.op_lock:
            with self.lock:
                if connection_id is not None and self.connection_id is not None and connection_id != self.connection_id:
                    raise ValueError("connection id does not match")
                self.disconnect_locked()
                # Only an explicit user disconnect releases the persistent block.
                self.ipv6_guard.disable()
                return {"ok": True, "state": "disconnected"}

    def status(self):
        with self.lock:
            connected = self.process is not None and self.process.poll() is None
            if self.process is not None and not connected:
                self.disconnect_locked()
        if not connected:
            return {
                "ok": True,
                "connected": False,
                "connection_id": None,
                "interface": None,
                "vpn_ip": None,
                "remote_endpoint": None,
                "transport": None,
                "connected_since": None,
                "bytes_in": 0,
                "bytes_out": 0,
            }
        with self.lock:
            status_path = self.status_path
            connection_id = self.connection_id
            remote_endpoint = self.remote_endpoint
            transport = self.transport
            started = self.started
        interface = self._interface_name()
        vpn_ip = self._tunnel_ip(interface)
        bytes_in, bytes_out = self._counters(interface, status_path)
        return {
            "ok": True,
            "connected": True,
            "connection_id": connection_id,
            "interface": interface,
            "vpn_ip": vpn_ip,
            "remote_endpoint": remote_endpoint,
            "transport": transport,
            "connected_since": started,
            "bytes_in": bytes_in,
            "bytes_out": bytes_out,
        }

    @staticmethod
    def _powershell() -> str:
        return os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"),
            "System32",
            "WindowsPowerShell",
            "v1.0",
            "powershell.exe",
        )

    def _tunnel_ip(self, interface):
        # PUSH_REPLY describes requested configuration, not necessarily the
        # address Windows actually assigned (notably with TAP DHCP emulation).
        if not interface:
            return None
        try:
            environment = safe_environment(Path(tempfile.gettempdir()))
            environment["NS_IFACE"] = interface
            command = (
                "[System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() | "
                "Where-Object { $_.Name -eq $env:NS_IFACE -and $_.OperationalStatus -eq 'Up' } | "
                "ForEach-Object { $_.GetIPProperties().UnicastAddresses } | "
                "Where-Object { $_.Address.AddressFamily -eq 'InterNetwork' } | "
                "ForEach-Object { $_.Address.IPAddressToString }"
            )
            result = subprocess.run(
                [
                    self._powershell(),
                    "-NoProfile",
                    "-Command",
                    command,
                ],
                capture_output=True,
                text=True,
                timeout=5,
                env=environment,
            )
            if result.returncode == 0:
                for value in result.stdout.splitlines():
                    try:
                        address = ipaddress.IPv4Address(value.strip())
                    except ValueError:
                        continue
                    if not (address.is_unspecified or address.is_loopback or address.is_link_local or address.is_multicast):
                        return str(address)
        except Exception:
            pass
        return None

    def _interface_name(self):
        try:
            result = subprocess.run(
                [
                    self._powershell(),
                    "-NoProfile",
                    "-Command",
                    "Get-NetAdapter | Where-Object { $_.InterfaceDescription -match 'TAP|OpenVPN|Wintun' -and $_.Status -eq 'Up' } | Select-Object -First 1 -ExpandProperty Name",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                env=safe_environment(Path(tempfile.gettempdir())),
            )
            value = result.stdout.strip()
            if re.fullmatch(r"[A-Za-z0-9 _.-]{1,64}", value):
                return value
        except Exception:
            pass
        return None

    @staticmethod
    def _parse_status_counters(text):
        """Parse a complete OpenVPN client statistics snapshot, or return None."""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines or lines[0] != "OpenVPN STATISTICS" or lines[-1] != "END":
            return None
        values = {}
        for line in lines[1:-1]:
            key, separator, value = line.partition(",")
            if key not in {"TUN/TAP read bytes", "TUN/TAP write bytes"}:
                continue
            if not separator or key in values or not re.fullmatch(r"[0-9]+", value.strip()):
                return None
            values[key] = int(value.strip())
        if len(values) != 2:
            return None
        # OpenVPN reads outbound packets from TUN and writes inbound packets to
        # TUN; these directions are reversed from its network socket counters.
        return values["TUN/TAP write bytes"], values["TUN/TAP read bytes"]

    def _counters(self, interface, status_path=None):
        if status_path:
            try:
                with Path(status_path).open("r", encoding="utf-8", errors="replace") as handle:
                    text = handle.read(64 * 1024 + 1)
                if len(text) <= 64 * 1024:
                    counters = self._parse_status_counters(text)
                    if counters is not None:
                        return counters
            except (OSError, ValueError):
                pass
        if not interface:
            return 0, 0
        try:
            command = (
                "$adapter = [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() | "
                "Where-Object { $_.Name -eq $env:NS_IFACE -and $_.OperationalStatus -eq 'Up' } | "
                "Select-Object -First 1; "
                "if ($null -ne $adapter) { $stats = $adapter.GetIPv4Statistics(); "
                "$stats.BytesReceived; $stats.BytesSent }"
            )
            environment = safe_environment(Path(tempfile.gettempdir()))
            environment["NS_IFACE"] = interface
            result = subprocess.run(
                [self._powershell(), "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
                timeout=5,
                env=environment,
            )
            values = [int(line.strip()) for line in result.stdout.splitlines() if line.strip().isdigit()]
            if result.returncode == 0 and len(values) == 2:
                return values[0], values[1]
        except Exception:
            pass
        return 0, 0


def authorized(request: dict, token: str) -> bool:
    supplied = request.get("token")
    if not isinstance(supplied, str):
        return False
    try:
        return secrets.compare_digest(supplied.encode("utf-8"), token.encode("utf-8"))
    except (UnicodeError, TypeError):
        return False


def handle_request(state: HelperState, request, token: str):
    if not isinstance(request, dict):
        return {"ok": False, "error": "invalid request"}
    if not authorized(request, token):
        return {"ok": False, "error": "unauthorized"}
    action = request.get("action")
    try:
        if action == "health":
            return state.health()
        if action == "connect":
            return state.connect(
                request.get("profile_id", ""),
                request.get("profile_path", ""),
                request.get("endpoint"),
                request.get("endpoint_port"),
                request.get("username", ""),
                request.get("password", ""),
            )
        if action == "disconnect":
            return state.disconnect(request.get("connection_id"))
        if action == "status":
            return state.status()
        return {"ok": False, "error": "unknown action"}
    except (ValueError, HelperError) as exc:
        return {"ok": False, "error": str(exc)[:240]}
    except Exception:
        traceback.print_exc()
        return {"ok": False, "error": "internal error"}


def client_worker(client: socket.socket, state: HelperState, token: str, semaphore: threading.BoundedSemaphore):
    with client:
        try:
            if not semaphore.acquire(blocking=False):
                client.sendall(json.dumps({"ok": False, "error": "busy"}).encode() + b"\n")
                return
            try:
                peer = client.getpeername()[0]
                if not is_loopback(peer):
                    return
                client.settimeout(10)
                # Packaged clients require proof that this socket belongs to the
                # token-owning service before sending VPN credentials. Legacy
                # development clients may still send one authenticated request.
                data = bytearray()
                for index in range(2):
                    while b"\n" not in data:
                        chunk = client.recv(4096)
                        if not chunk:
                            return
                        data.extend(chunk)
                        if len(data) > MAX_REQUEST_BYTES:
                            return
                    line, _, remaining = data.partition(b"\n")
                    data = bytearray(remaining)
                    try:
                        request = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        return
                    if index == 0 and isinstance(request, dict) and request.get("action") == "challenge":
                        nonce = request.get("nonce")
                        if not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{64}", nonce):
                            return
                        proof = hmac.new(token.encode(), b"northstar-helper-v1:" + nonce.encode("ascii"), hashlib.sha256).hexdigest()
                        response = {"ok": True, "proof": proof}
                        client.sendall(json.dumps(response).encode() + b"\n")
                        continue
                    response = handle_request(state, request, token)
                    client.sendall(json.dumps(response).encode() + b"\n")
                    return
            finally:
                semaphore.release()
        except (OSError, socket.timeout, ConnectionError):
            pass


def serve(host: str, port: int, token: str, state: HelperState, stop_event=None):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            server.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen(5)
        server.settimeout(0.5)
        semaphore = threading.BoundedSemaphore(4)
        while stop_event is None or not stop_event.is_set():
            try:
                client, _ = server.accept()
            except socket.timeout:
                continue
            threading.Thread(
                target=client_worker,
                args=(client, state, token, semaphore),
                daemon=True,
            ).start()


def load_token(explicit: str | None) -> str:
    token = explicit or os.getenv("VPN_WINDOWS_HELPER_TOKEN")
    if not token:
        try:
            token = token_path().read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
    token = (token or "").strip()
    if len(token) < TOKEN_MIN or token == "northstar-dev-token":
        raise SystemExit(
            "Refusing to start without a strong helper token. "
            f"Set VPN_WINDOWS_HELPER_TOKEN or write at least {TOKEN_MIN} characters to {token_path()}."
        )
    return token


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--token", default=None)
    parser.add_argument("--profile-root", default=os.getenv("VPN_PROFILE_ROOT"))
    args = parser.parse_args()
    if not is_loopback(args.host):
        raise SystemExit("the helper may only bind to a loopback address")
    token = load_token(args.token)
    root = Path(args.profile_root) if args.profile_root else Path(__file__).resolve().parents[1]
    if not root.is_dir():
        raise SystemExit(f"profile root does not exist: {root}")
    if not Path(OPENVPN).is_file():
        print(f"warning: OpenVPN executable not found at {OPENVPN}")
    state = HelperState(root)
    print(f"Northstar Windows helper listening on {args.host}:{args.port}")
    serve(args.host, args.port, token, state)


if __name__ == "__main__":
    main()
