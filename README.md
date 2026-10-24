# Northstar VPN for Linux

An independent Linux desktop client for Namecheap FastVPN OpenVPN profiles. The interface follows the Windows application's three-column layout: navigation, country/city locations, and a persistent connection panel. This is not an official Namecheap application.

## Implemented in stage 1

- Electron desktop window, system tray, compact window, desktop launcher, notifications, and optional sign-in startup.
- Searchable countries/cities, country/city favorites, TCP/UDP selection, measured TCP handshake latency, and best-reachable selection.
- OpenVPN connect/disconnect and same-city endpoint switching through NetworkManager.
- Real tunnel interface/address detection, source-bound public-IP checks, session-relative traffic counters, and reconnect while the backend is running.
- VPN-scoped IPv6 and conventional DNS protection, optional LAN exceptions, and a separate persistent kill switch.
- Light/dark/system themes, credentials in Linux Secret Service, local connection logs, diagnostics, and help/legal pages.

WireGuard, IKEv2, provider subscription data, server load, split tunneling, ad blocking, DNS monitoring, traffic optimization, and trusted-network Auto-Protect require separate integrations. Their controls are explicitly unavailable. Source `.ovpn` files remain read-only.

## Install dependencies

Linux Mint/Ubuntu with NetworkManager, systemd, nftables 1.0.9 or later, Python 3.11 or later, and Node.js 22 or later:

```bash
sudo apt install network-manager network-manager-openvpn network-manager-openvpn-gnome nftables python3-venv nodejs npm
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -e 'backend[test]'
npm install
npm --prefix frontend install
npm run build
```

If an existing virtual environment has no pip, use an installed pip to target it:

```bash
python3 -m pip --python backend/.venv install -e 'backend[test]'
```

Electron's first installation downloads its Linux runtime. For networks requiring proxy environment support:

```bash
ELECTRON_GET_USE_PROXY=1 node node_modules/electron/install.js
```

## Add your own VPN profiles

VPN profiles, account credentials, local settings, logs, screenshots, and development notes are not included in this repository.

Download OpenVPN profiles from your provider and place TCP profiles in `tcp/` and UDP profiles in `udp/` at the project root:

```bash
mkdir -p tcp udp
```

Keep the provider filenames, such as `NCVPN-DE-Frankfurt-TCP.ovpn` and `NCVPN-DE-Frankfurt-UDP.ovpn`. Alternatively, set `VPN_PROFILE_ROOT` to a directory containing your own `tcp/` and `udp/` folders before launching the app. Profiles and credentials remain local and are ignored by Git. Enter credentials through the Account screen; do not put them in source files.

## Install network protection

Run once from this directory as your normal desktop user:

```bash
sudo bash scripts/install-protection.sh
```

The installer copies a root-owned standard-library Python helper to `/usr/local/lib/northstar-vpn/`, installs `northstar-vpn-protection.service`, and authorizes only your desktop UID. If using `pkexec`, provide the desktop UID explicitly:

```bash
pkexec /bin/bash "$PWD/scripts/install-protection.sh" "$(id -u)"
```

The app itself does not run as root. The helper checks Unix-socket peer credentials and accepts only a narrow JSON protocol. It changes only the `inet northstar_vpn` nftables table. Docker, UFW, and unrelated firewall tables are not flushed. Check readiness in Settings or with:

```bash
systemctl status northstar-vpn-protection.service
```

IPv6 and DNS protection default on. Protected connections refuse activation if the helper is unavailable. Preparation permits IPv4 DNS temporarily to resolve VPN endpoints; once connected, conventional DNS outside the VPN is blocked. IPv6 internet traffic outside the tunnel is blocked without permanently disabling IPv6 on Wi-Fi. Loopback and network configuration traffic remain available.

## Launch desktop

```bash
bash scripts/install-desktop.sh
bash scripts/start-desktop.sh
```

The launcher also appears as **Northstar VPN** in your application menu. Enter your FastVPN connection credentials under **Account**, select a city and transport, then click **Connect VPN**. **Switch IP** reconnects to a different endpoint in the same city; the provider may still assign the same public exit IP.

Closing the window hides it to the tray. Use **Quit** to stop desktop controls and their owned backend. NetworkManager continues to own the VPN; the root helper continues to enforce its policy. A kill switch remains active until explicitly disabled. Automatic reconnect requires the desktop backend to remain running.

The desktop uses a dedicated loopback port and an unpredictable per-launch mutation token passed through an authenticated preload bootstrap. Passwords are not returned to the renderer or written to event logs. External navigation is restricted to allowlisted Namecheap HTTPS hosts. Renderer sandboxing and context isolation remain enabled.

## Kill-switch recovery

When enabled, the kill switch blocks ordinary IPv4 and IPv6 internet access while disconnected. Disable it in **Settings → Advanced** to restore ordinary internet access. Location probes may be blocked while disconnected; choose a specific city to reconnect.

For emergency manual recovery, stop the helper before removing its table so the daemon does not recreate it:

```bash
sudo systemctl stop northstar-vpn-protection.service
sudo nft destroy table inet northstar_vpn
```

This removes this application's protection. Other firewall rules remain in place. The root-owned policy persists in `/var/lib/northstar-vpn/protection.json`; restarting the service restores a saved kill switch. Disable the kill switch in the UI before normal removal if you do not want it restored.

## Browser development

```bash
VPN_UI_PORT=8766 backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8766
npm --prefix frontend run dev
```

Open `http://127.0.0.1:5173`. Without a desktop-supplied token, development mutations use the existing `X-CSRF-Token: local-ui` header. Host and Origin validation restrict access to the loopback development origins. Startup and tray controls are desktop-only.

## Verify

```bash
backend/.venv/bin/python -m pytest backend/tests -q -c backend/pyproject.toml
npm --prefix frontend test -- --run
npm run build
npm run test:desktop
npm run check:desktop
python3 -m compileall -q backend/app system
bash -n scripts/start-desktop.sh scripts/install-desktop.sh scripts/install-protection.sh
```

Desktop integration smoke test, run from your normal desktop session with the app closed:

```bash
bash scripts/start-desktop.sh --smoke-test
```

Set `VPN_SMOKE_OUTPUT=/absolute/path/desktop.png` to save a screenshot and adjacent JSON verification result. In a restricted command harness, Chromium child processes may be blocked even though desktop launching works. Start through the normal application menu or a user systemd unit; do not disable Electron's sandbox.

Settings are stored in `~/.config/northstar-vpn/settings.json`; Electron data and backend logs use its user-data directory (normally `~/.config/Northstar VPN` on Linux). Credentials remain in Secret Service. Public-IP queries contact ipify; speed tests contact Cloudflare; latency checks contact VPN servers.

Desktop favorites and activity history persist locally in `desktop-state.json` in the Electron user-data directory, independently of the loopback port. These files are not part of the repository.
