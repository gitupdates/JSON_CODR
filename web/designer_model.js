(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.JSONCodrDesignerModel = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const BREAKPOINTS = ["desktop", "tablet", "mobile"];
  const MAX_NODES = 1000;
  const MAX_DEPTH = 32;

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function canonicalize(value) {
    if (value === null || typeof value === "boolean" || typeof value === "string") {
      return JSON.stringify(value);
    }
    if (typeof value === "number") {
      if (!Number.isFinite(value)) throw new TypeError("design JSON numbers must be finite");
      return JSON.stringify(value);
    }
    if (Array.isArray(value)) return `[${value.map(canonicalize).join(",")}]`;
    if (typeof value === "object") {
      const keys = Object.keys(value).sort();
      return `{${keys.map((key) => `${JSON.stringify(key)}:${canonicalize(value[key])}`).join(",")}}`;
    }
    throw new TypeError("design document must contain JSON values only");
  }

  function sha256(text) {
    const bytes = new TextEncoder().encode(text);
    const words = [];
    for (let index = 0; index < bytes.length; index += 1) {
      words[index >> 2] = (words[index >> 2] || 0) | (bytes[index] << (24 - (index % 4) * 8));
    }
    const bitLength = bytes.length * 8;
    words[bitLength >> 5] = (words[bitLength >> 5] || 0) | (0x80 << (24 - bitLength % 32));
    const paddedLength = (((bitLength + 64) >> 9) << 4) + 15;
    words[paddedLength] = bitLength;
    words[paddedLength - 1] = Math.floor(bitLength / 0x100000000);

    const constants = [
      0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
      0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
      0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
      0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
      0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
      0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
      0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
      0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
    ];
    const state = [
      0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
      0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
    ];
    const rotate = (value, count) => (value >>> count) | (value << (32 - count));
    for (let offset = 0; offset < words.length; offset += 16) {
      const schedule = new Array(64);
      for (let index = 0; index < 16; index += 1) schedule[index] = words[offset + index] | 0;
      for (let index = 16; index < 64; index += 1) {
        const x = schedule[index - 15];
        const y = schedule[index - 2];
        const s0 = rotate(x, 7) ^ rotate(x, 18) ^ (x >>> 3);
        const s1 = rotate(y, 17) ^ rotate(y, 19) ^ (y >>> 10);
        schedule[index] = (schedule[index - 16] + s0 + schedule[index - 7] + s1) | 0;
      }
      let [a, b, c, d, e, f, g, h] = state;
      for (let index = 0; index < 64; index += 1) {
        const sum1 = rotate(e, 6) ^ rotate(e, 11) ^ rotate(e, 25);
        const choose = (e & f) ^ (~e & g);
        const first = (h + sum1 + choose + constants[index] + schedule[index]) | 0;
        const sum0 = rotate(a, 2) ^ rotate(a, 13) ^ rotate(a, 22);
        const majority = (a & b) ^ (a & c) ^ (b & c);
        const second = (sum0 + majority) | 0;
        h = g; g = f; f = e; e = (d + first) | 0;
        d = c; c = b; b = a; a = (first + second) | 0;
      }
      state[0] = (state[0] + a) | 0;
      state[1] = (state[1] + b) | 0;
      state[2] = (state[2] + c) | 0;
      state[3] = (state[3] + d) | 0;
      state[4] = (state[4] + e) | 0;
      state[5] = (state[5] + f) | 0;
      state[6] = (state[6] + g) | 0;
      state[7] = (state[7] + h) | 0;
    }
    return state.map((value) => (value >>> 0).toString(16).padStart(8, "0")).join("");
  }

  function canonicalDigest(document) {
    const value = clone(document);
    delete value.canonical_digest;
    return `sha256:${sha256(canonicalize(value))}`;
  }

  function fail(code, message, details) {
    const error = new Error(message);
    error.code = code;
    error.details = details;
    throw error;
  }

  function validateSafeJson(value, path = []) {
    const forbidden = /(^on[a-z]|script|handler|secret|credential|token|cookie|(^|_)(file_)?path($|_))/i;
    if (Array.isArray(value)) {
      value.forEach((child, index) => validateSafeJson(child, path.concat(String(index))));
      return;
    }
    if (value && typeof value === "object") {
      for (const [key, child] of Object.entries(value)) {
        if (forbidden.test(key)) fail("invalid-document", `forbidden design key: ${path.concat(key).join(".")}`);
        validateSafeJson(child, path.concat(key));
      }
      return;
    }
    if (typeof value === "string" && /^[A-Za-z]:[\\/]/.test(value)) {
      fail("invalid-document", "absolute machine paths are not allowed in a design");
    }
    if (typeof value === "number" && !Number.isFinite(value)) {
      fail("invalid-document", "design numbers must be finite");
    }
  }

  function validateDocument(document) {
    if (!document || document.schema_version !== 2 || !document.project_id) {
      fail("invalid-document", "a schema-version-2 design document is required");
    }
    if (!Array.isArray(document.pages) || !document.pages.length || !Array.isArray(document.nodes) || !document.nodes.length) {
      fail("invalid-document", "design pages and nodes are required");
    }
    if (document.nodes.length > MAX_NODES) fail("invalid-document", "design node limit exceeded");
    validateSafeJson(document.tokens || {});
    validateSafeJson(document.metadata || {});
    const byId = new Map();
    for (const node of document.nodes) {
      if (!node || typeof node.node_id !== "string" || byId.has(node.node_id)) fail("invalid-document", "node identifiers must be unique");
      byId.set(node.node_id, node);
    }
    const pageIds = new Set();
    const slugs = new Set();
    for (const page of document.pages) {
      if (!page || pageIds.has(page.page_id) || slugs.has(page.slug) || !byId.has(page.root_node_id)) {
        fail("invalid-document", "page identifiers, slugs, and root nodes must be valid");
      }
      pageIds.add(page.page_id);
      slugs.add(page.slug);
    }
    for (const node of document.nodes) {
      validateSafeJson(node.properties || {});
      validateSafeJson(node.styles || {});
      validateSafeJson(node.breakpoint_overrides || {});
      validateSafeJson(node.actions || []);
      if (!Array.isArray(node.children)) fail("invalid-document", "node children must be an array");
      if (node.parent_id != null) {
        const parent = byId.get(node.parent_id);
        if (!parent || !parent.children.includes(node.node_id)) fail("invalid-document", "parent and child relationships must match");
      }
      if (new Set(node.children).size !== node.children.length) fail("invalid-document", "child identifiers must be unique");
      for (const childId of node.children) {
        const child = byId.get(childId);
        if (!child || child.parent_id !== node.node_id) fail("invalid-document", "parent and child relationships must match");
      }
      const layout = node.layout || {};
      if (layout.kind === "freeform") {
        for (const key of ["x", "y", "width", "height"]) {
          if (!Number.isFinite(layout[key]) || layout[key] < 0 || (key === "width" || key === "height") && layout[key] === 0) {
            fail("invalid-document", "freeform bounds must be finite and positive");
          }
        }
        if (node.parent_id != null) {
            const parent = byId.get(node.parent_id);
            if (!parent || parent.layout?.kind !== "freeform"
              || layout.x + layout.width > parent.layout.width
              || layout.y + layout.height > parent.layout.height) {
              fail("invalid-document", "freeform coordinates must stay within a freeform parent");
            }
        }
      }
    }
    const visiting = new Set();
    const visited = new Set();
    function visit(id, depth) {
      if (visiting.has(id)) fail("invalid-document", "design node cycle detected");
      if (depth > MAX_DEPTH) fail("invalid-document", "design nesting limit exceeded");
      if (visited.has(id)) return;
      visiting.add(id);
      for (const childId of byId.get(id).children) visit(childId, depth + 1);
      visiting.delete(id);
      visited.add(id);
    }
    for (const node of document.nodes) visit(node.node_id, 1);
    return document;
  }

  function effectiveNode(document, nodeId, breakpoint) {
    if (!BREAKPOINTS.includes(breakpoint)) fail("invalid-breakpoint", "unknown breakpoint");
    const node = document.nodes.find((entry) => entry.node_id === nodeId);
    if (!node) fail("missing-node", `node not found: ${nodeId}`);
    const result = clone(node);
    delete result.breakpoint_overrides;
    for (const name of BREAKPOINTS.slice(0, BREAKPOINTS.indexOf(breakpoint) + 1)) {
      const override = node.breakpoint_overrides?.[name];
      if (!override) continue;
      result.properties = { ...result.properties, ...(override.properties || {}) };
      result.styles = { ...result.styles, ...(override.styles || {}) };
      if (override.layout) result.layout = clone(override.layout);
    }
    return result;
  }

  function createDesignerModel(document) {
    const copy = clone(document);
    validateDocument(copy);
    const expected = canonicalDigest(copy);
    if (copy.canonical_digest != null && copy.canonical_digest !== expected) {
      fail("stale-document", "design canonical digest does not match its content");
    }
    copy.canonical_digest = expected;
    return {
      clone,
      canonicalize,
      canonicalDigest,
      validateDocument,
      effectiveNode: (nodeId, breakpoint) => effectiveNode(copy, nodeId, breakpoint),
      getDocument: () => clone(copy),
    };
  }

  createDesignerModel.clone = clone;
  createDesignerModel.canonicalize = canonicalize;
  createDesignerModel.canonicalDigest = canonicalDigest;
  createDesignerModel.validateDocument = validateDocument;
  createDesignerModel.effectiveNode = effectiveNode;
  createDesignerModel.breakpoints = BREAKPOINTS.slice();
  return createDesignerModel;
});
