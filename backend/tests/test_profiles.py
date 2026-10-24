from app.profiles import ProfileCatalog, parse_profile_name, parse_remote_servers


def test_parse_remote_servers_extracts_every_remote_line():
    content = "client\nremote cmb-c01.vpn.wlvpn.com 1194\nremote cmb-c02.vpn.wlvpn.com 443 tcp\n"

    assert parse_remote_servers(content) == [
        {"host": "cmb-c01.vpn.wlvpn.com", "port": 1194},
        {"host": "cmb-c02.vpn.wlvpn.com", "port": 443},
    ]


def test_parse_remote_servers_ignores_comments_and_malformed_lines():
    content = "# remote hidden.example 1194\nremote valid.example 1194\nremote missing-port\n"

    assert parse_remote_servers(content) == [{"host": "valid.example", "port": 1194}]

def test_parse_regular_tcp_profile():
    p = parse_profile_name("NCVPN-DE-Frankfurt-TCP.ovpn", "tcp")
    assert (p.country_code, p.city, p.transport, p.virtual) == ("DE", "Frankfurt", "tcp", False)

def test_parse_virtual_udp_profile():
    p = parse_profile_name("NCVPN-AD-Andorra la Vella - Virtual-UDP.ovpn", "udp")
    assert (p.city, p.virtual, p.transport) == ("Andorra la Vella", True, "udp")

def test_catalog_scans_both_directories(tmp_path):
    for transport in ("tcp", "udp"):
        (tmp_path / transport).mkdir()
        (tmp_path / transport / f"NCVPN-US-Chicago-{transport.upper()}.ovpn").write_text(
            f"client\nremote chicago-{transport}.example 1194\n"
        )
    assert len(ProfileCatalog(tmp_path).scan()) == 2


def test_catalog_includes_profile_servers(tmp_path):
    folder = tmp_path / "udp"
    folder.mkdir()
    (folder / "NCVPN-US-Chicago-UDP.ovpn").write_text(
        "remote cmb-c01.vpn.wlvpn.com 1194\nremote cmb-c02.vpn.wlvpn.com 443\n"
    )

    profile = ProfileCatalog(tmp_path).scan()[0]

    assert [(server.host, server.port) for server in profile.servers] == [
        ("cmb-c01.vpn.wlvpn.com", 1194),
        ("cmb-c02.vpn.wlvpn.com", 443),
    ]


def test_profile_ids_are_stable_and_catalog_refresh_replaces_removed_profiles(tmp_path):
    folder = tmp_path / "udp"
    folder.mkdir()
    path = folder / "NCVPN-US-Chicago-UDP.ovpn"
    path.write_text("client\n")
    catalog = ProfileCatalog(tmp_path)
    first = catalog.scan()[0]
    path.unlink()

    assert catalog.scan() == []
    assert first.id == parse_profile_name(path.name, "udp", path.relative_to(tmp_path)).id
