import { useEffect, useState } from "react";
import { Settings, Trash2 } from "lucide-react";
import { api } from "../api";
export function SettingsPanel() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [configured, setConfigured] = useState(false);
  const [message, setMessage] = useState("");
  const [health, setHealth] = useState("Health not checked");
  const refresh = async () => {
    try {
      const v = await api.credentials();
      setConfigured(v.configured);
      setUsername(v.username || "");
      setMessage("Credentials refreshed.");
    } catch (err) {
      setMessage((err as Error).message);
    }
  };
  useEffect(() => {
    void refresh();
  }, []);
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.saveCredentials({ username, password });
      setConfigured(true);
      setPassword("");
      setMessage("Credentials saved to Secret Service.");
    } catch (err) {
      setMessage((err as Error).message);
    }
  };
  const checkHealth = async () => {
    try {
      const v = await api.health();
      setHealth(
        `NetworkManager ${v.network_manager ? "ready" : "unavailable"} · OpenVPN plugin ${v.openvpn_plugin ? "ready" : "unavailable"}`,
      );
    } catch (err) {
      setHealth((err as Error).message);
    }
  };
  const testCredentials = async () => {
    try {
      const v = await api.testCredentials();
      setMessage(v.message);
    } catch (err) {
      setMessage((err as Error).message);
    }
  };
  return (
    <section className="panel settings">
      <div className="section-head">
        <div>
          <div className="eyebrow">
            <Settings size={14} /> LOCAL SETTINGS
          </div>
          <h2>Credentials</h2>
        </div>
      </div>
      <p className="muted">
        Stored in Linux Secret Service. Password never returns to browser.
      </p>
      <form onSubmit={save}>
        <input
          placeholder="Namecheap username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
        <input
          type="password"
          placeholder="Namecheap password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button className="primary" type="submit">
          {configured ? "Update credentials" : "Save credentials"}
        </button>
      </form>
      <div className="settings-actions">
        <button onClick={() => void refresh()}>Refresh credentials</button>
        <button onClick={() => void checkHealth()}>Check health</button>
        <button onClick={() => void testCredentials()} disabled={!configured}>
          Re-test credentials
        </button>
      </div>
      <p className="muted">{health}</p>
      {configured && (
        <button
          className="danger"
          onClick={async () => {
            await api.clearCredentials();
            setConfigured(false);
            setUsername("");
            setMessage("Credentials cleared.");
          }}
        >
          <Trash2 size={15} /> Clear saved credentials
        </button>
      )}
      {message && <p className="notice">{message}</p>}
    </section>
  );
}
