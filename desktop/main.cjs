const {
  app,
  BrowserWindow,
  Tray,
  Menu,
  nativeImage,
  ipcMain,
  shell,
  Notification,
  dialog,
  session,
} = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const {
  safeExternal,
  allowedNavigation,
  trayTemplate,
  desktopEntry,
} = require("./policy.cjs");
const { startBackend, stopBackend } = require("./backend.cjs");
const { DesktopStore } = require("./store.cjs");

const root = path.resolve(__dirname, "..");
const token = crypto.randomBytes(32).toString("hex");
const identity = crypto.randomUUID();
let backend,
  mainWindow,
  compactWindow,
  tray,
  quitting = false;
let state = { connected: false, city: "", favorites: [] };
let lastNotification = "";
const startupPath = () => {
  if (process.platform === "win32")
    return path.join(
      app.getPath("appData"),
      "Microsoft",
      "Windows",
      "Start Menu",
      "Programs",
      "Startup",
      "northstar-vpn.cmd",
    );
  return path.join(
    process.env.XDG_CONFIG_HOME || path.join(app.getPath("home"), ".config"),
    "autostart/northstar-vpn.desktop",
  );
};
app.setName("Northstar VPN");
// A static control panel does not need GPU acceleration on hybrid Linux laptops.
app.disableHardwareAcceleration();

function icon() {
  const bitmap = Buffer.alloc(32 * 32 * 4);
  for (let y = 3; y < 29; y++)
    for (let x = 4; x < 28; x++) {
      if (y > 18 && Math.abs(x - 16) > (29 - y) * 1.1) continue;
      const offset = (y * 32 + x) * 4;
      bitmap[offset] = state.connected ? 117 : 75;
      bitmap[offset + 1] = state.connected ? 199 : 128;
      bitmap[offset + 2] = state.connected ? 0 : 255;
      bitmap[offset + 3] = 255;
    }
  return nativeImage.createFromBitmap(bitmap, { width: 32, height: 32 });
}

function trusted(event) {
  if (
    !backend ||
    !event.senderFrame ||
    !allowedNavigation(event.senderFrame.url, backend.origin)
  )
    throw new Error("Untrusted desktop request");
}

function createWindow(compact = false) {
  const window = new BrowserWindow({
    width: compact ? 360 : 1200,
    height: compact ? 690 : 790,
    minWidth: compact ? 340 : 850,
    minHeight: compact ? 620 : 650,
    show: false,
    title: compact ? "Northstar - Compact" : "Northstar VPN",
    backgroundColor: "#ffffff",
    autoHideMenuBar: true,
    icon: icon(),
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (safeExternal(url)) void shell.openExternal(url);
    return { action: "deny" };
  });
  window.webContents.on("will-navigate", (event, url) => {
    if (!allowedNavigation(url, backend.origin)) {
      event.preventDefault();
      if (safeExternal(url)) void shell.openExternal(url);
    }
  });
  window.on("close", (event) => {
    if (!quitting) {
      event.preventDefault();
      window.hide();
    }
  });
  window.loadURL(`${backend.origin}/${compact ? "?compact=1" : ""}`);
  return window;
}

function showMain() {
  mainWindow.show();
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.focus();
}
function dispatch(command) {
  if (command === "quit") {
    app.quit();
    return;
  }
  if (command === "show") {
    showMain();
    return;
  }
  if (command === "compact") {
    if (!compactWindow) compactWindow = createWindow(true);
    compactWindow.show();
    compactWindow.focus();
    return;
  }
  if (["Settings", "Account"].includes(command)) showMain();
  mainWindow.webContents.send("northstar:command", command);
}

function updateTray() {
  tray.setImage(icon());
  tray.setToolTip(
    state.connected
      ? `Northstar — ${state.city}`
      : "Northstar VPN — disconnected",
  );
  tray.setContextMenu(Menu.buildFromTemplate(trayTemplate(state, dispatch)));
}

if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on("second-instance", () => {
    if (mainWindow) showMain();
  });
  app.on("window-all-closed", () => {
    /* The tray owns desktop lifetime. */
  });
  app.on("before-quit", () => {
    quitting = true;
    stopBackend(backend?.child);
  });
  app
    .whenReady()
    .then(async () => {
      const logPath = path.join(app.getPath("userData"), "backend.log");
      fs.mkdirSync(path.dirname(logPath), { recursive: true });
      if (fs.existsSync(logPath) && fs.statSync(logPath).size > 2 * 1024 * 1024)
        fs.renameSync(logPath, `${logPath}.old`);
      const log = fs.openSync(logPath, "a", 0o600);
      if (!app.isPackaged && process.platform === "win32") {
        const venvPython = path.join(root, "backend", ".venv", "Scripts", "python.exe");
        if (fs.existsSync(venvPython)) process.env.VPN_PYTHON = venvPython;
      } else if (!app.isPackaged) {
        const venvPython = path.join(root, "backend", ".venv", "bin", "python");
        if (fs.existsSync(venvPython)) process.env.VPN_PYTHON = venvPython;
      }
      try {
        backend = await startBackend(root, token, identity, log, {
          packaged: app.isPackaged,
          resourcesPath: process.resourcesPath,
        });
      } finally {
        fs.closeSync(log);
      }
      session.defaultSession.setPermissionRequestHandler(
        (_contents, _permission, callback) => callback(false),
      );
      session.defaultSession.webRequest.onHeadersReceived((details, callback) =>
        callback({
          responseHeaders: {
            ...details.responseHeaders,
            "Content-Security-Policy": [
              "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
            ],
          },
        }),
      );
      const store = new DesktopStore(path.join(app.getPath("userData"), "desktop-state.json"));
      ipcMain.handle("northstar:write-data", (event, key, values) => {
        trusted(event);
        store.write(key, values);
      });
      ipcMain.on("northstar:bootstrap", (event) => {
        trusted(event);
        event.returnValue = {
          token,
          compact: new URL(event.senderFrame.url).searchParams.has("compact"),
          data: store.snapshot(),
        };
      });
      mainWindow = createWindow();
      tray = new Tray(icon());
      updateTray();
      tray.on("click", showMain);
      if (!process.argv.includes("--background"))
        mainWindow.once("ready-to-show", showMain);
      if (process.platform === "win32") {
        ipcMain.handle("northstar:get-startup", (event) => {
          trusted(event);
          return app.getLoginItemSettings().openAtLogin;
        });
        ipcMain.handle("northstar:set-startup", (event, enabled) => {
          trusted(event);
          if (typeof enabled !== "boolean")
            throw new Error("Invalid startup value");
          app.setLoginItemSettings({
            openAtLogin: enabled,
            args: ["--background"],
          });
          return enabled;
        });
      } else {
        ipcMain.handle("northstar:get-startup", (event) => {
          trusted(event);
          return fs.existsSync(startupPath());
        });
        ipcMain.handle("northstar:set-startup", (event, enabled) => {
          trusted(event);
          if (typeof enabled !== "boolean")
            throw new Error("Invalid startup value");
          const target = startupPath();
          if (enabled) {
            fs.mkdirSync(path.dirname(target), { recursive: true });
            fs.writeFileSync(target, desktopEntry(root), { mode: 0o600 });
          } else fs.rmSync(target, { force: true });
          return enabled;
        });
      }
      ipcMain.handle("northstar:external", (event, url) => {
        trusted(event);
        if (!safeExternal(url)) throw new Error("Unsupported external link");
        return shell.openExternal(url);
      });
      ipcMain.on("northstar:notify", (event, message) => {
        trusted(event);
        if (
          typeof message !== "string" ||
          message.length > 200 ||
          message === lastNotification
        )
          return;
        lastNotification = message;
        if (Notification.isSupported())
          new Notification({
            title: "Northstar VPN",
            body: message,
            icon: icon(),
          }).show();
      });
      ipcMain.on("northstar:tray", (event, value) => {
        trusted(event);
        if (
          typeof value?.connected !== "boolean" ||
          typeof value?.city !== "string" ||
          !Array.isArray(value?.favorites)
        )
          return;
        const favorites = value.favorites
          .filter(
            (item) =>
              typeof item?.id === "string" &&
              /^[a-f0-9]{16}$/.test(item.id) &&
              typeof item?.label === "string",
          )
          .slice(0, 100);
        const next = {
          connected: value.connected,
          city: value.city.slice(0, 100),
          favorites,
        };
        if (JSON.stringify(next) !== JSON.stringify(state)) {
          state = next;
          updateTray();
        }
      });
      backend.child.once("exit", () => {
        if (!quitting) {
          dialog.showErrorBox(
            "Northstar backend stopped",
            `Reopen the app to restore desktop controls. VPN and firewall state remain managed by NetworkManager and the protection service. See ${logPath}.`,
          );
          app.quit();
        }
      });
      if (process.argv.includes("--smoke-test")) {
        mainWindow.webContents.once("did-finish-load", async () => {
          try {
            await new Promise((resolve) => setTimeout(resolve, 6500));
            const result = await mainWindow.webContents.executeJavaScript(
              `({bridge:window.desktop?.token?.length===64, nodeDisabled:typeof require==='undefined', locations:!!document.querySelector('.locations-scroll'), sandboxed:${mainWindow.webContents.getLastWebPreferences().sandbox}})`,
            );
            console.log("NORTHSTAR_SMOKE", JSON.stringify(result));
            if (process.env.VPN_SMOKE_OUTPUT) {
              fs.writeFileSync(
                process.env.VPN_SMOKE_OUTPUT,
                (await mainWindow.webContents.capturePage()).toPNG(),
              );
              fs.writeFileSync(
                `${process.env.VPN_SMOKE_OUTPUT}.json`,
                JSON.stringify(result, null, 2),
              );
            }
            if (Object.values(result).some((value) => value !== true))
              process.exitCode = 1;
          } catch (error) {
            console.error("NORTHSTAR_SMOKE", String(error));
            process.exitCode = 1;
          }
          app.quit();
        });
      }
    })
    .catch((error) => {
      dialog.showErrorBox(
        "Northstar could not start",
        String(error.message || error),
      );
      app.quit();
    });
}
