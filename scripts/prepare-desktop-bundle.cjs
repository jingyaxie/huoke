#!/usr/bin/env node
/**
 * Tauri beforeBuildCommand 跨平台入口：macOS/Linux 走 bash，Windows 走 PowerShell。
 */
const { spawnSync } = require("child_process");
const path = require("path");

const root = path.resolve(__dirname, "..");

function run(cmd, args) {
  const result = spawnSync(cmd, args, { stdio: "inherit", cwd: root, shell: false });
  process.exit(result.status ?? 1);
}

if (process.platform === "win32") {
  run("powershell.exe", [
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    path.join(root, "scripts", "prepare_desktop_bundle.ps1"),
  ]);
} else {
  run("bash", [path.join(root, "scripts", "prepare_desktop_bundle.sh")]);
}
