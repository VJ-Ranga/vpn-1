const { contextBridge, ipcRenderer } = require("electron");
const bootstrap = ipcRenderer.sendSync("northstar:bootstrap");
contextBridge.exposeInMainWorld("desktop", {
  token: bootstrap.token,
  compact: bootstrap.compact,
  storage: {
    read: key => bootstrap.data[key] || null,
    write: (key, values) => ipcRenderer.invoke('northstar:write-data', key, values),
  },
  getStartup: () => ipcRenderer.invoke("northstar:get-startup"),
  setStartup: (enabled) => ipcRenderer.invoke("northstar:set-startup", enabled),
  openExternal: (url) => ipcRenderer.invoke("northstar:external", url),
  notify: (message) => ipcRenderer.send("northstar:notify", message),
  updateTray: (value) => ipcRenderer.send("northstar:tray", value),
  onCommand: (callback) => {
    const listener = (_event, command) => callback(command);
    ipcRenderer.on("northstar:command", listener);
    return () => ipcRenderer.removeListener("northstar:command", listener);
  },
});
