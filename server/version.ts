/**
 * Single source of truth for app version/build identity.
 * Reads from package.json at module load time.
 */

import { readFileSync } from "fs";
import { resolve } from "path";

let _version = "0.0.0";
let _name = "aiden-iwo2";

try {
  const pkgPath = resolve(process.cwd(), "package.json");
  const pkg = JSON.parse(readFileSync(pkgPath, "utf-8"));
  _version = pkg.version || _version;
  _name = pkg.name || _name;
} catch {
  console.warn("[version] Could not read package.json — using fallback version");
}

export const APP_VERSION = _version;
export const APP_NAME = _name;
export const BUILD_ID = `${_name}@${_version}`;
