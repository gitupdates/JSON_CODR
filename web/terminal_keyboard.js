(function (root, factory) {
  const createTerminalKeyboardController = factory();
  if (typeof module === "object" && module.exports) module.exports = createTerminalKeyboardController;
  if (root) root.createTerminalKeyboardController = createTerminalKeyboardController;
})(typeof window !== "undefined" ? window : globalThis, function () {
  return function createTerminalKeyboardController(options = {}) {
    const copyText = options.copyText || (() => {});
    const interrupt = options.interrupt || (() => {});
    const loadHistory = options.loadHistory || (() => []);
    const saveHistory = options.saveHistory || (() => {});
    const now = options.now || Date.now;
    const chordTimeoutMs = options.chordTimeoutMs || 1500;
    let interruptChordStartedAt = null;
    let commandHistory = [];
    try {
      const loaded = loadHistory();
      if (Array.isArray(loaded)) commandHistory = loaded.filter((item) => typeof item === "string").slice(-100);
    } catch (_error) {
      commandHistory = [];
    }
    let historyIndex = commandHistory.length;
    let historyDraft = "";

    function persistHistory() {
      saveHistory([...commandHistory]);
    }

    function recordCommand(command) {
      const normalized = String(command || "").trim();
      if (normalized && commandHistory.at(-1) !== normalized) {
        commandHistory.push(normalized);
        commandHistory = commandHistory.slice(-100);
        persistHistory();
      }
      historyIndex = commandHistory.length;
      historyDraft = "";
    }

    function navigateHistory(direction, currentValue = "") {
      if (!commandHistory.length) return currentValue;
      if (direction < 0) {
        if (historyIndex === commandHistory.length) historyDraft = currentValue;
        historyIndex = Math.max(0, historyIndex - 1);
      } else {
        historyIndex = Math.min(commandHistory.length, historyIndex + 1);
      }
      return historyIndex === commandHistory.length ? historyDraft : commandHistory[historyIndex];
    }

    function clearCommandHistory() {
      commandHistory = [];
      historyIndex = 0;
      historyDraft = "";
      persistHistory();
    }

    function handleKeyEvent(event, selection = "") {
      if (event.type !== "keydown") return true;
      const key = String(event.key || "").toLowerCase();
      const controlKey = event.ctrlKey && !event.altKey && !event.metaKey;

      if (controlKey && key === "x") {
        interruptChordStartedAt = now();
        return false;
      }

      if (controlKey && key === "c") {
        const chordIsActive = interruptChordStartedAt !== null
          && now() - interruptChordStartedAt <= chordTimeoutMs;
        interruptChordStartedAt = null;
        if (chordIsActive) interrupt();
        else if (selection) copyText(selection);
        return false;
      }

      if (controlKey && key === "v") {
        interruptChordStartedAt = null;
        return true;
      }

      if (!controlKey || !["control", "shift", "alt", "meta"].includes(key)) {
        interruptChordStartedAt = null;
      }
      return true;
    }

    return { clearCommandHistory, handleKeyEvent, navigateHistory, recordCommand };
  };
});
