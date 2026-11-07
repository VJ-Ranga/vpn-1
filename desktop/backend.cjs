const { spawn } = require("node:child_process");
const net = require("node:net");
const path = require("node:path");

async function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const port = server.address().port;
      server.close(() => resolve(port));
    });
  });
}

async function waitForBackend(
  origin,
  identity,
  timeout = 60000,
  request = fetch,
) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    try {
      const response = await request(`${origin}/api/health`, {
        // Windows helper health includes a firewall-policy query. A 2-second
        // deadline repeatedly aborted valid cold-start responses once the
        // installed service was running, preventing desktop startup entirely.
        signal: AbortSignal.timeout(30000),
      });
      if (response.ok && (await response.json()).instance === identity) return;
    } catch {
      /* The child may still be importing dependencies. */
    }
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  throw new Error(
    "Backend could not start. See the desktop backend log for details.",
  );
}

function stopBackend(child) {
  if (child && child.exitCode === null && !child.killed) child.kill("SIGTERM");
}

function backendLaunchPlan(root, token, identity, port, {
  packaged = false,
  resourcesPath = process.resourcesPath,
  platform = process.platform,
  env = process.env,
} = {}) {
  const bundled = packaged && platform === "win32";
  const childEnv = { ...env };
  if (bundled) {
    for (const key of Object.keys(childEnv)) {
      if (/^PYTHON/i.test(key) || /^_PYI_/i.test(key) ||
          /^(VIRTUAL_ENV|__PYVENV_LAUNCHER__|VPN_PYTHON|VPN_WINDOWS_HELPER_(TOKEN|HOST|PORT))$/i.test(key))
        delete childEnv[key];
    }
    childEnv.VPN_PROFILE_ROOT = path.join(resourcesPath, "profiles");
  }
  Object.assign(childEnv, {
    VPN_UI_PORT: String(port), VPN_API_TOKEN: token, VPN_INSTANCE: identity,
  });
  const args = ["--host", "127.0.0.1", "--port", String(port)];
  return {
    command: bundled ? path.join(resourcesPath, "backend", "NorthstarBackend.exe") :
      env.VPN_PYTHON || (platform === "win32" ? "python" : "python3"),
    args: bundled ? args : ["-m", "uvicorn", "app.main:app", ...args, "--no-access-log"],
    options: {
      cwd: bundled ? resourcesPath : path.join(root, "backend"),
      env: childEnv,
      windowsHide: true,
    },
  };
}

async function startBackend(root, token, identity, log, options = {}) {
  const port = await freePort();
  const origin = `http://127.0.0.1:${port}`;
  const plan = backendLaunchPlan(root, token, identity, port, options);
  const child = spawn(plan.command, plan.args, {
    ...plan.options, stdio: ["ignore", log, log],
  });
  let failure;
  child.on("error", (error) => {
    failure = error;
  });
  try {
    await waitForBackend(origin, identity);
    if (failure) throw failure;
  } catch (error) {
    stopBackend(child);
    throw failure || error;
  }
  return { child, origin };
}

module.exports = { freePort, waitForBackend, stopBackend, startBackend, backendLaunchPlan };
