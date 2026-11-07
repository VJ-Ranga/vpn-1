import hashlib
import hmac
import importlib.util
import json
import threading
from pathlib import Path
from types import SimpleNamespace

SPEC = importlib.util.spec_from_file_location(
    "helper_protocol", Path(__file__).resolve().parents[2] / "system" / "windows_helper.py"
)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


class Client:
    def __init__(self, requests):
        self.data = b"".join(json.dumps(request).encode() + b"\n" for request in requests)
        self.responses = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def getpeername(self):
        return ("127.0.0.1", 12345)

    def settimeout(self, value):
        pass

    def recv(self, size):
        data, self.data = self.data[:size], self.data[size:]
        return data

    def sendall(self, data):
        self.responses.append(json.loads(data))


def test_server_proof_and_authenticated_action_share_one_socket():
    token, nonce = "x" * 64, "a" * 64
    client = Client([{"action": "challenge", "nonce": nonce}, {"action": "health", "token": token}])
    state = SimpleNamespace(health=lambda: {"ok": True, "openvpn": True})
    helper.client_worker(client, state, token, threading.BoundedSemaphore(4))
    assert client.responses == [
        {"ok": True, "proof": hmac.new(token.encode(), b"northstar-helper-v1:" + nonce.encode(), hashlib.sha256).hexdigest()},
        {"ok": True, "openvpn": True},
    ]


def test_proof_does_not_authorize_the_following_action():
    client = Client([{"action": "challenge", "nonce": "a" * 64}, {"action": "disconnect", "token": "wrong"}])
    helper.client_worker(client, SimpleNamespace(), "x" * 64, threading.BoundedSemaphore(4))
    assert client.responses[-1] == {"ok": False, "error": "unauthorized"}


def test_invalid_challenge_is_rejected():
    client = Client([{"action": "challenge", "nonce": "bad"}])
    helper.client_worker(client, SimpleNamespace(), "x" * 64, threading.BoundedSemaphore(4))
    assert client.responses == []


def test_development_single_request_protocol_still_works():
    client = Client([{"action": "health", "token": "x" * 64}])
    helper.client_worker(client, SimpleNamespace(health=lambda: {"ok": True}), "x" * 64, threading.BoundedSemaphore(4))
    assert client.responses == [{"ok": True}]
