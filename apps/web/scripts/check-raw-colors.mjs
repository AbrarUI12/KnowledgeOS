#!/usr/bin/env node
/**
 * Fails if feature/component code uses raw colors instead of design tokens (session.md S05).
 * Raw hex/rgb/hsl/oklch values belong only in styles/tokens.css.
 *
 * Usage: node scripts/check-raw-colors.mjs
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const SCAN_DIRS = ["app", "components", "features", "lib", "hooks"];
const EXTENSIONS = /\.(tsx?|css|mjs)$/;
const IGNORE_FILES = new Set(["app/globals.css"]); // maps tokens; contains no raw colors itself
// Hex colors (3/4/6/8 digits) and color functions with literal numbers.
const RAW_COLOR =
  /(?<![\w&-])#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})(?![\w-])|\b(?:rgba?|hsla?|oklch|oklab|lab|lch)\(\s*[\d.]/g;

function* walk(dir) {
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules" || entry.startsWith(".")) continue;
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) yield* walk(path);
    else if (EXTENSIONS.test(entry)) yield path;
  }
}

const violations = [];
for (const dir of SCAN_DIRS) {
  let base;
  try {
    base = join(root, dir);
    statSync(base);
  } catch {
    continue;
  }
  for (const file of walk(base)) {
    const rel = relative(root, file).replaceAll("\\", "/");
    if (IGNORE_FILES.has(rel)) continue;
    readFileSync(file, "utf8")
      .split("\n")
      .forEach((line, i) => {
        for (const match of line.matchAll(RAW_COLOR)) {
          violations.push(
            `${rel}:${i + 1}: raw color "${match[0]}" — use a token from styles/tokens.css`,
          );
        }
      });
  }
}

if (violations.length) {
  console.error(violations.join("\n"));
  console.error(`\n${violations.length} raw color(s) found.`);
  process.exit(1);
}
console.log("check-raw-colors: no raw colors outside styles/tokens.css");
