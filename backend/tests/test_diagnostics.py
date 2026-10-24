from app.diagnostics import Counters, calculate_rates

def test_calculate_rates_uses_byte_delta():
    r = calculate_rates(Counters(1000, 2000), Counters(3000, 5000), 2)
    assert (r.download_bps, r.upload_bps) == (1000, 1500)

def test_negative_counter_delta_returns_zero():
    r = calculate_rates(Counters(3000, 5000), Counters(1000, 2000), 2)
    assert (r.download_bps, r.upload_bps) == (0, 0)


def test_public_ip_binds_to_tunnel_address_and_caches_per_source(monkeypatch):
    from app import diagnostics
    calls = []
    class Response:
        text = "203.0.113.4"
        def raise_for_status(self):
            pass
    class Client:
        def __init__(self, **kwargs):
            calls.append(kwargs)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, url):
            return Response()
    monkeypatch.setattr(diagnostics.httpx, "Client", Client)
    monkeypatch.setattr(diagnostics.httpx, "HTTPTransport", lambda **kwargs: kwargs)
    monkeypatch.setattr(diagnostics, "_public_ip_cache", {})
    assert diagnostics.get_public_ip("10.8.0.2") == "203.0.113.4"
    assert diagnostics.get_public_ip("10.8.0.2") == "203.0.113.4"
    diagnostics.get_public_ip("10.8.0.3")
    assert len(calls) == 2
    assert calls[0]["transport"]["local_address"] == "10.8.0.2"
