# Windows installer

The unsigned personal-use x64 installer is stored in `windows/` as two ordinary Git files, each below GitHub's 100 MiB limit. Git LFS is **not** required; the repository's LFS budget was exhausted.

Clone the repository or download/extract its ZIP, then double-click **`windows/Install.cmd`**. Keep `Install.ps1`, both `.exe.part1` / `.exe.part2` files, and `SHA256SUMS.txt` together. The script joins the parts into `Northstar-VPN-0.2.1-Setup-x64.exe`, verifies its SHA-256 checksum, and launches Setup. To assemble without installing, run `powershell -NoProfile -File windows/Install.ps1 -BuildOnly` from this directory.

Run Setup and approve UAC, then launch Northstar VPN from the Desktop or Start Menu shortcut. Python and Node.js are bundled, and the helper service starts automatically. Before replacing an old development setup, disconnect its VPN and close its manually launched helper to free port 8799.

Credentials and local settings are not bundled. IPv6 blocking is mandatory while connected; DNS protection and the IPv4 kill switch are still unavailable. The build is unsigned and may trigger SmartScreen. Licensing/redistribution review is still required before wider distribution.
