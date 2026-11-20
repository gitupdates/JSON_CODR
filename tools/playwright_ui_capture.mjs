#!/usr/bin/env node
import { readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { pathToFileURL } from "node:url";

const MAX_PAGES = 100;
const MAX_RESOURCE_BYTES = 5 * 1024 * 1024;
const MAX_OUTPUT_BYTES = 20 * 1024 * 1024;

function fail(message) {
  console.error(message);
  process.exitCode = 1;
}

function validateRequest(request) {
  const keys = [
    "url", "authorization_attested", "source_label", "license_note",
    "allowed_origins", "routes", "viewports",
  ].sort();
  if (!request || Object.keys(request).sort().join() !== keys.join()) {
    throw new Error("Request must contain only the documented capture fields.");
  }
  if (request.authorization_attested !== true || !request.source_label?.trim() || !request.license_note?.trim()) {
    throw new Error("Explicit authorization and license/reuse provenance are required.");
  }
  const target = new URL(request.url);
  if (!["http:", "https:"].includes(target.protocol) || target.username || target.password) {
    throw new Error("Capture URL must be HTTP(S) and contain no embedded credentials.");
  }
  const origin = target.origin;
  if (!Array.isArray(request.allowed_origins) || !request.allowed_origins.includes(origin)) {
    throw new Error("The initial origin must be explicitly allow-listed.");
  }
  if (!Array.isArray(request.routes) || request.routes.length < 1 ||
      request.routes.length > MAX_PAGES || request.routes.some((route) =>
        typeof route !== "string" || !route.startsWith("/") || /[?#]/.test(route) || route.includes("://"))) {
    throw new Error("Routes must be bounded local paths without query strings.");
  }
  if (!Array.isArray(request.viewports) || request.viewports.length < 1 ||
      request.routes.length * request.viewports.length > MAX_PAGES ||
      request.viewports.some((size) => !size || Object.keys(size).sort().join() !== "height,width" ||
        !Number.isInteger(size.width) || size.width < 1 || size.width > 4096 ||
        !Number.isInteger(size.height) || size.height < 1 || size.height > 4096 ||
        size.width * size.height > 8388608)) {
    throw new Error("Viewport list is malformed or exceeds the page limit.");
  }
  return {
    ...request,
    url: `${target.origin}${target.pathname || "/"}`,
    allowed_origins: request.allowed_origins,
  };
}

async function main() {
  const [requestPath, outputPath] = process.argv.slice(2);
  if (!requestPath || !outputPath) {
    throw new Error("Usage: node tools/playwright_ui_capture.mjs <request.json> <capture-envelope.json>");
  }
  const request = validateRequest(JSON.parse(await readFile(requestPath, "utf8")));
  let chromium;
  try {
    ({ chromium } = await import("playwright"));
  } catch {
    throw new Error("Playwright is optional. Install it and a browser only after explicit approval; this tool does not download browsers.");
  }
  const captureSource = await readFile(new URL("../web/designer_capture.js", import.meta.url), "utf8");
  const allowedOrigins = new Set(request.allowed_origins);
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ serviceWorkers: "block" });
  const pages = [];
  const stylesheets = new Map();
  const resources = new Map();
  const unresolvedResources = [];
  let stylesheetBytesTotal = 0;
  let screenshotBytesTotal = 0;
  try {
    const page = await context.newPage();
    await page.route("**/*", async (route) => {
      const requestUrl = new URL(route.request().url());
      const origin = requestUrl.origin;
      const kind = route.request().resourceType();
      if (!allowedOrigins.has(origin) ||
          ["xhr", "fetch", "websocket", "eventsource", "media", "manifest"].includes(kind)) {
        await route.abort();
      } else {
        await route.continue();
      }
    });
    page.on("response", async (response) => {
      let parsed;
      try {
        parsed = new URL(response.url());
      } catch {
        return;
      }
      if (!allowedOrigins.has(parsed.origin)) return;
      const kind = response.request().resourceType();
      if (!["stylesheet", "image", "font"].includes(kind)) return;
      const path = parsed.pathname || "/";
      const contentType = (response.headers()["content-type"] || "").split(";", 1)[0].slice(0, 128);
      const contentLength = Number(response.headers()["content-length"] || 0);
      if (!resources.has(path) && resources.size >= 2048) return;
      resources.set(path, {
        type: kind,
        path,
        media_type: contentType,
        size: Number.isSafeInteger(contentLength) ? Math.min(contentLength, MAX_RESOURCE_BYTES) : 0,
      });
      if (kind === "stylesheet") {
        if (stylesheets.size >= 512 || !Number.isSafeInteger(contentLength) ||
            contentLength <= 0 || contentLength > MAX_RESOURCE_BYTES ||
            stylesheetBytesTotal >= 20 * 1024 * 1024) {
          unresolvedResources.push({ path, reason: "size-unknown-or-limit" });
        } else {
          try {
            const bytes = await response.body();
            if (bytes.length <= MAX_RESOURCE_BYTES && stylesheetBytesTotal + bytes.length <= 20 * 1024 * 1024) {
              stylesheets.set(path, bytes.toString("utf8"));
              stylesheetBytesTotal += bytes.length;
            } else {
              unresolvedResources.push({ path, reason: "size-limit" });
            }
          } catch {
            unresolvedResources.push({ path, reason: "unreadable" });
          }
        }
      }
    });

    for (const route of request.routes) {
      for (const viewport of request.viewports) {
        await page.setViewportSize(viewport);
        const target = new URL(route, request.url);
        await page.goto(target.href, { waitUntil: "domcontentloaded", timeout: 30000 });
        const captured = await page.evaluate(captureSource);
        await page.addStyleTag({
          content: "input,textarea,select,[contenteditable=true] {color:transparent!important;text-shadow:none!important;background-image:none!important;caret-color:transparent!important}",
        });
        const screenshotPath = `screenshots/${String(pages.length + 1).padStart(3, "0")}.jpg`;
        const screenshot = await page.screenshot({ type: "jpeg", quality: 60, fullPage: false });
        if (screenshot.length <= 512 * 1024 && screenshotBytesTotal + screenshot.length <= 5 * 1024 * 1024) {
          screenshotBytesTotal += screenshot.length;
          captured.screenshots = [{
            path: screenshotPath,
            media_type: "image/jpeg",
            size: screenshot.length,
            digest: `sha256:${createHash("sha256").update(screenshot).digest("hex")}`,
            content_base64: screenshot.toString("base64"),
          }];
        } else {
          captured.screenshots = [{ path: screenshotPath, omitted: "size_limit" }];
        }
        captured.route = route;
        captured.viewport = viewport;
        captured.stylesheets = [...stylesheets.entries()].sort(([a], [b]) => a.localeCompare(b))
          .map(([path, body]) => ({ path, body }));
        captured.resources = [...resources.values()].slice(0, 2048);
        captured.unresolved_resources = unresolvedResources.slice(0, 2048);
        pages.push(captured);
      }
    }
  } finally {
    await context.close();
    await browser.close();
  }
  const envelope = {
    schema_version: 1,
    pages,
    framework_hints: [...new Set(pages.flatMap((page) => page.framework_hints || []))].slice(0, 32),
    excluded_field_counts: { browser_storage: 0, request_headers: 0, response_headers: 0 },
  };
  const output = `${JSON.stringify(envelope, null, 2)}\n`;
  if (Buffer.byteLength(output, "utf8") > MAX_OUTPUT_BYTES) throw new Error("Capture envelope exceeds output size limit.");
  await writeFile(outputPath, output, { encoding: "utf8", flag: "wx" });
}

if (import.meta.url === pathToFileURL(process.argv[1] || "").href) {
  main().catch((error) => fail(error.message));
}
