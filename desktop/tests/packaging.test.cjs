const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { backendLaunchPlan } = require("../backend.cjs");

test("packaged Windows launches only the bundled standalone backend", () => {
  const resourcesPath = path.resolve("Program Files", "Northstar VPN", "resources");
  const env = {
    PATH: "system-path", ProgramData: "program-data", VPN_PYTHON: "attacker.exe",
    PYTHONPATH: "injected", pythonhome: "injected", PYTHONSTARTUP: "injected",
    _PYI_APPLICATION_HOME_DIR: "foreign-bundle", VIRTUAL_ENV: "foreign-venv",
    VPN_WINDOWS_HELPER_TOKEN: "foreign-token", VPN_WINDOWS_HELPER_HOST: "remote",
    VPN_WINDOWS_HELPER_PORT: "1", VPN_PROFILE_ROOT: "foreign-profiles",
  };
  const plan = backendLaunchPlan("app.asar", "api-token", "instance", 12345, {
    packaged: true, platform: "win32", resourcesPath, env,
  });
  assert.equal(plan.command, path.join(resourcesPath, "backend", "NorthstarBackend.exe"));
  assert.deepEqual(plan.args, ["--host", "127.0.0.1", "--port", "12345"]);
  assert.equal(plan.options.cwd, resourcesPath);
  assert.equal(plan.options.windowsHide, true);
  assert.equal(plan.options.env.VPN_PROFILE_ROOT, path.join(resourcesPath, "profiles"));
  assert.equal(plan.options.env.VPN_API_TOKEN, "api-token");
  assert.equal(plan.options.env.VPN_INSTANCE, "instance");
  assert.equal(plan.options.env.VPN_UI_PORT, "12345");
  for (const key of Object.keys(env)) {
    if (!["PATH", "ProgramData", "VPN_PROFILE_ROOT"].includes(key))
      assert.equal(plan.options.env[key], undefined, key);
  }
  assert.equal(plan.options.env.PATH, env.PATH);
  assert.equal(env.PYTHONPATH, "injected", "parent environment remains unchanged");
  assert.ok(!JSON.stringify(plan.args).includes("api-token"));
});

test("development and Linux retain the Python launch path", () => {
  for (const [platform, packaged] of [["win32", false], ["linux", false], ["linux", true]]) {
    const plan = backendLaunchPlan("repo", "token", "id", 8766, {
      platform, packaged, env: { VPN_PYTHON: "dev-python", PYTHONPATH: "dev-path" },
    });
    assert.equal(plan.command, "dev-python");
    assert.deepEqual(plan.args, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8766", "--no-access-log"]);
    assert.equal(plan.options.cwd, path.join("repo", "backend"));
    assert.equal(plan.options.env.PYTHONPATH, "dev-path");
  }
});
