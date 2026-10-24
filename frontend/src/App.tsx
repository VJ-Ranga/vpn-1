import { useCallback, useEffect, useRef, useState } from "react";
import {
  Bell,
  CircleHelp,
  FileText,
  Globe2,
  MessageSquare,
  Settings,
  Shield,
  UserRound,
  X,
  Download,
  CircleCheck,
} from "lucide-react";
import { api } from "./api";
import type { Preferences, Profile, Protection, Status } from "./types";
import { countryName } from "./countries";
import { SettingsPanel } from "./components/SettingsPanel";
import { LocationList } from "./components/LocationList";
import { ConnectionPanel, bytes } from "./components/ConnectionPanel";
import { PreferencesView } from "./components/PreferencesView";
import "./styles.css";

const emptyStatus: Status = {
  state: "disconnected",
  duration_seconds: 0,
  bytes_in: 0,
  bytes_out: 0,
  download_bps: 0,
  upload_bps: 0,
};
const defaults: Preferences = {
  transport: "udp",
  theme: "light",
  ipv6_protection: true,
  dns_protection: true,
  kill_switch: false,
  allow_lan: false,
  auto_reconnect: false,
};
const navigation = [
  { label: "Locations", Icon: Globe2 },
  { label: "Settings", Icon: Settings },
  { label: "Account", Icon: UserRound },
  { label: "Notifications", Icon: Bell },
  { label: "Log Details", Icon: FileText },
  { label: "Get Help", Icon: MessageSquare },
  { label: "Legal Information", Icon: CircleHelp },
];
function saved<T>(key: string, fallback: T): T {
  try {
    return (window.desktop?.storage.read(key) as T | null) ?? JSON.parse(localStorage.getItem(key) || "null") ?? fallback;
  } catch {
    return fallback;
  }
}

export default function App() {
  const [page, setPage] = useState("Locations");
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [status, setStatus] = useState<Status>(emptyStatus);
  const [preferences, setPreferences] = useState<Preferences>(defaults);
  const [protection, setProtection] = useState<Protection>({
    available: false,
    active: false,
  });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedEndpoint, setSelectedEndpoint] = useState('');
  const [favorites, setFavorites] = useState<string[]>(() =>
    saved("vpn-favorites", []),
  );
  const [events, setEvents] = useState<string[]>(() => saved("vpn-events", []));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [measuring, setMeasuring] = useState(false);
  const [latencies, setLatencies] = useState<Record<string, number | null>>({});
  const [speed, setSpeed] = useState("");
  const acting = useRef(false);
  const compact =
    window.desktop?.compact ||
    new URLSearchParams(window.location.search).has("compact");
  const record = useCallback((message: string) => {
    const safe = message.replace(
      /(password|token|secret|authorization)[^\s:=]*[\s:=]+[^\s]+/gi,
      "$1 [redacted]",
    );
    setEvents((previous) => {
      if (previous[0]?.endsWith(safe)) return previous;
      const next = [
        `${new Date().toLocaleTimeString()} · ${safe}`,
        ...previous,
      ].slice(0, 80);
      localStorage.setItem("vpn-events", JSON.stringify(next));
      void window.desktop?.storage.write('vpn-events', next).catch(() => setError('Could not save local activity history.'));
      return next;
    });
  }, []);
  const updateStatus = useCallback((value: Status) => {
    setStatus({ ...emptyStatus, ...value });
    if (value.protection) setProtection(value.protection);
  }, []);
  useEffect(() => {
    let disposed = false;
    void api
      .profiles()
      .then((data) => {
        if (!disposed) setProfiles(data.profiles);
      })
      .catch((err) => {
        if (!disposed) setError(err.message);
      });
    void api
      .settings()
      .then((data) => {
        if (!disposed) {
          setPreferences({ ...defaults, ...data.settings });
          setProtection(data.protection);
        }
      })
      .catch((err) => {
        if (!disposed) setError(err.message);
      });
    let polling = false;
    const poll = async () => {
      if (acting.current || polling) return;
      polling = true;
      try {
        const current = await api.status();
        if (!disposed && !acting.current) updateStatus(current);
      } catch (err) {
        if (!disposed) {
          record((err as Error).message);
        }
      } finally {
        polling = false;
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 4000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [record, updateStatus]);
  useEffect(() => {
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    const apply = () => {
      document.documentElement.dataset.theme =
        preferences.theme === "system"
          ? media?.matches
            ? "dark"
            : "light"
          : preferences.theme;
    };
    apply();
    media?.addEventListener("change", apply);
    return () => media?.removeEventListener("change", apply);
  }, [preferences.theme]);
  const selected = profiles.find((profile) => profile.id === selectedId);
  const visibleProfiles = profiles.filter(
    (profile) => profile.transport === preferences.transport,
  );
  const select = (id: string) => {
    setSelectedId(id);
    setSelectedEndpoint('');
    setError("");
  };
  const changePreferences = async (values: Partial<Preferences>) => {
    if (saving) return;
    setSaving(true);
    setError("");
    try {
      const next = await api.saveSettings(values);
      setPreferences(next.settings);
      setProtection(next.protection);
      if (values.transport) setSelectedId(null);
      record("Settings updated");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };
  const action = useCallback(
    async (kind: "connect" | "disconnect" | "switch" | "best", id?: string, endpoint?: string) => {
      if (acting.current) return;
      acting.current = true;
      setBusy(true);
      setError("");
      try {
        const next =
          kind === "disconnect"
            ? await api.disconnect()
            : kind === "switch"
              ? await api.switchIp()
              : kind === "best" || !id
                ? await api.best()
                : await api.connect(id, endpoint);
        updateStatus(next);
        if (next.state === "error")
          throw new Error(next.error || "Connection failed");
        const message =
          next.state === "connected"
            ? `Connected to ${next.city || "VPN"}`
            : "Disconnected";
        record(message);
        window.desktop?.notify(message);
      } catch (err) {
        const message = (err as Error).message;
        setError(message);
        record(message);
      } finally {
        acting.current = false;
        setBusy(false);
      }
    },
    [record, updateStatus],
  );
  useEffect(() => {
    window.desktop?.updateTray({
      connected: status.state === "connected",
      city: status.city || "",
      favorites: profiles
        .filter(
          (profile) =>
            profile.transport === preferences.transport &&
            (favorites.includes(profile.id) ||
              favorites.includes(`country:${profile.country_code}`)),
        )
        .map((profile) => ({
          id: profile.id,
          label: `${countryName(profile.country_code)} — ${profile.city}`,
        })),
    });
  }, [profiles, favorites, status.state, status.city, preferences.transport]);
  useEffect(
    () =>
      window.desktop?.onCommand((command) => {
        if (command === "disconnect") void action("disconnect");
        else if (command === "best") void action("best");
        else if (command.startsWith("connect:"))
          void action("connect", command.slice(8));
        else if (navigation.some((item) => item.label === command))
          setPage(command);
      }),
    [action],
  );
  const toggleFavorite = (key: string) =>
    setFavorites((previous) => {
      const next = previous.includes(key)
        ? previous.filter((value) => value !== key)
        : [...previous, key];
      localStorage.setItem("vpn-favorites", JSON.stringify(next));
      void window.desktop?.storage.write('vpn-favorites', next).catch(() => setError('Could not save favorite locations.'));
      return next;
    });
  const measure = async () => {
    if (measuring) return;
    setMeasuring(true);
    setError("");
    try {
      setLatencies(
        (await api.latencies(visibleProfiles.map((profile) => profile.id)))
          .latencies,
      );
      record("Location latency measurement completed");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setMeasuring(false);
    }
  };
  const refresh = async () => {
    try {
      setProfiles((await api.refresh()).profiles);
      const data = await api.settings();
      setProtection(data.protection);
      setError("");
    } catch (err) {
      setError((err as Error).message);
    }
  };
  const speedTest = async () => {
    setSpeed("Testing…");
    try {
      const value = await api.speed();
      setSpeed(`${value.download_mbps} Mbps download`);
    } catch (err) {
      setSpeed((err as Error).message);
    }
  };
  const downloadLogs = () => {
    const url = URL.createObjectURL(
      new Blob([events.join("\n")], { type: "text/plain" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "northstar-vpn-log.txt";
    link.click();
    URL.revokeObjectURL(url);
  };
  return (
    <main className={`desktop-app ${compact ? "compact" : ""}`}>
      {!compact && (
        <nav className="sidebar" aria-label="Main navigation">
          <div className="app-brand">
            <Shield size={22} />
            <span>
              Northstar<small>FASTVPN FOR LINUX</small>
            </span>
          </div>
          <span className="nav-caption">GENERAL</span>
          {navigation.map(({ label, Icon }, index) => (
            <div key={label}>
              {index === 5 && (
                <span className="nav-caption about-caption">ABOUT US</span>
              )}
              <button
                className={`nav-item ${page === label ? "active" : ""}`}
                onClick={() => {
                  setPage(label);
                  setError("");
                }}
              >
                <Icon size={17} />
                {label}
              </button>
            </div>
          ))}
          <div className="sidebar-bottom">
            <Shield size={15} />
            <span>
              Independent Linux client
              <small>Powered by your FastVPN subscription</small>
            </span>
          </div>
        </nav>
      )}
      {!compact && (
        <section className="workspace" aria-label={page}>
          {error && (
            <div className="error-banner" role="alert">
              <span>{error}</span>
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={17} />
              </button>
            </div>
          )}
          {page === "Locations" && (
            <LocationList
              profiles={visibleProfiles}
              status={status}
              selected={selectedId}
              selectedEndpoint={selectedEndpoint}
              setEndpoint={setSelectedEndpoint}
              favorites={favorites}
              toggleFavorite={toggleFavorite}
              select={select}
              latencies={latencies}
              measure={() => void measure()}
              measuring={measuring}
              refresh={() => void refresh()}
            />
          )}
          {page === "Settings" && (
            <PreferencesView
              values={preferences}
              protection={protection}
              save={(values) => void changePreferences(values)}
              saving={saving}
            />
          )}
          {page === "Account" && (
            <>
              <div className="page-heading">
                <h1>Account</h1>
              </div>
              <div className="content-page">
                <h2>Your FastVPN connection</h2>
                <p className="setting-description">
                  Use the VPN credentials supplied with your Namecheap
                  subscription.
                </p>
                <SettingsPanel />
                <div className="info-block">
                  <h3>Subscription</h3>
                  <p>
                    Subscription details require provider account integration.
                    Manage your plan in your Namecheap account.
                  </p>
                  <a
                    href="https://www.namecheap.com/myaccount/login/"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Manage subscription
                  </a>
                </div>
              </div>
            </>
          )}
          {page === "Notifications" && (
            <>
              <div className="page-heading">
                <h1>Notifications</h1>
              </div>
              <div className="content-page">
                <div className="info-block">
                  <Shield size={23} />
                  <h2>
                    {protection.available
                      ? "Network protection is ready"
                      : "Finish setting up protection"}
                  </h2>
                  <p>
                    {protection.available
                      ? "Manage your IPv6, DNS, and kill-switch preferences in Advanced settings."
                      : "Install the privileged helper to enable VPN-scoped IPv6 and DNS protection."}
                  </p>
                  <button
                    className="outline-button"
                    onClick={() => setPage("Settings")}
                  >
                    Open settings
                  </button>
                </div>
                {events.map((event, index) => (
                  <div className="notification-row" key={`${index}-${event}`}>
                    <Bell size={17} />
                    <p>{event}</p>
                  </div>
                ))}
              </div>
            </>
          )}
          {page === "Log Details" && (
            <>
              <div className="page-heading">
                <h1>Log Details</h1>
                <button className="text-button" onClick={downloadLogs}>
                  <Download size={14} />
                  Export logs
                </button>
              </div>
              <div className="content-page">
                <h2>Data Consumption</h2>
                <div className="consumption">
                  <div>
                    <small>DOWNLOAD</small>
                    <strong>{bytes(status.bytes_in)}</strong>
                  </div>
                  <div>
                    <small>UPLOAD</small>
                    <strong>{bytes(status.bytes_out)}</strong>
                  </div>
                </div>
                <p className="setting-description">
                  Session tunnel counters. Activity records stay on this device.
                </p>
                <button
                  className="outline-button"
                  onClick={() => void speedTest()}
                >
                  Run Cloudflare speed test
                </button>
                {speed && <p>{speed}</p>}
                <dl className="diagnostic-details">
                  <dt>Tunnel</dt>
                  <dd>{status.interface || "Not connected"}</dd>
                  <dt>Tunnel IP</dt>
                  <dd>{status.vpn_ip || "—"}</dd>
                  <dt>VPN endpoint</dt>
                  <dd>{status.remote_endpoint || "—"}</dd>
                </dl>
                <div className="logs-heading">
                  <h2>Connection activity</h2>
                  <button
                    className="text-button"
                    onClick={() => {
                      setEvents([]);
                      localStorage.removeItem("vpn-events");
                      void window.desktop?.storage.write('vpn-events', []).catch(() => setError('Could not clear local activity history.'));
                    }}
                  >
                    Clear log
                  </button>
                </div>
                {!events.length && (
                  <p className="setting-description">
                    Connection events will appear here.
                  </p>
                )}
                {events.map((event, index) => (
                  <p className="log-line" key={`${index}-${event}`}>
                    {event}
                  </p>
                ))}
              </div>
            </>
          )}
          {page === "Get Help" && (
            <>
              <div className="page-heading">
                <h1>Get Help</h1>
              </div>
              <div className="content-page">
                <h2>How can we help?</h2>
                <div className="info-block">
                  <h3>Network protection setup</h3>
                  <p>
                    Run this command from your project folder. Administrator
                    authorization is required once.
                  </p>
                  <code>sudo bash scripts/install-protection.sh</code>
                  <button
                    className="outline-button"
                    onClick={() => void refresh()}
                  >
                    Check setup again
                  </button>
                </div>
                <a
                  className="help-link"
                  href="https://www.namecheap.com/support/knowledgebase/category/2265/fastvpn/"
                  target="_blank"
                  rel="noreferrer"
                >
                  FastVPN knowledgebase <ChevronIcon />
                </a>
                <a
                  className="help-link"
                  href="https://www.namecheap.com/help-center/live-chat/"
                  target="_blank"
                  rel="noreferrer"
                >
                  Namecheap live chat <ChevronIcon />
                </a>
                <p className="setting-description">
                  This independent Linux client is not an official Namecheap
                  application. Provider support may not cover this client.
                </p>
              </div>
            </>
          )}
          {page === "Legal Information" && (
            <>
              <div className="page-heading">
                <h1>Legal Information</h1>
              </div>
              <div className="content-page">
                <h2>Northstar for Linux</h2>
                <p>
                  Independent Linux client for your FastVPN subscription. Not
                  affiliated with or endorsed by Namecheap.
                </p>
                <p>
                  FastVPN and Namecheap names belong to their respective owners.
                  WireGuard is a registered trademark of Jason A. Donenfeld.
                </p>
                <a
                  className="help-link"
                  href="https://www.namecheap.com/legal/general/privacy-policy/"
                  target="_blank"
                  rel="noreferrer"
                >
                  Provider privacy policy <ChevronIcon />
                </a>
                <a
                  className="help-link"
                  href="https://www.namecheap.com/legal/"
                  target="_blank"
                  rel="noreferrer"
                >
                  Provider terms <ChevronIcon />
                </a>
                <h3>Local data</h3>
                <p>
                  Connection credentials stay in Linux Secret Service.
                  Preferences and connection events stay on your device.
                  Public-IP checks use ipify; speed tests use Cloudflare; ping
                  checks contact VPN servers.
                </p>
              </div>
            </>
          )}
        </section>
      )}
      <ConnectionPanel
        status={status}
        selected={selected}
        preferences={preferences}
        protection={protection}
        busy={busy}
        compact={compact}
        toggle={() =>
          void action(
            status.state === "connected"
              ? "disconnect"
              : selected
                ? "connect"
                : "best",
            selected?.id,
            selectedEndpoint || undefined,
          )
        }
        switchIp={() => void action("switch")}
        showLocations={() => setPage("Locations")}
      />
      {compact && error && (
        <div className="compact-error" role="alert">
          {error}
        </div>
      )}
    </main>
  );
}

function ChevronIcon() {
  return <CircleCheck size={16} />;
}
