#!/usr/bin/env bash
set -euo pipefail
root="$(dirname "$(dirname "$(readlink -f "$0")")")"
destination="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
install -d "$destination"
node -e 'const fs=require("node:fs"); const path=require("node:path"); const root=process.argv[1]; const {desktopEntry}=require(path.join(root,"desktop/policy.cjs")); fs.writeFileSync(process.argv[2],desktopEntry(root).replace(" --background\n","\n"));' "$root" "$destination/northstar-vpn.desktop"
chmod 0755 "$root/scripts/start-desktop.sh" "$destination/northstar-vpn.desktop"
printf 'Northstar VPN launcher installed: %s\n' "$destination/northstar-vpn.desktop"
