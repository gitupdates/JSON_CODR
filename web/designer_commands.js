(function (root, factory) {
  const modelApi = typeof module === "object" && module.exports
    ? require("./designer_model.js")
    : root.JSONCodrDesignerModel;
  const createDesignerModel = factory(modelApi);
  if (typeof module === "object" && module.exports) module.exports = createDesignerModel;
  if (root) root.createDesignerModel = createDesignerModel;
})(typeof globalThis !== "undefined" ? globalThis : this, function (modelApi) {
  "use strict";

  const ACTIONS = new Set([
    "navigate", "open_dialog", "close_dialog", "switch_tab", "toggle_visibility",
    "set_value", "reset_form", "submit_https_form", "request_connector",
  ]);
  const BREAKPOINTS = ["desktop", "tablet", "mobile"];
  const FORBIDDEN_KEY = /(^on[a-z]|script|handler|secret|credential|token|cookie|(^|_)(file_)?path($|_))/i;

  function conflict(code, message, details) {
    return { ok: false, conflict: { code, message, ...(details ? { details } : {}) } };
  }

  function createDesignerModel(document, registry = {}, options = {}) {
    const model = modelApi(document);
    let current = model.getDocument();
    const capabilities = registry instanceof Map ? Object.fromEntries(registry) : registry || {};
    const snap = options.snap === true;
    const gridSize = Number.isFinite(options.gridSize) && options.gridSize > 0 ? options.gridSize : 8;
    const historyLimit = Number.isInteger(options.historyLimit) && options.historyLimit >= 0
      ? options.historyLimit
      : 100;
    const undoStack = [];
    const redoStack = [];
    let selected = [];

    function byId(id, source = current) {
      return source.nodes.find((node) => node.node_id === id) || null;
    }

    function pageRoot(id, source = current) {
      return source.pages.some((page) => page.root_node_id === id);
    }

    function component(type) {
      return capabilities[type] || null;
    }

    function ensureNode(id, source = current) {
      const node = byId(id, source);
      if (!node) throw Object.assign(new Error(`node not found: ${id}`), { code: "missing-node" });
      return node;
    }

    function ensureUnlocked(node, capability) {
      if ((node.locked_capabilities || []).includes(capability)) {
        throw Object.assign(new Error(`node capability is protected: ${capability}`), { code: "protected-node" });
      }
    }

    function validateProperty(node, key, value) {
      const schema = component(node.component_type)?.property_schema?.[key];
      if (!schema) {
        throw Object.assign(new Error(`property is not supported by ${node.component_type}: ${key}`), { code: "invalid-property" });
      }
      const type = schema.type;
      const validType = type === "array" ? Array.isArray(value)
        : type === "integer" ? Number.isInteger(value)
          : type === "number" ? typeof value === "number" && Number.isFinite(value)
            : type === "string" ? typeof value === "string"
              : type === "boolean" ? typeof value === "boolean" : true;
      if (!validType
        || (schema.enum && !schema.enum.includes(value))
        || (Number.isFinite(schema.minimum) && value < schema.minimum)
        || (Number.isFinite(schema.maximum) && value > schema.maximum)
        || (Number.isFinite(schema.maxLength) && value.length > schema.maxLength)) {
        throw Object.assign(new Error(`property value is invalid: ${key}`), { code: "invalid-property" });
      }
    }

    function validateAction(node, action) {
      if (!action || typeof action !== "object" || Array.isArray(action)
        || !ACTIONS.has(action.kind) || typeof action.event !== "string"
        || !/^[a-z][a-z0-9_-]{0,63}$/.test(action.event)
        || !action.arguments || typeof action.arguments !== "object" || Array.isArray(action.arguments)) {
        throw Object.assign(new Error("action binding is invalid"), { code: "invalid-action" });
      }
      const definition = component(node.component_type);
      if (definition && !definition.action_slots.includes(action.event)) {
        throw Object.assign(new Error("component does not expose this action slot"), { code: "invalid-action" });
      }
      safeValue(action.arguments);
    }

    function safeValue(value) {
      modelApi.validateDocument({
        schema_version: 2,
        project_id: current.project_id,
        name: current.name,
        mode: current.mode,
        pages: current.pages,
        nodes: current.nodes,
        tokens: {},
        references: [],
        metadata: { candidate: value },
      });
    }

    function parentFor(node, source = current) {
      return node.parent_id == null ? null : byId(node.parent_id, source);
    }

    function childAllowed(parent, childType) {
      const definition = component(parent.component_type);
      return !definition || !Array.isArray(definition.allowed_children)
        || definition.allowed_children.includes(childType);
    }

    function checkParent(parent, childType) {
      if (!parent || !Array.isArray(parent.children)) {
        throw Object.assign(new Error("a valid parent container is required"), { code: "invalid-parent" });
      }
      if (!childAllowed(parent, childType)) {
        throw Object.assign(new Error(`${parent.component_type} cannot contain ${childType}`), { code: "invalid-parent" });
      }
    }

    function snapValue(value) {
      return snap ? Math.round(value / gridSize) * gridSize : value;
    }

    function normalizedLayout(node, partial, source, { applySnap = false } = {}) {
      const incoming = partial || {};
      const layout = { ...(node.layout || {}), ...incoming };
      if (incoming.kind && incoming.kind !== "freeform" && incoming.kind !== node.layout?.kind) {
        for (const key of ["x", "y", "width", "height"]) layout[key] = null;
      }
      if (layout.kind !== "freeform") {
        for (const key of ["x", "y", "width", "height"]) {
          if (layout[key] != null) {
            throw Object.assign(new Error("coordinates are limited to freeform layouts"), { code: "invalid-layout" });
          }
        }
        return layout;
      }
      if (!["x", "y", "width", "height"].every((key) => Number.isFinite(layout[key]))) {
        throw Object.assign(new Error("freeform layouts require finite bounds"), { code: "invalid-layout" });
      }
      if (applySnap && snap) {
        for (const key of ["x", "y", "width", "height"]) layout[key] = snapValue(layout[key]);
      }
      if (layout.x < 0 || layout.y < 0 || layout.width <= 0 || layout.height <= 0) {
        throw Object.assign(new Error("freeform bounds must be positive"), { code: "invalid-layout" });
      }
      if (node.parent_id != null) {
        const parent = byId(node.parent_id, source);
        if (!parent || parent.layout?.kind !== "freeform") {
          throw Object.assign(new Error("freeform coordinates require a freeform parent"), { code: "invalid-layout" });
        }
        if (layout.x + layout.width > parent.layout.width || layout.y + layout.height > parent.layout.height) {
          throw Object.assign(new Error("freeform bounds exceed the parent container"), { code: "out-of-bounds" });
        }
      }
      return layout;
    }

    function ensureNotRoot(node) {
      if (pageRoot(node.node_id)) {
        throw Object.assign(new Error("page root nodes cannot be moved or removed"), { code: "protected-node" });
      }
    }

    function insertAt(list, item, index) {
      const position = index == null ? list.length : index;
      if (!Number.isInteger(position) || position < 0 || position > list.length) {
        throw Object.assign(new Error("child index is out of range"), { code: "invalid-index" });
      }
      list.splice(position, 0, item);
    }

    function subtree(nodeId, source = current) {
      const result = [];
      const visit = (id) => {
        const node = byId(id, source);
        if (!node) throw Object.assign(new Error(`node not found: ${id}`), { code: "missing-node" });
        result.push(node);
        node.children.forEach(visit);
      };
      visit(nodeId);
      return result;
    }

    function assertSiblingSelection(ids, source = current) {
      if (!Array.isArray(ids) || ids.length < 2 || new Set(ids).size !== ids.length) {
        throw Object.assign(new Error("at least two distinct sibling nodes are required"), { code: "invalid-selection" });
      }
      const nodes = ids.map((id) => ensureNode(id, source));
      const parentId = nodes[0].parent_id;
      if (parentId == null || nodes.some((node) => node.parent_id !== parentId)) {
        throw Object.assign(new Error("selected nodes must share a parent"), { code: "invalid-selection" });
      }
      ensureNotRoot(nodes[0]);
      const parent = ensureNode(parentId, source);
      if (parent.layout?.kind !== "freeform" || nodes.some((node) => node.layout?.kind !== "freeform")) {
        throw Object.assign(new Error("operation requires freeform siblings"), { code: "invalid-selection" });
      }
      return { nodes, parent };
    }

    function normalizeNode(candidate, parentId, source) {
      if (!candidate || typeof candidate !== "object" || typeof candidate.node_id !== "string"
        || typeof candidate.component_type !== "string") {
        throw Object.assign(new Error("inserted nodes require an identifier and component type"), { code: "invalid-node" });
      }
      const allowedKeys = new Set([
        "node_id", "component_type", "parent_id", "children", "properties", "styles", "layout",
        "breakpoint_overrides", "actions", "locked_capabilities", "inert_placeholder",
      ]);
      if (Object.keys(candidate).some((key) => !allowedKeys.has(key))) {
        throw Object.assign(new Error("inserted node contains unsupported fields"), { code: "invalid-node" });
      }
      if (byId(candidate.node_id, source)) {
        throw Object.assign(new Error(`node identifier already exists: ${candidate.node_id}`), { code: "duplicate-id" });
      }
      const node = {
        node_id: candidate.node_id,
        component_type: candidate.component_type,
        parent_id: parentId,
        children: candidate.children || [],
        properties: candidate.properties || {},
        styles: candidate.styles || {},
        layout: {
          kind: "stack", x: null, y: null, width: null, height: null, gap: null, columns: null,
          ...(candidate.layout || {}),
        },
        breakpoint_overrides: candidate.breakpoint_overrides || {},
        actions: candidate.actions || [],
        locked_capabilities: candidate.locked_capabilities || [],
        inert_placeholder: candidate.inert_placeholder === true || component(candidate.component_type)?.inert_placeholder === true
          || !component(candidate.component_type),
      };
      if (!node.properties || typeof node.properties !== "object" || Array.isArray(node.properties)
        || !node.styles || typeof node.styles !== "object" || Array.isArray(node.styles)
        || !Array.isArray(node.children) || !Array.isArray(node.actions)
        || !Array.isArray(node.locked_capabilities)
        || !node.breakpoint_overrides || typeof node.breakpoint_overrides !== "object" || Array.isArray(node.breakpoint_overrides)) {
        throw Object.assign(new Error("inserted node fields have invalid types"), { code: "invalid-node" });
      }
      Object.entries(node.properties).forEach(([key, value]) => validateProperty(node, key, value));
      node.actions.forEach((action) => validateAction(node, action));
      return node;
    }

    function removeSubtree(candidate, node) {
      ensureNotRoot(node);
      ensureUnlocked(node, "delete");
      const removedNodes = subtree(node.node_id, candidate);
      if (removedNodes.some((entry) => entry.locked_capabilities?.includes("delete"))) {
        throw Object.assign(new Error("a protected descendant cannot be removed"), { code: "protected-node" });
      }
      const parent = byId(node.parent_id, candidate);
      if (!parent) throw Object.assign(new Error("node parent is missing"), { code: "invalid-document" });
      parent.children = parent.children.filter((id) => id !== node.node_id);
      const removedIds = new Set(removedNodes.map((child) => child.node_id));
      candidate.nodes = candidate.nodes.filter((child) => !removedIds.has(child.node_id));
    }

    function parentIndex(parent, nodeId) {
      const index = parent.children.indexOf(nodeId);
      if (index < 0) throw Object.assign(new Error("node is missing from its parent"), { code: "invalid-document" });
      return index;
    }

    function applyCommand(candidate, command) {
      const node = command.nodeId == null ? null : ensureNode(command.nodeId, candidate);
      switch (command.type) {
        case "insert": {
          const parent = ensureNode(command.parentId, candidate);
          const inserted = normalizeNode(command.node, parent.node_id, candidate);
          checkParent(parent, inserted.component_type);
          if (inserted.children.length) {
            throw Object.assign(new Error("insert accepts a leaf node only"), { code: "invalid-node" });
          }
          inserted.layout = normalizedLayout(inserted, inserted.layout, candidate);
          safeValue(inserted);
          insertAt(parent.children, inserted.node_id, command.index);
          candidate.nodes.push(inserted);
          break;
        }
        case "remove":
          removeSubtree(candidate, node);
          break;
        case "move": {
          ensureNotRoot(node);
          const oldParent = parentFor(node, candidate);
          const newParent = ensureNode(command.parentId, candidate);
          checkParent(newParent, node.component_type);
          let ancestor = newParent;
          while (ancestor) {
            if (ancestor.node_id === node.node_id) {
              throw Object.assign(new Error("a node cannot be moved into its descendant"), { code: "invalid-parent" });
            }
            ancestor = ancestor.parent_id == null ? null : byId(ancestor.parent_id, candidate);
          }
          if (oldParent === newParent) {
            const oldIndex = parentIndex(oldParent, node.node_id);
            oldParent.children.splice(oldIndex, 1);
            insertAt(newParent.children, node.node_id, command.index);
            if (command.layout) node.layout = normalizedLayout(node, command.layout, candidate, { applySnap: true });
          } else {
            const previousRegion = node.locked_capabilities?.includes("move_outside_region")
              ? node.node_id
              : (function findRegion(parent) {
                let currentParent = parent;
                while (currentParent) {
                  if (currentParent.locked_capabilities?.includes("move_outside_region")) return currentParent.node_id;
                  currentParent = currentParent.parent_id == null ? null : byId(currentParent.parent_id, candidate);
                }
                return null;
              })(oldParent);
            let nextParent = newParent;
            let nextRegion = null;
            while (nextParent) {
              if (nextParent.locked_capabilities?.includes("move_outside_region")) {
                nextRegion = nextParent.node_id;
                break;
              }
              nextParent = nextParent.parent_id == null ? null : byId(nextParent.parent_id, candidate);
            }
            if (previousRegion !== nextRegion) {
              throw Object.assign(new Error("node cannot leave its protected region"), { code: "protected-node" });
            }
            if (oldParent) oldParent.children = oldParent.children.filter((id) => id !== node.node_id);
            node.parent_id = newParent.node_id;
            if (command.layout) node.layout = normalizedLayout(node, command.layout, candidate, { applySnap: true });
            insertAt(newParent.children, node.node_id, command.index);
          }
          break;
        }
        case "resize":
          ensureUnlocked(node, "resize");
          node.layout = normalizedLayout(node, command.layout, candidate, { applySnap: true });
          break;
        case "group": {
          const { nodes, parent } = assertSiblingSelection(command.nodeIds, candidate);
          const groupId = command.groupId;
          const groupType = command.componentType || "stack";
          if (typeof groupId !== "string" || byId(groupId, candidate)) {
            throw Object.assign(new Error("group requires a new identifier"), { code: "duplicate-id" });
          }
          const definition = component(groupType);
          if (!definition || !Array.isArray(definition.allowed_children)) {
            throw Object.assign(new Error("group type must be a registered container"), { code: "invalid-component" });
          }
          nodes.forEach((child) => {
            if (child.locked_capabilities?.length) {
              throw Object.assign(new Error("protected nodes cannot be grouped"), { code: "protected-node" });
            }
            checkParent({ component_type: groupType, children: [] }, child.component_type);
          });
          const originalOrder = parent.children.slice();
          const selectedSet = new Set(nodes.map((child) => child.node_id));
          const orderedNodes = originalOrder.filter((id) => selectedSet.has(id)).map((id) => byId(id, candidate));
          const groupIndex = Math.min(...orderedNodes.map((child) => parentIndex(parent, child.node_id)));
          let groupLayout;
          if (parent.layout.kind === "freeform") {
            const left = Math.min(...orderedNodes.map((child) => child.layout.x));
            const top = Math.min(...orderedNodes.map((child) => child.layout.y));
            const right = Math.max(...orderedNodes.map((child) => child.layout.x + child.layout.width));
            const bottom = Math.max(...orderedNodes.map((child) => child.layout.y + child.layout.height));
            groupLayout = { kind: "freeform", x: left, y: top, width: right - left, height: bottom - top, gap: null, columns: null };
            orderedNodes.forEach((child) => {
              child.layout = { ...child.layout, x: child.layout.x - left, y: child.layout.y - top };
            });
          } else {
            groupLayout = { kind: groupType === "grid" ? "grid" : "stack", x: null, y: null, width: null, height: null, gap: null, columns: null };
          }
          const group = {
            node_id: groupId,
            component_type: groupType,
            parent_id: parent.node_id,
            children: orderedNodes.map((child) => child.node_id),
            properties: {},
            styles: {},
            layout: groupLayout,
            breakpoint_overrides: {},
            actions: [],
            locked_capabilities: [],
            inert_placeholder: false,
          };
          parent.children = originalOrder.filter((id) => !selectedSet.has(id));
          insertAt(parent.children, groupId, groupIndex);
          orderedNodes.forEach((child) => { child.parent_id = groupId; });
          candidate.nodes.push(group);
          break;
        }
        case "ungroup": {
          ensureNotRoot(node);
          ensureUnlocked(node, "delete");
          const parent = parentFor(node, candidate);
          if (!parent) throw Object.assign(new Error("group parent is missing"), { code: "invalid-document" });
          const index = parentIndex(parent, node.node_id);
          const children = node.children.map((id) => ensureNode(id, candidate));
          if (subtree(node.node_id, candidate).some((entry) => entry !== node && entry.locked_capabilities?.length)) {
            throw Object.assign(new Error("protected descendants cannot be ungrouped"), { code: "protected-node" });
          }
          if (parent.layout.kind === "freeform" && node.layout.kind === "freeform") {
            for (const child of children) {
              child.layout = { ...child.layout, x: child.layout.x + node.layout.x, y: child.layout.y + node.layout.y };
            }
          }
          parent.children.splice(index, 1, ...node.children);
          children.forEach((child) => { child.parent_id = parent.node_id; });
          candidate.nodes = candidate.nodes.filter((entry) => entry.node_id !== node.node_id);
          break;
        }
        case "duplicate": {
          ensureNotRoot(node);
          const parent = parentFor(node, candidate);
          if (!parent) throw Object.assign(new Error("node parent is missing"), { code: "invalid-document" });
          const originalSubtree = subtree(node.node_id, candidate);
          if (originalSubtree.some((item) => item.locked_capabilities?.length)) {
            throw Object.assign(new Error("protected nodes cannot be duplicated"), { code: "protected-node" });
          }
          const idMap = command.nodeMap || {};
          const ids = originalSubtree.map((item) => idMap[item.node_id]);
          if (ids.some((id) => typeof id !== "string" || byId(id, candidate)) || new Set(ids).size !== ids.length) {
            throw Object.assign(new Error("duplicate requires a new identifier for every copied node"), { code: "invalid-id-map" });
          }
          const copies = originalSubtree.map((item) => {
            const copy = modelApi.clone(item);
            copy.node_id = idMap[item.node_id];
            copy.parent_id = item.node_id === node.node_id ? parent.node_id : idMap[item.parent_id];
            copy.children = item.children.map((id) => idMap[id]);
            return copy;
          });
          const at = parentIndex(parent, node.node_id) + 1;
          insertAt(parent.children, copies[0].node_id, at);
          candidate.nodes.push(...copies);
          break;
        }
        case "reorder": {
          ensureNotRoot(node);
          const parent = parentFor(node, candidate);
          const currentIndex = parentIndex(parent, node.node_id);
          parent.children.splice(currentIndex, 1);
          insertAt(parent.children, node.node_id, command.index);
          break;
        }
        case "set-property": {
          if (typeof command.key !== "string" || FORBIDDEN_KEY.test(command.key)) {
            throw Object.assign(new Error("property key is not allowed"), { code: "invalid-property" });
          }
          if (node.locked_capabilities?.includes("rename")
            && ["label", "name", "title", "text"].includes(command.key)) {
            throw Object.assign(new Error("node name is protected"), { code: "protected-node" });
          }
          if (node.locked_capabilities?.includes("rebind")
            && ["href", "target", "destination", "action"].includes(command.key)) {
            throw Object.assign(new Error("node behavior is protected"), { code: "protected-node" });
          }
          if (node.locked_capabilities?.includes("hide") && command.key === "hidden" && command.value === true) {
            throw Object.assign(new Error("node visibility is protected"), { code: "protected-node" });
          }
          validateProperty(node, command.key, command.value);
          safeValue({ [command.key]: command.value });
          node.properties = { ...(node.properties || {}), [command.key]: command.value };
          break;
        }
        case "set-style": {
          if (typeof command.key !== "string" || FORBIDDEN_KEY.test(command.key)) {
            throw Object.assign(new Error("style key is not allowed"), { code: "invalid-property" });
          }
          if (node.locked_capabilities?.includes("hide")
            && ((command.key === "display" && command.value === "none")
              || (command.key === "visibility" && command.value === "hidden"))) {
            throw Object.assign(new Error("node visibility is protected"), { code: "protected-node" });
          }
          safeValue({ [command.key]: command.value });
          node.styles = { ...(node.styles || {}), [command.key]: command.value };
          break;
        }
        case "set-action": {
          ensureUnlocked(node, "rebind");
          if (node.inert_placeholder) {
            throw Object.assign(new Error("inert components cannot have actions"), { code: "invalid-action" });
          }
          const actions = (node.actions || []).slice();
          const index = command.index == null ? actions.length : command.index;
          if (!Number.isInteger(index) || index < 0 || index > actions.length) {
            throw Object.assign(new Error("action index is out of range"), { code: "invalid-index" });
          }
          if (command.action == null) {
            if (index >= actions.length) throw Object.assign(new Error("action index does not exist"), { code: "invalid-index" });
            actions.splice(index, 1);
          } else {
            const action = command.action;
            validateAction(node, action);
            if (index === actions.length) actions.push(modelApi.clone(action));
            else actions[index] = modelApi.clone(action);
          }
          node.actions = actions;
          break;
        }
        case "set-breakpoint": {
          ensureUnlocked(node, "resize");
          if (!BREAKPOINTS.includes(command.breakpoint)) {
            throw Object.assign(new Error("unknown breakpoint"), { code: "invalid-breakpoint" });
          }
          const overrides = { ...(node.breakpoint_overrides || {}) };
          if (command.override == null) {
            delete overrides[command.breakpoint];
          } else {
            const supplied = modelApi.clone(command.override);
            if ((supplied.properties != null && (typeof supplied.properties !== "object" || Array.isArray(supplied.properties)))
              || (supplied.styles != null && (typeof supplied.styles !== "object" || Array.isArray(supplied.styles)))) {
              throw Object.assign(new Error("breakpoint properties and styles must be objects"), { code: "invalid-breakpoint" });
            }
            const override = {
              properties: supplied.properties || {},
              styles: supplied.styles || {},
              layout: supplied.layout || null,
            };
            if (Object.keys(supplied).some((key) => !["properties", "styles", "layout"].includes(key))) {
              throw Object.assign(new Error("breakpoint override contains unsupported fields"), { code: "invalid-breakpoint" });
            }
            for (const [key, value] of Object.entries(override.properties)) validateProperty(node, key, value);
            if (!override || typeof override !== "object" || Array.isArray(override)) {
              throw Object.assign(new Error("breakpoint override must be an object"), { code: "invalid-breakpoint" });
            }
            if (override.layout) {
              override.layout = normalizedLayout(
                { ...node, layout: override.layout },
                override.layout,
                candidate,
              );
            }
            safeValue(override);
            overrides[command.breakpoint] = override;
          }
          node.breakpoint_overrides = overrides;
          break;
        }
        case "replace-asset": {
          if (node.component_type !== "image" || typeof command.assetId !== "string"
            || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(command.assetId)) {
            throw Object.assign(new Error("a managed asset identifier is required for an image"), { code: "invalid-asset" });
          }
          node.properties = { ...(node.properties || {}), asset_id: command.assetId };
          break;
        }
        case "align": {
          const { nodes } = assertSiblingSelection(command.nodeIds, candidate);
          const axis = command.axis;
          const edge = command.edge;
          if (!["x", "y"].includes(axis) || !["start", "center", "end"].includes(edge)) {
            throw Object.assign(new Error("alignment axis or edge is invalid"), { code: "invalid-alignment" });
          }
          const position = axis;
          const dimension = axis === "x" ? "width" : "height";
          const anchor = nodes[0].layout[position] + (edge === "center" ? nodes[0].layout[dimension] / 2 : edge === "end" ? nodes[0].layout[dimension] : 0);
          for (const selectedNode of nodes) {
            const offset = edge === "center" ? selectedNode.layout[dimension] / 2 : edge === "end" ? selectedNode.layout[dimension] : 0;
            selectedNode.layout[position] = snapValue(anchor - offset);
          }
          break;
        }
        case "distribute": {
          const { nodes } = assertSiblingSelection(command.nodeIds, candidate);
          if (!["x", "y"].includes(command.axis)) {
            throw Object.assign(new Error("distribution axis is invalid"), { code: "invalid-alignment" });
          }
          const position = command.axis;
          const dimension = command.axis === "x" ? "width" : "height";
          const ordered = nodes.slice().sort((left, right) => left.layout[position] - right.layout[position]);
          if (ordered.length < 3) break;
          const first = ordered[0].layout[position];
          const last = ordered.at(-1).layout[position] + ordered.at(-1).layout[dimension];
          const occupied = ordered.reduce((total, item) => total + item.layout[dimension], 0);
          const gap = (last - first - occupied) / (ordered.length - 1);
          let cursor = first;
          for (const selectedNode of ordered) {
            selectedNode.layout[position] = snapValue(cursor);
            cursor += selectedNode.layout[dimension] + gap;
          }
          break;
        }
        case "nudge": {
          ensureNotRoot(node);
          if (node.layout?.kind !== "freeform" || !Number.isFinite(command.dx) || !Number.isFinite(command.dy)) {
            throw Object.assign(new Error("keyboard movement requires a freeform node and finite deltas"), { code: "invalid-layout" });
          }
          const layout = {
            ...node.layout,
            x: snapValue(node.layout.x + command.dx),
            y: snapValue(node.layout.y + command.dy),
          };
          node.layout = normalizedLayout(node, layout, candidate);
          break;
        }
        default:
          throw Object.assign(new Error(`unsupported command: ${command.type}`), { code: "unknown-command" });
      }
    }

    function commit(candidate, previous, command) {
      modelApi.validateDocument(candidate);
      candidate.canonical_digest = modelApi.canonicalDigest(candidate);
      current = candidate;
      if (historyLimit > 0) {
        undoStack.push(previous);
        if (undoStack.length > historyLimit) undoStack.shift();
      }
      redoStack.length = 0;
      if (command.type === "remove") selected = selected.filter((id) => byId(id));
      return {
        ok: true,
        document: modelApi.clone(current),
        inverse: {
          type: "restore-document",
          projectId: current.project_id,
          expectedDigest: current.canonical_digest,
          document: previous,
        },
        announcements: command.type === "insert" ? ["Element added"]
          : command.type === "remove" ? ["Element removed"]
            : command.type === "move" ? ["Element moved"] : [],
      };
    }

    function dispatch(command) {
      if (!command || typeof command !== "object" || Array.isArray(command)) {
        return conflict("invalid-command", "a command object is required");
      }
      if (command.projectId !== current.project_id) {
        return conflict("wrong-project", "command belongs to another project");
      }
      if (command.expectedDigest !== current.canonical_digest) {
        return conflict("stale-document", "command was created for a different document revision", {
          expected: current.canonical_digest,
          received: command.expectedDigest ?? null,
        });
      }
      const previous = modelApi.clone(current);
      const candidate = modelApi.clone(current);
      try {
        if (command.type === "restore-document") {
          if (!command.document || command.document.project_id !== current.project_id) {
            throw Object.assign(new Error("inverse document belongs to another project"), { code: "wrong-project" });
          }
          const restored = modelApi.clone(command.document);
          modelApi.validateDocument(restored);
          restored.canonical_digest = modelApi.canonicalDigest(restored);
          current = restored;
          if (command.type !== "undo" && historyLimit > 0) {
            undoStack.push(previous);
            if (undoStack.length > historyLimit) undoStack.shift();
          }
          redoStack.length = 0;
          return {
            ok: true,
            document: modelApi.clone(current),
            inverse: {
              type: "restore-document",
              projectId: current.project_id,
              expectedDigest: current.canonical_digest,
              document: previous,
            },
            announcements: [],
          };
        }
        applyCommand(candidate, command);
        return commit(candidate, previous, command);
      } catch (error) {
        return conflict(error.code || "invalid-command", error.message, error.details);
      }
    }

    function undo() {
      if (!undoStack.length) return conflict("history-limit", "no earlier command is available");
      const previous = undoStack.pop();
      redoStack.push(modelApi.clone(current));
      current = modelApi.clone(previous);
      return { ok: true, document: modelApi.clone(current), announcements: ["Undo"] };
    }

    function redo() {
      if (!redoStack.length) return conflict("nothing-to-redo", "there is no command to redo");
      const next = redoStack.pop();
      if (historyLimit > 0) {
        undoStack.push(modelApi.clone(current));
        if (undoStack.length > historyLimit) undoStack.shift();
      }
      current = modelApi.clone(next);
      return { ok: true, document: modelApi.clone(current), announcements: ["Redo"] };
    }

    return {
      dispatch,
      undo,
      redo,
      effectiveNode: (nodeId, breakpoint) => modelApi.effectiveNode(current, nodeId, breakpoint),
      selection: () => selected.slice(),
      select: (nodeIds) => {
        const ids = Array.isArray(nodeIds) ? nodeIds : [nodeIds];
        selected = [...new Set(ids)].filter((id) => byId(id));
        return selected.slice();
      },
      getDocument: () => modelApi.clone(current),
    };
  }

  return createDesignerModel;
});
