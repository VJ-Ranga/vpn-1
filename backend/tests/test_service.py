from app.service import VpnService
from app.secrets import Credentials
from app.network_manager import ActiveConnection, NetworkManagerError


class Store:
    def get(self):
        return Credentials("user", "secret")


class Manager:
    def __init__(self):
        self.calls = []

    def active(self):
        return None

    def health(self):
        return {"network_manager": True, "openvpn_plugin": True}

    def import_profile(self, profile):
        self.calls.append(("import", profile.id))
        return "uuid-1"

    def connect(self, connection_id, credentials):
        self.calls.append(("connect", connection_id, credentials.username, credentials.password))

    def disconnect(self, connection_id):
        self.calls.append(("disconnect", connection_id))


def test_status_reconciles_active_networkmanager_profile_after_restart():
    class ActiveManager(Manager):
        def active(self):
            return ActiveConnection("uuid-1", "Namecheap VPN / DE Frankfurt / UDP", "tun0", "10.8.0.2")

    class PathCatalog(Catalog):
        def __init__(self):
            super().__init__()
            self.profile.path = type("Path", (), {"stem": "unused"})()

        def list(self):
            return [self.profile]

    service = VpnService(ActiveManager(), Store(), PathCatalog())

    status = service.status()

    assert status["state"] == "connected"
    assert status["profile_id"] == "new"
    assert status["city"] == "Frankfurt"


class Catalog:
    def __init__(self):
        self.profile = type("Profile", (), {"id": "new", "city": "Frankfurt", "country_code": "DE", "transport": "udp"})()

    def get(self, profile_id):
        assert profile_id == "new"
        return self.profile


def test_connect_passes_secret_service_credentials_to_manager():
    manager = Manager()
    service = VpnService(manager, Store(), Catalog())

    service.connect("new")

    assert manager.calls == [
        ("import", "new"),
        ("connect", "uuid-1", "user", "secret"),
    ]


def test_switch_failure_clears_stale_active_state():
    class FailingManager(Manager):
        def connect(self, connection_id, credentials):
            raise NetworkManagerError("connection failed")

    service = VpnService(FailingManager(), Store(), Catalog())
    service.active_profile_id = "old"
    service.active_connection_id = "old-uuid"
    service.state = "connected"

    status = service.connect("new")

    assert status["state"] == "error"
    assert status["profile_id"] is None
    assert service.active_connection_id is None


def test_refresh_profiles_rescans_catalog():
    class RefreshingCatalog(Catalog):
        def scan(self):
            return [self.profile]

    catalog = RefreshingCatalog()
    service = VpnService(Manager(), Store(), catalog)

    assert service.refresh_profiles() == [catalog.profile]


def test_protection_failure_prevents_vpn_activation():
    import pytest
    class Protection:
        def prepare(self, profile):
            raise RuntimeError("Install protection helper")
        def release(self):
            pass
        def status(self):
            return {"available": False}
    manager = Manager()
    service = VpnService(manager, Store(), Catalog(), protection=Protection())
    service.connect("new")
    assert not manager.calls
    assert service.state == "error"


def test_failed_connect_releases_prepared_protection():
    calls = []
    class Protection:
        def prepare(self, profile):
            calls.append("prepare")
        def release(self):
            calls.append("release")
        def status(self):
            return {"available": True}
    class FailingManager(Manager):
        def connect(self, connection_id, credentials):
            calls.append("connect")
            raise NetworkManagerError("connection failed")
    service = VpnService(FailingManager(), Store(), Catalog(), protection=Protection())
    service.connect("new")
    assert calls == ["prepare", "connect", "release"]


def test_reconnect_does_not_try_to_disconnect_missing_tunnel():
    class Preferences:
        def get(self):
            return {"auto_reconnect": True}
    class DroppedManager(Manager):
        def disconnect(self, connection_id):
            raise NetworkManagerError("Already disconnected")
    manager = DroppedManager()
    service = VpnService(manager, Store(), Catalog(), settings=Preferences())
    service.active_profile_id, service.active_connection_id = "new", "uuid-old"
    service.last_profile_id, service.reconnect_requested = "new", True
    service.state = "connected"
    service.reconcile()
    assert any(call[0] == "connect" for call in manager.calls)


def test_session_counters_start_at_zero_on_existing_tunnel(monkeypatch):
    import app.service as module
    monkeypatch.setattr(module, "get_public_ip", lambda *args: "203.0.113.8")
    class ActiveManager(Manager):
        value = ActiveConnection("uuid-1", "Namecheap VPN / DE Frankfurt / UDP", "tun0", "10.8.0.2", bytes_in=8000, bytes_out=5000)
        def active(self):
            return self.value
    class PathCatalog(Catalog):
        def list(self):
            self.profile.path = type("Path", (), {"stem": "unused"})()
            return [self.profile]
    manager = ActiveManager()
    service = VpnService(manager, Store(), PathCatalog())
    assert service.status()["bytes_in"] == 0
    manager.value.bytes_in = 10000
    manager.value.bytes_out = 6000
    result = service.status()
    assert result["bytes_in"] == 2000
    assert result["bytes_out"] == 1000


def test_failed_protection_confirmation_disconnects_new_tunnel():
    calls = []
    class Protection:
        def prepare(self, profile):
            pass
        def confirm(self):
            raise RuntimeError("VPN protection could not be verified")
        def release(self):
            calls.append("release")
        def status(self):
            return {"available": False}
    class ActiveManager(Manager):
        connection = None
        def active(self):
            return self.connection
        def connect(self, connection_id, credentials):
            self.connection = ActiveConnection(connection_id, "Namecheap VPN / DE Frankfurt / UDP", "tun0")
        def disconnect(self, connection_id):
            calls.append("disconnect")
            self.connection = None
    class PathCatalog(Catalog):
        def list(self):
            self.profile.path = type("Path", (), {"stem": "unused"})()
            return [self.profile]
    service = VpnService(ActiveManager(), Store(), PathCatalog(), protection=Protection())
    service.connect("new")
    assert calls == ["disconnect", "release"]


def test_reconnecting_same_uuid_resets_session_counter_baseline(monkeypatch):
    import app.service as module
    monkeypatch.setattr(module, "get_public_ip", lambda *args: "203.0.113.8")
    class ReusingManager(Manager):
        value = ActiveConnection("uuid-1", "Namecheap VPN / DE Frankfurt / UDP", "tun0", "10.8.0.2", bytes_in=8000)
        def active(self):
            return self.value
        def connect(self, connection_id, credentials):
            self.value.bytes_in = 500
    class PathCatalog(Catalog):
        def list(self):
            self.profile.path = type("Path", (), {"stem": "unused"})()
            return [self.profile]
    manager = ReusingManager()
    service = VpnService(manager, Store(), PathCatalog())
    service.status()
    service.connect("new")
    manager.value.bytes_in += 2000
    assert service.status()["bytes_in"] == 2000
