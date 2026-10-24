from dataclasses import dataclass
import socket
import time
import httpx
import ipaddress

_public_ip_cache: dict[str | None, tuple[float, str | None]] = {}

@dataclass
class Counters:
    download: int
    upload: int

@dataclass
class Rates:
    download_bps: int
    upload_bps: int

def calculate_rates(previous: Counters, current: Counters, elapsed: float) -> Rates:
    if elapsed <= 0:
        return Rates(0, 0)
    return Rates(max(0, int((current.download - previous.download) / elapsed)), max(0, int((current.upload - previous.upload) / elapsed)))

def measure_latency(host: str, port: int, timeout: float = 2.0) -> dict:
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {"host": host, "latency_ms": round((time.perf_counter() - started) * 1000, 1)}
    except OSError as exc:
        return {"host": host, "latency_ms": None, "error": str(exc)[:120]}

def get_public_ip(local_address: str | None = None) -> str | None:
    cached = _public_ip_cache.get(local_address, (0, None))
    if time.monotonic() - cached[0] < (30 if cached[1] else 5):
        return cached[1]
    try:
        transport = httpx.HTTPTransport(local_address=local_address, trust_env=False)
        with httpx.Client(transport=transport, timeout=5, trust_env=False) as client:
            response = client.get("https://api.ipify.org")
        response.raise_for_status()
        value = str(ipaddress.ip_address(response.text.strip()))
        if len(_public_ip_cache) > 16:
            _public_ip_cache.clear()
        _public_ip_cache[local_address] = (time.monotonic(), value)
        return value
    except Exception:
        _public_ip_cache[local_address] = (time.monotonic(), None)
        return None

def run_cloudflare_speed_test() -> dict:
    started = time.perf_counter()
    with httpx.Client(timeout=15) as client:
        response = client.get("https://speed.cloudflare.com/__down?bytes=1000000")
        response.raise_for_status()
    seconds = max(time.perf_counter() - started, 0.001)
    return {"download_mbps": round((len(response.content) * 8 / seconds) / 1_000_000, 2), "duration_seconds": round(seconds, 2)}
