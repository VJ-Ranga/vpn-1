import threading
import time

from .diagnostics import Counters, calculate_rates, get_public_ip, measure_latency
from .network_manager import NetworkManagerError


class MissingCredentials(RuntimeError):
    pass


class VpnService:
    def __init__(self, manager, store, catalog, protection=None, settings=None):
        self.manager, self.store, self.catalog = manager, store, catalog
        self.active_profile_id = None
        self.active_connection_id = None
        self.state = "disconnected"
        self.error = None
        self.started = None
        self.lock = threading.RLock()
        self.protection, self.settings = protection, settings
        self.counter_connection = None
        self.counter_baseline = None
        self.last_profile_id = None
        self.reconnect_requested = False
        self.previous_counters = None
        self.previous_counter_time = None
        self._reset_session_baseline()

    def _reset_session_baseline(self):
        active = self.manager.active() if self.manager else None
        if active:
            self.counter_baseline = Counters(active.bytes_in, active.bytes_out)
        else:
            self.counter_baseline = None

    def status(self):
        with self.lock:
            return self._status()

    def _status(self):
        active = self.manager.active()
        if active and not self.active_profile_id:
            for candidate in self.catalog.list():
                stable_name = f"Namecheap VPN / {candidate.country_code} {candidate.city} / {candidate.transport.upper()}"
                if active.name in {stable_name, candidate.path.stem}:
                    self.active_profile_id = candidate.id
                    self.active_connection_id = active.connection_id
                    self.state = "connected"
                    self.started = active.connected_since or time.time()
                    break
        connected = active is not None and (self.state == "connected" or self.active_profile_id is not None)
        health = self.manager.health()
        adapter_reachable = health.get("reachable", health.get("network_manager", False))
        if self.state == "connected" and active is None and adapter_reachable:
            self.state = "disconnected"
            self.active_profile_id = self.active_connection_id = None
            self.started = None
        profile = None
        if self.active_profile_id:
            try:
                profile = self.catalog.get(self.active_profile_id)
            except KeyError:
                pass
        now = time.monotonic()
        current = Counters(active.bytes_in, active.bytes_out) if connected and active else None
        if current and self.counter_connection != active.connection_id:
            self.counter_connection = active.connection_id
            self.counter_baseline = current
            self.previous_counters = current
            self.previous_counter_time = now
        if current and self.previous_counters and self.previous_counter_time:
            rates = calculate_rates(self.previous_counters, current, now - self.previous_counter_time)
        elif current:
            rates = calculate_rates(Counters(0, 0), current, 1)
        else:
            rates = calculate_rates(Counters(0, 0), Counters(0, 0), 1)
        self.previous_counters, self.previous_counter_time = current, now
        latency = None
        return {
            "state": self.state,
            "profile_id": self.active_profile_id,
            "city": profile.city if profile else None,
            "country_code": profile.country_code if profile else None,
            "transport": profile.transport if profile else active.transport if connected and active else None,
            "interface": active.interface if connected and active else None,
            "remote_endpoint": active.remote_endpoint if connected and active else None,
            "vpn_ip": active.vpn_ip if connected and active else None,
            "public_ip": get_public_ip(active.vpn_ip) if connected and active.vpn_ip else None,
            "latency": latency,
            "duration_seconds": int(time.time() - self.started) if self.started else 0,
            "bytes_in": max(0, active.bytes_in - self.counter_baseline.download) if current and self.counter_baseline else 0,
            "bytes_out": max(0, active.bytes_out - self.counter_baseline.upload) if current and self.counter_baseline else 0,
            "download_bps": rates.download_bps,
            "upload_bps": rates.upload_bps,
            "error": self.error,
            "protection": self.protection.status() if self.protection else {
                "available": False, "active": False, "platform": "windows",
                "ipv6_blocked": health.get("ipv6_blocked") is True,
                "ipv6_guard_required": health.get("ipv6_guard_required") is True,
                "error": "DNS protection and the kill switch are unavailable on Windows.",
            } if health.get("platform") == "windows" else None,
        }

    def connect(self, profile_id: str, endpoint: str | None = None):
        with self.lock:
            credentials = self.store.get()
            if not credentials:
                raise MissingCredentials("credentials required")
            profile = self.catalog.get(profile_id)
            self.state, self.error = "connecting", None
            connection = None
            try:
                if self.protection:
                    self.protection.prepare(profile)
                active = self.manager.active()
                if active:
                    self.manager.disconnect(active.connection_id)
                connection = self.manager.import_profile(profile, endpoint) if endpoint else self.manager.import_profile(profile)
                self.manager.connect(connection, credentials)
                if self.protection:
                    protection = self.protection.confirm()
                    if protection.get("required", True) and (not protection.get("available") or protection.get("error")):
                        self.manager.disconnect(connection)
                        raise RuntimeError("VPN protection could not be verified")
                self.active_profile_id, self.active_connection_id = profile_id, connection
                self.last_profile_id, self.reconnect_requested = profile_id, True
                self.state, self.started = "connected", time.time()
                self._reset_session_baseline()
            except (NetworkManagerError, RuntimeError) as exc:
                if connection:
                    try:
                        self.manager.disconnect(connection)
                    except NetworkManagerError:
                        pass
                # A failed switch leaves no trusted active connection to report.
                self.active_profile_id = self.active_connection_id = None
                self.started = None
                self.state, self.error = "error", str(exc)
                if self.protection:
                    try:
                        self.protection.release()
                    except RuntimeError:
                        pass
            return self.status()

    def disconnect(self):
        with self.lock:
            self.reconnect_requested = False
            active = self.manager.active()
            if active or getattr(self.manager, "disconnect_when_inactive", False):
                try:
                    self.manager.disconnect(active.connection_id if active else None)
                except NetworkManagerError as exc:
                    self.state, self.error = "error", str(exc)
                    return self.status()
            self.active_profile_id, self.active_connection_id = None, None
            self.state, self.started, self.error = "disconnected", None, None
            self._reset_session_baseline()
            if self.protection:
                try:
                    self.protection.release()
                except RuntimeError as exc:
                    self.error = str(exc)
            return self.status()

    def switch_ip(self):
        with self.lock:
            active = self.manager.active()
            if not active or not self.active_profile_id:
                raise RuntimeError("Connect to a location first")
            profile = self.catalog.get(self.active_profile_id)
            current = self.manager.endpoints.get(profile.id)
            candidates = [server.host for server in profile.servers if server.host != current]
            if active.remote_endpoint:
                import socket
                remaining = []
                for host in candidates:
                    try:
                        addresses = {item[4][0] for item in socket.getaddrinfo(host, None, socket.AF_INET)}
                    except OSError:
                        continue
                    if active.remote_endpoint.split(":")[0] not in addresses:
                        remaining.append(host)
                candidates = remaining
            if not candidates:
                raise RuntimeError("No alternate server is available in this location")
            return self.connect(profile.id, candidates[0])

    def reconcile(self):
        if not self.lock.acquire(blocking=False):
            return
        try:
            if self.settings and self.settings.get()["auto_reconnect"] and self.reconnect_requested and self.last_profile_id and not self.manager.active():
                self.connect(self.last_profile_id)
        finally:
            self.lock.release()

    def refresh_profiles(self):
        return self.catalog.scan()
