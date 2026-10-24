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
  timeout = 20000,
  request = fetch,
) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    try {
      const response = await request(`${origin}/api/health`, {
        signal: AbortSignal.timeout(2000),
      });
      if (response.ok && (await response.json()).instance === identity) return;
    } catch {
      /* The child may still be importing dependencies. */
    }
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  throw new Error(
    "Backend could not start. Check Python dependencies and the desktop backend log.",
  );
}

function stopBackend(child) {
  if (child && child.exitCode === null && !child.killed) child.kill("SIGTERM");
}

async function startBackend(root, token, identity, log) {
  const port = await freePort();
  const origin = `http://127.0.0.1:${port}`;
  const child = spawn(
    process.env.VPN_PYTHON || "python3",
    [
      "-m",
      "uvicorn",
      "app.main:app",
      "--host",
      "127.0.0.1",
      "--port",
      String(port),
      "--no-access-log",
    ],
    {
      cwd: path.join(root, "backend"),
      env: {
        ...process.env,
        VPN_UI_PORT: String(port),
        VPN_API_TOKEN: token,
        VPN_INSTANCE: identity,
      },
      stdio: ["ignore", log, log],
    },
  );
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

module.exports = { freePort, waitForBackend, stopBackend, startBackend };
