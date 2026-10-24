import type { Profile, Status, Preferences, Protection } from "./types";

const call = async (path: string, options: RequestInit = {}) => {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": window.desktop?.token || "local-ui",
      ...options.headers,
    },
    signal: AbortSignal.timeout(
      path === "/connect" || path === "/best" || path === "/switch-ip"
        ? 180000
        : path === "/latencies"
          ? 60000
          : 20000,
    ),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(
      typeof body.detail === "string" ? body.detail : "Request failed",
    );
  return body;
};
export const api = {
  profiles: (): Promise<{ profiles: Profile[] }> => call("/profiles"),
  refresh: (): Promise<{ profiles: Profile[] }> =>
    call("/profiles/refresh", { method: "POST" }),
  status: (): Promise<Status> => call("/status"),
  connect: (id: string, endpoint?: string): Promise<Status> =>
    call("/connect", {
      method: "POST",
      body: JSON.stringify({ profile_id: id, ...(endpoint ? { endpoint } : {}) }),
    }),
  best: (): Promise<Status> => call("/best", { method: "POST" }),
  disconnect: (): Promise<Status> => call("/disconnect", { method: "POST" }),
  switchIp: (): Promise<Status> => call("/switch-ip", { method: "POST" }),
  settings: (): Promise<{ settings: Preferences; protection: Protection }> =>
    call("/settings"),
  saveSettings: (
    values: Partial<Preferences>,
  ): Promise<{ settings: Preferences; protection: Protection }> =>
    call("/settings", { method: "PUT", body: JSON.stringify(values) }),
  latencies: (
    ids: string[],
  ): Promise<{ latencies: Record<string, number | null> }> =>
    call("/latencies", {
      method: "POST",
      body: JSON.stringify({ profile_ids: ids }),
    }),
  health: () => call("/health"),
  speed: () => call("/speed-test", { method: "POST" }),
  credentials: () => call("/settings/credentials"),
  testCredentials: () => call("/settings/credentials/test", { method: "POST" }),
  saveCredentials: (value: object) =>
    call("/settings/credentials", {
      method: "PUT",
      body: JSON.stringify(value),
    }),
  clearCredentials: () => call("/settings/credentials", { method: "DELETE" }),
};
