(() => {
  const maxNodes = 1000;
  const maxDepth = 16;
  const safeProperties = [
    "display", "position", "boxSizing", "width", "height", "minWidth", "minHeight",
    "maxWidth", "maxHeight", "marginTop", "marginRight", "marginBottom", "marginLeft",
    "paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "gap", "gridTemplateColumns",
    "flexDirection", "alignItems", "justifyContent", "color", "backgroundColor", "fontFamily",
    "fontSize", "fontWeight", "lineHeight", "letterSpacing", "borderColor", "borderRadius",
    "borderWidth", "boxShadow", "textAlign", "opacity",
  ];
  const safeText = (value, limit = 256) => (value || "").replace(/\s+/g, " ").trim().slice(0, limit);
  const localPath = (raw) => {
    try {
      const parsed = new URL(raw, location.href);
      if (parsed.origin !== location.origin) return null;
      return parsed.pathname;
    } catch {
      return null;
    }
  };
  const boundsOf = (element) => {
    const rect = element.getBoundingClientRect();
    return {
      x: Math.max(0, Math.round(rect.x)),
      y: Math.max(0, Math.round(rect.y)),
      width: Math.max(0, Math.round(rect.width)),
      height: Math.max(0, Math.round(rect.height)),
    };
  };
  const nameOf = (element) => {
    const aria = element.getAttribute("aria-label");
    const labelled = element.labels && element.labels.length
      ? Array.from(element.labels).map((label) => label.textContent).join(" ")
      : "";
    if (element.matches("input,textarea,select")) {
      return safeText(aria || labelled || element.getAttribute("placeholder") || element.title);
    }
    const semanticText = element.matches("h1,h2,h3,h4,h5,h6,button,a,label,[role=button]")
      ? element.innerText || element.textContent
      : "";
    return safeText(aria || element.getAttribute("title") || semanticText);
  };
  const nodeCount = { value: 0 };
  const accessibility = [];
  const computedStyles = [];
  const selectorUsage = new Set();
  const walk = (element, depth) => {
    if (nodeCount.value >= maxNodes || depth > maxDepth) return null;
    nodeCount.value += 1;
    const role = element.getAttribute("role") || ({
      H1: "heading", H2: "heading", H3: "heading", BUTTON: "button", A: "link",
      NAV: "navigation", MAIN: "main", HEADER: "banner", FOOTER: "contentinfo",
    }[element.tagName] || "");
    const name = nameOf(element);
    const classes = Array.from(element.classList).filter((value) => /^[A-Za-z0-9_-]{1,128}$/.test(value)).slice(0, 32);
    const style = getComputedStyle(element);
    const visual = {};
    for (const property of safeProperties) visual[property] = style[property];
    computedStyles.push({ tag: element.tagName.toLowerCase(), classes, bounds: boundsOf(element), properties: visual });
    for (const className of classes) selectorUsage.add(`.${className}`);
    if (role || name) accessibility.push({ role: role.slice(0, 64), name: name.slice(0, 256) });
    return {
      tag: element.tagName.toLowerCase(),
      role: role.slice(0, 64),
      name: name.slice(0, 256),
      classes,
      bounds: boundsOf(element),
      children: Array.from(element.children).slice(0, 100)
        .map((child) => walk(child, depth + 1)).filter(Boolean),
    };
  };
  const root = document.body ? walk(document.body, 0) : null;
  const headings = Array.from(document.querySelectorAll("h1,h2,h3,h4,h5,h6"))
    .slice(0, 128).map((element) => safeText(element.textContent));
  const labels = [];
  for (const element of Array.from(document.querySelectorAll("button,a,input,textarea,select,[role=button]")).slice(0, 512)) {
    const label = nameOf(element);
    if (label) labels.push(label);
  }
  const controls = Array.from(document.querySelectorAll("button,a,input,textarea,select,[role=button]"))
    .slice(0, 512).map((element) => ({
      type: safeText(element.getAttribute("type") || element.tagName.toLowerCase(), 64),
      label: nameOf(element),
    }));
  const classFrequencies = {};
  for (const element of Array.from(document.querySelectorAll("[class]")).slice(0, 10000)) {
    for (const className of element.classList) {
      if (/^[A-Za-z0-9_-]{1,128}$/.test(className)) {
        classFrequencies[className] = Math.min(1000000, (classFrequencies[className] || 0) + 1);
      }
    }
  }
  const cssVariables = {};
  for (const element of [document.documentElement, document.body].filter(Boolean)) {
    const style = getComputedStyle(element);
    for (let index = 0; index < style.length; index += 1) {
      const property = style[index];
      if (property.startsWith("--") && Object.keys(cssVariables).length < 256) {
        const variable = style.getPropertyValue(property).trim().slice(0, 256);
        if (!/(?:url|https?:|data:|javascript:|file:)/i.test(variable)) cssVariables[property] = variable;
      }
    }
  }
  const images = Array.from(document.images).slice(0, 512).map((image) => ({
    path: localPath(image.currentSrc || image.src),
    alt: safeText(image.alt),
    bounds: boundsOf(image),
  })).filter((image) => image.path);
  const backgrounds = [];
  for (const item of computedStyles.slice(0, 512)) {
    const element = document.querySelector(item.classes.map((name) => `.${CSS.escape(name)}`).join(","));
    if (!element) continue;
    const backgroundImage = getComputedStyle(element).backgroundImage;
    for (const match of backgroundImage.matchAll(/url\(["']?(.*?)["']?\)/g)) {
      const path = localPath(match[1]);
      backgrounds.push(path ? { path } : { unresolved: true });
    }
  }
  const resources = Array.from(document.querySelectorAll("link[rel=stylesheet],img,svg,image"))
    .slice(0, 1024).map((element) => ({
      type: element.tagName.toLowerCase() === "link" ? "stylesheet" : "image",
      path: localPath(element.href || element.currentSrc || element.getAttribute("href") || ""),
    })).filter((resource) => resource.path);
  const frameworkHints = [];
  if (document.querySelector("[data-reactroot],#root")) frameworkHints.push("React");
  if (document.querySelector("[ng-version],[_nghost]")) frameworkHints.push("Angular");
  if (document.querySelector("[data-v-app]")) frameworkHints.push("Vue");
  const gridColumns = Array.from(new Set(computedStyles
    .map((item) => item.properties.gridTemplateColumns)
    .filter((value) => value && value !== "none")
    .map((value) => value.split(/\s+/).length))).slice(0, 24);
  const pageTitle = headings[0] || "";
  return {
    schema_version: 1,
    route: location.pathname,
    viewport: { width: Math.min(10000, innerWidth), height: Math.min(10000, innerHeight) },
    dom: root,
    accessibility,
    headings,
    labels: Array.from(new Set(labels)).slice(0, 512),
    controls,
    class_frequencies: classFrequencies,
    grid_columns: gridColumns,
    computed_styles: computedStyles,
    inline_styles: Array.from(document.querySelectorAll("[style]")).slice(0, 256).map((element) => ({
      tag: element.tagName.toLowerCase(),
      declarations: element.getAttribute("style").slice(0, 2048),
    })),
    css_variables: cssVariables,
    tokens: {},
    images,
    backgrounds,
    svgs: Array.from(document.querySelectorAll("svg")).slice(0, 128).map((svg) => ({
      bounds: boundsOf(svg), label: safeText(svg.getAttribute("aria-label") || svg.querySelector("title")?.textContent),
    })),
    fonts: Array.from(document.fonts).slice(0, 256).map((font) => ({
      family: safeText(font.family, 128), weight: safeText(font.weight, 32), style: safeText(font.style, 32),
    })),
    resources,
    screenshots: [],
    selector_usage: Array.from(selectorUsage).slice(0, 2048),
    unresolved_resources: [],
    framework_hints: frameworkHints,
    page_title: pageTitle,
    excluded_field_counts: {
      form_values: controls.length,
      table_cells: document.querySelectorAll("td,th").length,
    },
  };
})();
