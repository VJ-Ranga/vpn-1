#!/usr/bin/env bash
set -u
ok=0
for command in python3 node; do command -v "$command" >/dev/null || { printf 'missing: %s\n' "$command"; ok=1; }; done
command -v nmcli >/dev/null && printf 'NetworkManager: available\n' || printf 'NetworkManager: unavailable (UI degraded mode)\n'
plugin=0
for path in \
  /usr/lib/NetworkManager/VPN/nm-openvpn-service.name \
  /usr/lib/NetworkManager/VPN/nm-openvpn-service \
  /usr/libexec/nm-openvpn-service \
  /usr/libexec/NetworkManager/VPN/nm-openvpn-service \
  /lib/NetworkManager/VPN/nm-openvpn-service.name \
  /lib/NetworkManager/VPN/nm-openvpn-service; do
  case "$path" in
    *.name) [ -f "$path" ] && plugin=1 ;;
    *) [ -x "$path" ] && plugin=1 ;;
  esac
done
[ "$plugin" -eq 1 ] && printf 'OpenVPN plugin: detected\n' || printf 'OpenVPN plugin: not detected\n'
python3 -c 'import keyring' 2>/dev/null && printf 'Secret Service client: available\n' || printf 'Secret Service client: install backend dependencies\n'
exit "$ok"
