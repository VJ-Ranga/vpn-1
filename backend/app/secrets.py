from dataclasses import dataclass
import keyring

SERVICE = "openvpn-local-ui"

@dataclass
class Credentials:
    username: str
    password: str

class CredentialStore:
    def __init__(self, backend=None):
        self.backend = backend or keyring

    def get(self) -> Credentials | None:
        username = self.backend.get_password(SERVICE, "username")
        password = self.backend.get_password(SERVICE, "password")
        return Credentials(username, password) if username and password else None

    def save(self, credentials: Credentials) -> None:
        if not credentials.username.strip() or not credentials.password:
            raise ValueError("username and password are required")
        self.backend.set_password(SERVICE, "username", credentials.username.strip())
        self.backend.set_password(SERVICE, "password", credentials.password)

    def clear(self) -> None:
        for name in ("username", "password"):
            try:
                self.backend.delete_password(SERVICE, name)
            except Exception:
                pass
