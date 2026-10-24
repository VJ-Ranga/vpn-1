import {
  ArrowDownToLine,
  ArrowUpFromLine,
  Check,
  ChevronDown,
  Globe2,
  LoaderCircle,
  MapPin,
  Network,
  ShieldAlert,
  ShieldCheck,
  Wifi,
} from "lucide-react";
import type { Preferences, Profile, Protection, Status } from "../types";
import { countryFlag, countryName } from "../countries";

export function bytes(value: number) {
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(2)} GB`;
  return `${(value / 1024 ** 2).toFixed(2)} MB`;
}

export function ConnectionPanel({
  status,
  selected,
  preferences,
  protection,
  busy,
  toggle,
  switchIp,
  showLocations,
  compact,
}: {
  status: Status;
  selected?: Profile;
  preferences: Preferences;
  protection: Protection;
  busy: boolean;
  toggle: () => void;
  switchIp: () => void;
  showLocations: () => void;
  compact: boolean;
}) {
  const connected = status.state === "connected";
  const country = connected ? status.country_code : selected?.country_code;
  const city = connected ? status.city : selected?.city;
  const seconds = status.duration_seconds || 0;
  const duration = [
    Math.floor(seconds / 3600),
    Math.floor(seconds / 60) % 60,
    seconds % 60,
  ]
    .map((v) => String(v).padStart(2, "0"))
    .join(":");
  return (
    <aside
      className={`connection-panel ${compact ? "compact-panel" : ""}`}
      aria-label="VPN connection"
    >
      <div className={`connection-hero ${connected ? "connected" : ""}`}>
        <svg className="world-dots" viewBox="0 0 600 360" aria-hidden="true">
          <defs>
            <pattern
              id="mapDots"
              width="8"
              height="8"
              patternUnits="userSpaceOnUse"
            >
              <circle cx="3" cy="3" r="2.1" fill="currentColor" />
            </pattern>
          </defs>
          <g fill="url(#mapDots)">
            <path d="M15 83 47 45 92 34 124 45 145 28 184 40 195 72 178 92 169 120 151 139 132 130 122 155 143 178 132 194 107 174 86 148 65 130 51 100Z" />
            <path d="m161 191 30-18 38 20 14 36-24 32-10 37-26 36-13-39-16-30-10-39Z" />
            <path d="m213 26 35-17 25 18-10 38-21 32-23-22Z" />
            <path d="m276 74 26-19 24 10 18-24 52-14 58 17 45 2 69 43-15 28-41 2-22 24-31 5-22 29-34 3-21-33-17 2-10-26-32-8-13 23-22-11-24 13-14-27Z" />
            <path d="m290 138 44-7 41 24 15 27-22 23-7 47-27 37-20-16-11-42-29-31-7-29Z" />
            <path d="m420 169 22 8 12 35 27 19-13 12-32-33Z" />
            <path d="m479 254 35-20 36 6 23 32-10 20-31-3-35 10-25-18Z" />
            <path d="m383 258 8-25 11 2-7 32Zm180 50 17-13 7 8-16 21Z" />
          </g>
        </svg>
        <div className="hero-status-icon">
          {busy ? (
            <LoaderCircle className="spin" size={43} />
          ) : connected ? (
            <span className="connected-check">
              <Check size={28} />
            </span>
          ) : (
            <Wifi size={43} strokeWidth={1.7} />
          )}
        </div>
        <h2>{busy ? "Connecting…" : connected ? "VPN Connected" : "Wi-Fi"}</h2>
        <p>
          {busy
            ? "Preparing your protected connection"
            : connected
              ? duration
              : "Your current network"}
        </p>
        <button
          className={`connection-button ${connected ? "disconnect" : ""}`}
          disabled={busy}
          onClick={toggle}
        >
          {busy ? "Please wait…" : connected ? "Disconnect" : "Connect VPN"}
        </button>
      </div>
      <div className="connection-details">
        <button className="selected-location" onClick={showLocations}>
          <span className="selected-flag">
            {country ? (
              countryFlag(country === "UK" ? "GB" : country)
            ) : (
              <MapPin size={23} />
            )}
          </span>
          <span>
            <strong>{country ? countryName(country) : "Best Available"}</strong>
            {city && <small>{city}</small>}
          </span>
          <ChevronDown size={18} />
        </button>
        <div className="public-address">
          <small>IP ADDRESS</small>
          <strong>
            {connected
              ? status.public_ip || "Checking public IP…"
              : "Not connected"}
          </strong>
          {connected && (
            <button className="text-button" onClick={switchIp} disabled={busy}>
              Switch IP
            </button>
          )}
        </div>
        <div className="connection-stats">
          <div>
            <ArrowDownToLine size={16} />
            <strong>{bytes(status.bytes_in || 0)}</strong>
            <small>DOWNLOAD</small>
          </div>
          <div>
            <ArrowUpFromLine size={16} />
            <strong>{bytes(status.bytes_out || 0)}</strong>
            <small>UPLOAD</small>
          </div>
          <div>
            <Network size={16} />
            <strong>OPENVPN</strong>
            <small>
              {(connected
                ? status.transport
                : preferences.transport
              )?.toUpperCase()}
            </small>
          </div>
        </div>
        <div
          className={`protection-indicator ${protection.available && protection.active && !protection.error ? "protected" : ""}`}
        >
          {protection.available && protection.active && !protection.error ? (
            <ShieldCheck size={16} />
          ) : (
            <ShieldAlert size={16} />
          )}
          <span>
            {protection.available
              ? protection.error
                ? "Protection needs attention"
                : protection.active
                  ? "Network protection active"
                  : "Protection ready"
              : "Protection setup required"}
          </span>
        </div>
        {connected && (
          <p className="tunnel-label">
            {status.interface || "Tunnel unavailable"} ·{" "}
            {status.vpn_ip || "Address unavailable"}
          </p>
        )}
        {!connected && (
          <p className="connection-hint">
            <Globe2 size={14} /> Choose a location, then connect.
          </p>
        )}
      </div>
    </aside>
  );
}
