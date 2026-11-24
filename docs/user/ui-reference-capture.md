# UI reference capture and import

The Designer accepts reference screenshots, bounded structural extracts, and sanitized ZIP archives. References are analysis inputs only: imported HTML and CSS are never executed, browser storage and credentials are not copied, and archive previews use a script-disabled sandbox with a restrictive content security policy.

## Capture privacy and authorization

Capture only interfaces you own, are authorized to inspect, or may reuse under an applicable license. The capture request requires an explicit authorization attestation, a source label, and a license/reuse note. That attestation is not permission to reuse trademarks, proprietary assets, or copyrighted implementation code.

The optional Playwright adapter is not installed with JSON_CODR and does not download browsers. Install Playwright and its browser only after you approve those dependencies. A capture starts in a fresh browser context with service workers blocked. It allows only the configured origins, blocks fetch/XHR and other data APIs, and records bounded stylesheet/resource metadata rather than mirroring a site.

The portable capture excludes scripts and source maps, API payloads, request/response headers, cookies, browser storage, form values, authentication state, and query strings. Form controls are visually masked in viewport screenshots. Cross-origin resources that cannot be read safely remain unresolved references. CSS resource bodies are bounded; selector usage and framework hints are advisory rather than grounds for deleting CSS.

The Python adapter accepts a JSON request with exactly these fields:

```json
{
  "url": "https://example.test/",
  "authorization_attested": true,
  "source_label": "Authorized design reference",
  "license_note": "User-owned interface",
  "allowed_origins": ["https://example.test"],
  "routes": ["/"],
  "viewports": [{"width": 1280, "height": 800}]
}
```

Routes must be local paths without query strings. The initial URL's query and fragment are removed before navigation. The capture limit is 100 route/viewport combinations, a 20 MiB envelope, 5 MiB per stylesheet/resource body, 512 KiB per viewport screenshot, and 5 MiB total screenshot data. Viewports are limited to 4096 pixels per side and 8,388,608 pixels total. The command-line adapter writes only to a new output file:

```powershell
node tools\playwright_ui_capture.mjs request.json capture-envelope.json
```

The tool exits with a clear error if Playwright is unavailable; it never installs packages or downloads a browser.

## Build and import an archive

An archive contains `REPORT.md`, `DIFF.md`, and `ui-extract.json`. It may also contain `capture-envelope.json`, `index.html`, `styles.css`, and inert files under `assets/` (PNG, JPEG, SVG, WOFF/WOFF2, TTF, or OTF). JavaScript, source maps, executables, arbitrary filesystem paths, symlinks, and encrypted ZIP entries are not accepted.

To package a capture, place the capture envelope and its review report/diff in a directory and run:

```powershell
python tools\make_ui_reference_archive.py .\capture-review .\ui-reference.zip
```

The packager validates/sanitizes the structural extract, creates a versioned `MANIFEST.json`, and writes `MANIFEST.sha256`. The importer checks both manifests against every archive entry, rejects traversal, duplicate files, symlinks, unsupported schema versions, mismatched checksums, and oversized entries/archives. Screenshots/assets are copied into generated managed asset paths; the original paths are never used as destinations.

`REVIEW.txt` indicates unresolved sanitizer findings. Import is refused until the user explicitly acknowledges those findings. Acknowledgement does not execute or remove the flagged content; the importer still applies the same validators and sanitizer.

## Preview and provenance

HTML is reduced to a small structural tag and attribute allowlist. Forms and active/embedded content are removed. CSS imports, remote URLs, unsafe values, and unsupported declarations are omitted. No remote resource is loaded in preview. The preview document is intended for comparison and inspection, not as an exact or behavior-preserving clone.

Each imported reference records its generated identifier, content digest, source label, license/reuse note, and import kind. Browser captures also record adapter and sanitizer versions. License and authorization metadata must be supplied again for each import; it is not inferred from the source URL.
