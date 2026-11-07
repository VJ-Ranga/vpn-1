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

## Windows development (Stage 1)

### Local Windows installer (preview)

Build an unsigned x64 setup executable with `npm run dist:windows`. The build machine needs the development dependencies plus `pyinstaller` and `pywin32` in `backend/.venv`; the installed application does **not** need Python, Node.js, or a terminal. Build artifacts remain ignored under `release/`. The build downloads official FastVPN profiles (not local profiles/credentials) and an Authenticode-verified official OpenVPN MSI.

The setup executable installs under Program Files, creates desktop/Start Menu shortcuts, installs OpenVPN if missing, and registers the automatic `NorthstarVPNHelper` Windows service. Setup requires UAC once; launch the desktop normally from its shortcut afterward. First disconnect and close the development helper so it does not occupy port 8799. Credentials stay in the current user's Windows Credential Manager and are not bundled. The installing Windows account is the sole enrolled account; installing with another administrator's credentials does not enroll a standard-user account.

The preview uses an ACL-restricted ProgramData token and authenticates the service with a fresh HMAC challenge on the same socket before sending credentials. Same-account malware can still read that token. This is not a signed production release; SmartScreen warnings are expected. Service installation and a real connection/disconnect have been verified on the development Windows x64 machine, including IPv6 blocking, tunnel address, routes, exit IP and counters. A clean-machine installation, reboot, upgrades and full uninstall still need separate testing. Do not redistribute before deciding the project's license and reviewing third-party/profile redistribution terms.

Uninstall through Windows Installed Apps. The uninstaller stops/removes the Northstar service and IPv6 rule, but leaves shared OpenVPN and per-user credentials/preferences intact.

Install Git, Node.js 22 or later, Python 3.11 or later, and OpenVPN Community. Then:

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -e "backend[test]"
npm ci
npm --prefix frontend ci
npm run build
```

Download the official FastVPN OpenVPN profiles from `https://vpn.ncapi.io/groupedServerList.zip` (or from `https://account.fastvpn.com`) and place the extracted `tcp/` and `udp/` folders in the project root. Profile files are ignored by Git.

Start the helper in an **elevated** PowerShell window. The script refuses to run otherwise, generates a strong per-user helper token in `%LOCALAPPDATA%\northstar-vpn\helper.token`, and binds only to loopback:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-windows-helper.ps1
```

Start the desktop in a **normal, non-elevated** PowerShell window. It refuses to run elevated. It reads the same helper token automatically:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-desktop.ps1
```

Enter FastVPN credentials only in the app's Account panel. They are stored in the Windows Credential Manager through the Python keyring backend; they are never written to the repository.

### Health output on Windows

`/api/health` reports `platform: "windows"`, `vpn_backend: "openvpn-helper"`, `reachable` (helper answered), `helper.available`, `openvpn_exe`, and `protection_available: false`. `network_manager` is `false` and `openvpn_plugin` is retained only for frontend compatibility; Windows does not use NetworkManager. The service uses `reachable` to detect a lost helper.

### Helper security model and remaining limitations

Before any profile reaches OpenVPN, the helper parses it and rebuilds a minimal config from a strict allowlist. Script, plugin, external file, management, server-mode, proxy, compression, and unknown directives are rejected. The helper supplies `remote`, credentials, logging, and status paths itself, validates endpoints and ports, and runs OpenVPN with `--script-security 0`, `--route-method ipapi`, and `--ip-win32 ipapi`.

The helper requires a token of at least 32 characters, compares it in constant time, rejects non-dict requests, checks that peers are loopback, and uses `SO_EXCLUSIVEADDRUSE` on Windows. Credentials and generated configs live in an ACL-restricted per-run directory under `%ProgramData%\NorthstarVPN\runs` and are deleted after disconnect. Profiles are opened only from the configured root; reparse points, hardlinks, non-`.ovpn` files, and files over 1 MiB are rejected.

Remaining Stage 1 limitations:

- The helper still runs from a user-controlled checkout and is launched from an elevated interactive shell. A user who can replace `windows_helper.py`, `openvpn.exe`, or the Python interpreter can influence the elevated process. Stage 3 moves it to an admin-owned service under `C:\Program Files`.
- The desktop and helper communicate over authenticated loopback TCP. A same-user process that can read the token file can also drive the helper. Stage 3 should use a named pipe with a restrictive DACL and client PID/SID verification.
- Profile root files are user-writable, so a malicious local profile is still accepted if it passes the allowlist. The allowlist prevents code execution but does not make the profile trustworthy.
- Windows connections now require a verified outbound IPv6 firewall block before OpenVPN starts. This blocks **all IPv6, including LAN traffic**, on every interface; it does not tunnel IPv6. DNS protection and the IPv4 kill switch remain **unavailable**. A connected tunnel is not full leak protection.

### Windows IPv6 guard and recovery

The helper applies the fixed `NorthstarVPN-Block-IPv6` rule before connecting. Windows Firewall must be enabled on all profiles and local rules must be allowed. If the block cannot be verified, the helper refuses to connect. The rule survives a helper crash and stays enabled during reconnects. **Explicit Disconnect removes it**, even if OpenVPN has already stopped. Adapter IPv6 bindings and unrelated firewall rules are not changed.

If the helper cannot be restarted, first stop/disconnect OpenVPN, then run this recovery command in an elevated PowerShell window to restore ordinary IPv6:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/windows-ipv6-guard.ps1 -Action Disable
```

Do not remove the rule while relying on the VPN. It is intentionally persistent on crashes; it is not an IPv4 kill switch. The helper uses a private Windows exit event for graceful OpenVPN shutdown so routes can be removed before releasing the block. Tunnel IPv4 reporting comes from the adapter's assigned address, and counters come from OpenVPN statistics (with a Windows adapter fallback), rather than parsing requested addresses from logs.

Desktop favorites and activity history persist locally in `desktop-state.json` in the Electron user-data directory, independently of the loopback port. These files are not part of the repository.
