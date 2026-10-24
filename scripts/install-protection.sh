#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then
  printf 'Run: sudo bash scripts/install-protection.sh\n' >&2
  exit 1
fi
desktop_uid="${SUDO_UID:-${1:-}}"
if [[ ! "$desktop_uid" =~ ^[0-9]+$ ]] || [[ "$desktop_uid" -eq 0 ]]; then
  printf 'Supply the non-root desktop UID as the first argument.\n' >&2
  exit 1
fi
command -v nft >/dev/null
command -v nmcli >/dev/null
source_root="$(dirname "$(dirname "$(readlink -f "$0")")")"
install -d -m 0755 /usr/local/lib/northstar-vpn
install -o root -g root -m 0755 "$source_root/system/protection_service.py" /usr/local/lib/northstar-vpn/protection_service.py
/usr/bin/python3 -I /usr/local/lib/northstar-vpn/protection_service.py --uid "$desktop_uid" --check
unit="$(mktemp)"
trap 'rm -f "$unit"' EXIT
cat > "$unit" <<EOF
[Unit]
Description=Northstar VPN leak protection
After=dbus.service
Before=NetworkManager.service
Wants=NetworkManager.service

[Service]
Type=notify
NotifyAccess=main
ExecStart=/usr/bin/python3 -I /usr/local/lib/northstar-vpn/protection_service.py --uid $desktop_uid
Restart=always
RestartSec=1
RuntimeDirectory=northstar-vpn
StateDirectory=northstar-vpn
UMask=0077
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/run/northstar-vpn /var/lib/northstar-vpn
NoNewPrivileges=true
PrivateTmp=true
RestrictAddressFamilies=AF_UNIX AF_NETLINK AF_INET AF_INET6
CapabilityBoundingSet=CAP_NET_ADMIN CAP_CHOWN

[Install]
WantedBy=multi-user.target
EOF
install -o root -g root -m 0644 "$unit" /etc/systemd/system/northstar-vpn-protection.service
systemctl daemon-reload
systemctl enable northstar-vpn-protection.service
systemctl reset-failed northstar-vpn-protection.service || true
systemctl restart northstar-vpn-protection.service
printf 'Protection helper installed for UID %s.\n' "$desktop_uid"
