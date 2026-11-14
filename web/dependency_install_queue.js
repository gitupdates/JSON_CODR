(function (root, factory) {
  const createDependencyInstallQueue = factory();
  if (typeof module === "object" && module.exports) module.exports = createDependencyInstallQueue;
  if (root) root.createDependencyInstallQueue = createDependencyInstallQueue;
})(typeof window !== "undefined" ? window : globalThis, function () {
  return function createDependencyInstallQueue(runCommand) {
    if (typeof runCommand !== "function") throw new TypeError("runCommand must be a function");
    const seen = new Set();
    let tail = Promise.resolve();

    return {
      enqueue(command) {
        if (typeof command !== "string" || !command.trim() || seen.has(command)) return false;
        seen.add(command);
        tail = tail.then(() => runCommand(command)).catch((error) => {
          console.error("Automatic prerequisite installation failed", error);
        });
        return true;
      },
    };
  };
});
