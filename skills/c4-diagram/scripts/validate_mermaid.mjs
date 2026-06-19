#!/usr/bin/env node
/**
 * Validate Mermaid diagram syntax.
 *
 * Usage:
 *   node scripts/validate_mermaid.mjs <file.mmd>
 *   node scripts/validate_mermaid.mjs -              # read from stdin
 *   echo '...' | node scripts/validate_mermaid.mjs
 *
 * Exit codes:
 *   0 — valid syntax
 *   1 — syntax error (details on stderr)
 *   2 — banned C4* keyword detected (warning on stderr, still validates syntax)
 *   3 — usage error
 *
 * Options:
 *   --help     Show this help
 *   --strict   Treat banned-keyword warnings as errors (exit 2)
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// Mermaid requires a DOM-like environment for initialization.
// We use a minimal shim — parse() doesn't actually render SVG.
import { JSDOM } from "jsdom";
const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>");
globalThis.window = dom.window;
globalThis.document = dom.window.document;
Object.defineProperty(globalThis, "navigator", {
  value: dom.window.navigator,
  writable: true,
  configurable: true,
});

const { default: mermaid } = await import("mermaid");

mermaid.initialize({
  securityLevel: "loose",
  startOnLoad: false,
});

// --- CLI parsing ---

const args = process.argv.slice(2);

if (args.includes("--help") || args.includes("-h")) {
  console.log(`Usage: node validate_mermaid.mjs [OPTIONS] <file.mmd | ->

Validate Mermaid diagram syntax using mermaid.parse().
Strips markdown fencing (\`\`\`mermaid ... \`\`\`) if present.

Options:
  --strict   Treat banned C4* keywords as errors (exit 2)
  --help     Show this help

Exit codes:
  0  Valid syntax
  1  Syntax error
  2  Banned keyword detected (--strict mode)
  3  Usage error`);
  process.exit(0);
}

const strict = args.includes("--strict");
const fileArgs = args.filter((a) => !a.startsWith("--"));

if (fileArgs.length > 1) {
  console.error("Error: expected at most one file argument.");
  process.exit(3);
}

// --- Read input ---

let code;

if (fileArgs.length === 0 || fileArgs[0] === "-") {
  // Read from stdin
  try {
    code = readFileSync(0, "utf-8");
  } catch {
    console.error("Error: could not read from stdin.");
    process.exit(3);
  }
} else {
  const filePath = resolve(fileArgs[0]);
  try {
    code = readFileSync(filePath, "utf-8");
  } catch (e) {
    console.error(`Error: could not read file: ${filePath}\n${e.message}`);
    process.exit(3);
  }
}

if (!code.trim()) {
  console.error("Error: empty input.");
  process.exit(3);
}

// --- Strip markdown fencing ---

const fencePattern = /^```mermaid\s*\n([\s\S]*?)\n```\s*$/m;
const fenceMatch = code.match(fencePattern);
if (fenceMatch) {
  code = fenceMatch[1];
}

// --- Check for banned C4* keywords ---

const BANNED_KEYWORDS = [
  "C4Context",
  "C4Container",
  "C4Component",
  "C4Deployment",
  "C4Dynamic",
];

const bannedFound = [];
for (const kw of BANNED_KEYWORDS) {
  // Match as the diagram type declaration (first non-comment, non-frontmatter line)
  const pattern = new RegExp(`^\\s*${kw}\\b`, "m");
  if (pattern.test(code)) {
    bannedFound.push(kw);
  }
}

if (bannedFound.length > 0) {
  const msg = `Warning: banned C4 keyword(s) detected: ${bannedFound.join(", ")}.\n` +
    `These are experimental and unreliable. Use flowchart + subgraphs instead.`;
  console.error(msg);
  if (strict) {
    process.exit(2);
  }
}

// --- Validate syntax ---

try {
  await mermaid.parse(code);
  console.log("✓ Valid");
  process.exit(bannedFound.length > 0 && strict ? 2 : 0);
} catch (e) {
  const errorMsg = e.message || String(e);
  console.error(`Syntax error: ${errorMsg}`);
  process.exit(1);
}
