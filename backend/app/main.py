from pathlib import Path
import os
import platform
import secrets
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from . import diagnostics
from .network_manager import NetworkManagerAdapter
from .profiles import ProfileCatalog
from .secrets import CredentialStore, Credentials
from .service import MissingCredentials, VpnService
from .settings import SettingsStore
from .protection import ProtectionClient

if platform.system() == "Windows":
    from .windows_openvpn import WindowsOpenVpnAdapter

ROOT = Path(sys.executable).resolve().parent.parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
frontend_dist = ROOT / "frontend" / "dist"
catalog = ProfileCatalog(ROOT / "profiles" if getattr(sys, "frozen", False) else Path(os.getenv("VPN_PROFILE_ROOT", ROOT)))
catalog.scan()
if platform.system() == "Windows":
    manager = WindowsOpenVpnAdapter()
else:
    manager = NetworkManagerAdapter()
store = CredentialStore()
settings = SettingsStore()
if platform.system() == "Windows":
    protection = None
else:
    protection = ProtectionClient(settings)
service = VpnService(manager, store, catalog, protection, settings)


@asynccontextmanager
async def lifespan(app):
    stopped = threading.Event()
    def reconcile():
        while not stopped.wait(8):
            try:
                service.reconcile()
            except Exception:
                pass
    threading.Thread(target=reconcile, daemon=True).start()
    yield
    stopped.set()


app = FastAPI(title="Northstar VPN Desktop", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"], allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Content-Type", "X-CSRF-Token"])

class ConnectBody(BaseModel):
    profile_id: str
    endpoint: str | None = None
class CredentialBody(BaseModel): username: str; password: str
class LatencyBody(BaseModel): profile_ids: list[str]

@app.middleware("http")
async def local_only(request: Request, call_next):
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "testclient", "localhost"}:
        return JSONResponse({"detail": "local access only"}, status_code=403)
    if request.url.hostname not in {"127.0.0.1", "::1", "localhost", "testserver"}:
        return JSONResponse({"detail": "invalid host"}, status_code=403)
    allowed_origins = {"http://127.0.0.1:5173", "http://localhost:5173", f"http://127.0.0.1:{os.getenv('VPN_UI_PORT', '8766')}"}
    if request.headers.get("origin") and request.headers["origin"] not in allowed_origins:
        return JSONResponse({"detail": "invalid origin"}, status_code=403)
    token = os.getenv("VPN_API_TOKEN", "local-ui")
    if request.method in {"POST", "PUT", "DELETE"} and not secrets.compare_digest(request.headers.get("x-csrf-token", ""), token):
        return JSONResponse({"detail": "invalid csrf token"}, status_code=403)
    return await call_next(request)

def public_profile(p):
    return {"id": p.id, "country_code": p.country_code, "city": p.city, "transport": p.transport, "virtual": p.virtual, "servers": [{"host": server.host, "port": server.port} for server in p.servers]}

@app.get("/api/health")
def health():
    return {"backend": "ok", "instance": os.getenv("VPN_INSTANCE"), **manager.health()}

@app.get("/api/profiles")
def profiles():
    return {"profiles": [public_profile(p) for p in catalog.list()]}

@app.post("/api/profiles/refresh")
def refresh_profiles():
    return {"profiles": [public_profile(p) for p in service.refresh_profiles()]}

@app.get("/api/status")
def status(): return service.status()

@app.post("/api/connect")
def connect(body: ConnectBody):
    try:
        response = service.connect(body.profile_id, body.endpoint)
        if response["state"] == "error" or response.get("error"):
            raise HTTPException(502, response["error"] or "connection failed")
        return response
    except KeyError: raise HTTPException(404, "unknown profile")
    except MissingCredentials: raise HTTPException(428, "credentials required")

@app.post("/api/disconnect")
def disconnect(): return service.disconnect()

@app.get("/api/settings/credentials")
def credentials():
    value = store.get()
    return {"configured": bool(value), "username": value.username if value else None}

@app.put("/api/settings/credentials")
def save_credentials(body: CredentialBody):
    try: store.save(Credentials(body.username, body.password))
    except ValueError as exc: raise HTTPException(400, str(exc))
    return {"configured": True, "username": body.username.strip()}

@app.delete("/api/settings/credentials")
def clear_credentials():
    store.clear()
    return {"configured": False, "username": None}

@app.post("/api/settings/credentials/test")
def test_credentials():
    if not store.get():
        raise HTTPException(428, "credentials required")
    return {"configured": True, "message": "Credentials are available in the operating system credential store."}

@app.get("/api/diagnostics")
def get_diagnostics():
    return {"health": manager.health(), "status": service.status()}

@app.post("/api/speed-test")
def speed_test():
    try: return diagnostics.run_cloudflare_speed_test()
    except Exception as exc: raise HTTPException(502, f"speed test failed: {str(exc)[:120]}")


PROTECTION_KEYS = ("ipv6_protection", "dns_protection", "kill_switch", "allow_lan")
WINDOWS_PROTECTION = {
    "available": False,
    "active": False,
    "platform": "windows",
    "error": "Windows connections require IPv6 blocking. DNS protection and the kill switch are unavailable.",
}


def effective_settings():
    values = settings.get()
    if protection is None:
        values = {**values, "ipv6_protection": False, "dns_protection": False, "kill_switch": False, "allow_lan": False}
    return values


@app.get("/api/settings")
def get_settings():
    protection_status = protection.status() if protection else WINDOWS_PROTECTION
    return {"settings": effective_settings(), "protection": protection_status}


@app.put("/api/settings")
def update_settings(values: dict):
    try:
        with service.lock:
            settings.validate(values)
            if protection is None and any(values.get(key) is True for key in PROTECTION_KEYS):
                raise HTTPException(400, "Windows network protection is not implemented yet.")
            updated = {**effective_settings(), **values}
            if protection and any(key in values for key in PROTECTION_KEYS):
                protection.configure(updated)
            settings.save(values)
            protection_status = protection.status() if protection else WINDOWS_PROTECTION
            return {"settings": updated, "protection": protection_status}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


@app.post("/api/switch-ip")
def switch_ip():
    try:
        response = service.switch_ip()
        if response["state"] == "error" or response.get("error"):
            raise HTTPException(502, response["error"])
        return response
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


def profile_latency(profile):
    if not profile.servers:
        return profile.id, None
    server = profile.servers[0]
    result = diagnostics.measure_latency(server.host, server.port if profile.transport == "tcp" else 443, timeout=1.5)
    return profile.id, result["latency_ms"]


@app.post("/api/latencies")
def latencies(body: LatencyBody):
    if len(body.profile_ids) > 302:
        raise HTTPException(400, "Too many profiles")
    try:
        profiles = [catalog.get(value) for value in dict.fromkeys(body.profile_ids)]
    except KeyError:
        raise HTTPException(404, "Unknown profile")
    with ThreadPoolExecutor(max_workers=24) as executor:
        return {"latencies": dict(executor.map(profile_latency, profiles)), "method": "TCP handshake; UDP reachability is not tested"}


@app.post("/api/best")
def connect_best():
    profiles = [p for p in catalog.list() if p.transport == settings.get()["transport"]]
    with ThreadPoolExecutor(max_workers=24) as executor:
        results = [(identifier, delay) for identifier, delay in executor.map(profile_latency, profiles) if delay is not None]
    if not results:
        raise HTTPException(502, "No reachable location found")
    return connect(ConnectBody(profile_id=min(results, key=lambda item: item[1])[0]))

def mount_frontend():
    if frontend_dist.is_dir() and (frontend_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

mount_frontend()
