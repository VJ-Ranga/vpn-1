from dataclasses import dataclass
from pathlib import Path
import hashlib
import re

@dataclass(frozen=True)
class Server:
    host: str
    port: int

@dataclass(frozen=True)
class Profile:
    id: str
    path: Path
    transport: str
    country_code: str
    city: str
    virtual: bool
    servers: tuple[Server, ...] = ()

def parse_remote_servers(content: str) -> list[dict[str, int | str]]:
    servers = []
    for line in content.splitlines():
        match = re.match(r"^\s*remote\s+(\S+)\s+(\d+)(?:\s|$)", line)
        if match:
            servers.append({"host": match.group(1), "port": int(match.group(2))})
    return servers

def parse_profile_name(filename: str, transport: str, path: Path | None = None, content: str = "") -> Profile:
    pattern = rf"^NCVPN-([A-Z]{{2}})-(.+?)(?: - Virtual)?-{transport.upper()}\.ovpn$"
    match = re.match(pattern, filename)
    if not match:
        raise ValueError(f"unsupported profile name: {filename}")
    city = match.group(2).strip()
    virtual = " - Virtual-" in filename
    relative = str(path or filename)
    profile_id = hashlib.sha256(relative.encode()).hexdigest()[:16]
    servers = tuple(Server(server["host"], server["port"]) for server in parse_remote_servers(content))
    return Profile(profile_id, path or Path(filename), transport, match.group(1), city, virtual, servers)

class ProfileCatalog:
    def __init__(self, root: Path):
        self.root = root
        self._profiles: dict[str, Profile] = {}

    def scan(self) -> list[Profile]:
        found = []
        for transport in ("tcp", "udp"):
            folder = self.root / transport
            if not folder.is_dir():
                continue
            for path in folder.glob("*.ovpn"):
                try:
                    relative = path.relative_to(self.root)
                    parsed = parse_profile_name(path.name, transport, relative, path.read_text())
                    p = Profile(parsed.id, path, parsed.transport, parsed.country_code, parsed.city, parsed.virtual, parsed.servers)
                except ValueError:
                    continue
                found.append(p)
        self._profiles = {p.id: p for p in found}
        return self.list()

    def list(self) -> list[Profile]:
        return sorted(self._profiles.values(), key=lambda p: (p.city.lower(), p.transport))

    def get(self, profile_id: str) -> Profile:
        return self._profiles[profile_id]
