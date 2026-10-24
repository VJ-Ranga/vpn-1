const path = require("node:path");

function safeExternal(value) {
  try {
    const url = new URL(value);
    return (
      url.protocol === "https:" &&
      ["www.namecheap.com", "support.namecheap.com"].includes(url.hostname) &&
      !url.username &&
      !url.password
    );
  } catch {
    return false;
  }
}

function allowedNavigation(value, origin) {
  try {
    const url = new URL(value);
    return url.origin === origin && url.pathname === "/";
  } catch {
    return false;
  }
}

function trayTemplate(state, dispatch) {
  return [
    {
      label: state.connected
        ? `Connected — ${state.city || "VPN"}`
        : "Northstar VPN",
      enabled: false,
    },
    { type: "separator" },
    { label: "Best Available", click: () => dispatch("best") },
    {
      label: "Favorites",
      submenu: state.favorites.length
        ? state.favorites
            .slice(0, 100)
            .map((item) => ({
              label: String(item.label).slice(0, 100),
              click: () => dispatch(`connect:${item.id}`),
            }))
        : [{ label: "Save a favorite in Locations", enabled: false }],
    },
    {
      label: "Disconnect",
      enabled: state.connected,
      click: () => dispatch("disconnect"),
    },
    { type: "separator" },
    { label: "Show Northstar", click: () => dispatch("show") },
    { label: "Compact mode", click: () => dispatch("compact") },
    { label: "Settings", click: () => dispatch("Settings") },
    { label: "Account", click: () => dispatch("Account") },
    { type: "separator" },
    { label: "Quit", click: () => dispatch("quit") },
  ];
}

function quoted(value) {
  return `"${value.replace(/[\\"`$]/g, "\\$&")}"`;
}
function desktopEntry(root) {
  return `[Desktop Entry]\nType=Application\nName=Northstar VPN\nComment=Independent FastVPN client for Linux\nExec=${quoted(path.join(root, "scripts/start-desktop.sh"))} --background\nIcon=${path.join(root, "assets/northstar-vpn.svg")}\nTerminal=false\nCategories=Network;Security;\nStartupWMClass=northstar-vpn-desktop\nX-GNOME-Autostart-enabled=true\n`;
}

module.exports = {
  safeExternal,
  allowedNavigation,
  trayTemplate,
  desktopEntry,
};
