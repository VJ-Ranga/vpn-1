export type Server = { host: string; port: number };
export type Profile = {
  id: string;
  country_code: string;
  city: string;
  transport: "tcp" | "udp";
  virtual: boolean;
  servers: Server[];
};
export type Protection = {
  available: boolean;
  active: boolean;
  platform?: string;
  ipv6_blocked?: boolean;
  ipv6_guard_required?: boolean;
  interface?: string | null;
  error?: string | null;
  policy?: Pick<
    Preferences,
    "ipv6_protection" | "dns_protection" | "kill_switch" | "allow_lan"
  >;
};
export type Preferences = {
  transport: "tcp" | "udp";
  theme: "light" | "dark" | "system";
  ipv6_protection: boolean;
  dns_protection: boolean;
  kill_switch: boolean;
  allow_lan: boolean;
  auto_reconnect: boolean;
};
export type Status = {
  state: string;
  profile_id?: string | null;
  city?: string | null;
  country_code?: string | null;
  transport?: string | null;
  interface?: string | null;
  remote_endpoint?: string | null;
  vpn_ip?: string | null;
  public_ip?: string | null;
  latency?: { latency_ms: number | null; error?: string } | null;
  duration_seconds: number;
  bytes_in: number;
  bytes_out: number;
  download_bps: number;
  upload_bps: number;
  error?: string | null;
  protection?: Protection | null;
};

export type DesktopBridge = {
  token: string;
  compact: boolean;
  storage: { read: (key: string) => string[] | null; write: (key: string, values: string[]) => Promise<void> };
  setStartup: (enabled: boolean) => Promise<boolean>;
  getStartup: () => Promise<boolean>;
  openExternal: (url: string) => Promise<void>;
  notify: (message: string) => void;
  updateTray: (data: {
    connected: boolean;
    city: string;
    favorites: { id: string; label: string }[];
  }) => void;
  onCommand: (callback: (command: string) => void) => () => void;
};
declare global {
  interface Window {
    desktop?: DesktopBridge;
  }
}
