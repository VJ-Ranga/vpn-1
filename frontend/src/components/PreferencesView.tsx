import { useEffect, useState } from "react";
import { Check, Monitor, Moon, Sun } from "lucide-react";
import type { Preferences, Protection } from "../types";

function Toggle({
  label,
  description,
  checked = false,
  disabled = false,
  change,
}: {
  label: string;
  description: string;
  checked?: boolean;
  disabled?: boolean;
  change?: () => void;
}) {
  return (
    <div className={`preference-row ${disabled ? "unavailable" : ""}`}>
      <div>
        <h3>{label}</h3>
        <p>{description}</p>
      </div>
      <button
        className="toggle"
        role="switch"
        aria-label={label}
        aria-checked={checked}
        disabled={disabled}
        onClick={change}
      >
        <span />
      </button>
    </div>
  );
}

export function PreferencesView({
  values,
  protection,
  save,
  saving,
}: {
  values: Preferences;
  protection: Protection;
  save: (values: Partial<Preferences>) => void;
  saving: boolean;
}) {
  const [tab, setTab] = useState("general");
  const [startup, setStartup] = useState(false);
  const [startupError, setStartupError] = useState("");
  useEffect(() => {
    window.desktop
      ?.getStartup()
      .then(setStartup)
      .catch(() => setStartupError("Could not read desktop startup settings."));
  }, []);
  return (
    <>
      <div className="page-heading">
        <h1>Settings</h1>
      </div>
      <div className="tabs" role="tablist" aria-label="Settings sections">
        <button
          role="tab"
          aria-selected={tab === "general"}
          onClick={() => setTab("general")}
        >
          General
        </button>
        <button
          role="tab"
          aria-selected={tab === "advanced"}
          onClick={() => setTab("advanced")}
        >
          Advanced
        </button>
        {saving && <span className="tab-count">Saving…</span>}
      </div>
      <div className="settings-content">
        {tab === "general" ? (
          <>
            <Toggle
              label="Startup"
              description="Open the desktop app when you sign in to Linux."
              checked={startup}
              disabled={!window.desktop}
              change={() => {
                window.desktop
                  ?.setStartup(!startup)
                  .then(setStartup)
                  .catch((error) => setStartupError(String(error)));
              }}
            />
            {startupError && <p className="inline-error">{startupError}</p>}
            <section className="protocol-section">
              <h2>Protocol</h2>
              <p className="setting-description">
                Select a protocol that balances your security and speed
                requirements.
              </p>
              <label className="protocol-option unavailable">
                <input type="radio" name="protocol" disabled />
                <span>
                  <strong>IKEv2</strong>
                  <small>
                    Requires a separate provider integration. Not available in
                    this release.
                  </small>
                </span>
              </label>
              <label className="protocol-option unavailable">
                <input type="radio" name="protocol" disabled />
                <span>
                  <strong>WireGuard®</strong>
                  <small>
                    Provider-generated WireGuard configurations are not
                    integrated yet.
                  </small>
                </span>
              </label>
              <label className="protocol-option">
                <input type="radio" name="protocol" checked readOnly />
                <span>
                  <strong>OpenVPN</strong>
                  <small>Secure Linux tunnels managed by NetworkManager.</small>
                </span>
              </label>
              <div
                className="transport-options"
                role="group"
                aria-label="OpenVPN transport"
              >
                {(["udp", "tcp"] as const).map((value) => (
                  <button
                    key={value}
                    disabled={saving}
                    aria-pressed={values.transport === value}
                    onClick={() => save({ transport: value })}
                  >
                    {values.transport === value && <Check size={13} />}
                    {value.toUpperCase()}
                  </button>
                ))}
              </div>
              <p className="transport-note">
                UDP favors speed. TCP can work better on restricted networks.
              </p>
            </section>
            <section className="theme-section">
              <h2>Theme Appearance</h2>
              <p className="setting-description">
                Choose a light or dark background, or follow your system.
              </p>
              <div className="theme-options">
                {(
                  [
                    { key: "light", label: "Light", Icon: Sun },
                    { key: "dark", label: "Dark", Icon: Moon },
                    { key: "system", label: "System", Icon: Monitor },
                  ] as const
                ).map(({ key, label, Icon }) => (
                  <button
                    aria-pressed={values.theme === key}
                    key={key}
                    disabled={saving}
                    onClick={() => save({ theme: key })}
                  >
                    <span className={`theme-preview ${key}`}>
                      <Icon size={20} />
                      <i />
                      <i />
                    </span>
                    {label}
                  </button>
                ))}
              </div>
            </section>
            <section className="version-section">
              <h3>Version</h3>
              <p>Northstar for Linux · 0.2.0</p>
              <small>
                Unofficial client for Namecheap FastVPN. Built for your Linux
                desktop.
              </small>
            </section>
          </>
        ) : (
          <>
            {!protection.available && (
              <div className="setup-notice">
                <strong>Install network protection</strong>
                <p>
                  One-time administrator setup is required for leak protection
                  and the kill switch.
                </p>
                <code>sudo bash scripts/install-protection.sh</code>
                <small>
                  Run from the project folder, then reopen this page.
                </small>
              </div>
            )}
            <Toggle
              label="Kill Switch"
              description="Block internet traffic outside the VPN, including after disconnect. Turn off to restore ordinary internet access."
              checked={values.kill_switch}
              disabled={saving}
              change={() => save({ kill_switch: !values.kill_switch })}
            />
            <Toggle
              label="Automatic reconnect"
              description="Reconnect to your last location if the tunnel drops while this app is running."
              checked={values.auto_reconnect}
              disabled={saving}
              change={() => save({ auto_reconnect: !values.auto_reconnect })}
            />
            <Toggle
              label="Auto-Protect"
              description="Automatically protect untrusted Wi-Fi networks. Planned for a future release."
              disabled
            />
            <Toggle
              label="Network detection notification"
              description="New-network detection is not integrated in this release."
              disabled
            />
            <Toggle
              label="Split tunneling"
              description="App and domain routing requires a separate Linux integration."
              disabled
            />
            <Toggle
              label="Ad Blocker"
              description="Provider ad-blocking DNS integration is not available yet."
              disabled
            />
            <Toggle
              label="Allow local network devices"
              description="Allow private-network access, such as printers, while protected. Off blocks local bypass when the kill switch is on."
              checked={values.allow_lan}
              disabled={saving}
              change={() => save({ allow_lan: !values.allow_lan })}
            />
            <Toggle
              label="IPv6 leak protection"
              description="Block public IPv6 traffic outside the VPN without disabling IPv6 permanently on Wi-Fi."
              checked={values.ipv6_protection}
              disabled={saving}
              change={() => save({ ipv6_protection: !values.ipv6_protection })}
            />
            <Toggle
              label="DNS leak protection"
              description="Block conventional DNS requests outside the VPN while connected."
              checked={values.dns_protection}
              disabled={saving}
              change={() => save({ dns_protection: !values.dns_protection })}
            />
            <Toggle
              label="DNS monitoring"
              description="DNS query inspection is not available in this release."
              disabled
            />
            <Toggle
              label="Traffic Optimizer"
              description="Per-app traffic prioritization is not available in this release."
              disabled
            />
          </>
        )}
      </div>
    </>
  );
}
