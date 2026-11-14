import json
import subprocess
import unittest
from pathlib import Path


MODULE = Path(__file__).parent / "web" / "dependency_install_queue.js"


class DependencyInstallQueueTests(unittest.TestCase):
    def run_node(self, source):
        return subprocess.run(
            ["node", "-e", source, str(MODULE)],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_deduplicates_orders_and_recovers_after_rejection(self):
        source = r'''
const assert = require("assert");
const createDependencyInstallQueue = require(process.argv[1]);

(async () => {
  const dispatched = [];
  const queue = createDependencyInstallQueue(async (command) => {
    dispatched.push(command);
    if (command === "fail") throw new Error("expected failure");
  });

  assert.strictEqual(queue.enqueue("first"), true);
  assert.strictEqual(queue.enqueue("first"), false);
  assert.strictEqual(queue.enqueue("fail"), true);
  assert.strictEqual(queue.enqueue("last"), true);
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.deepStrictEqual(dispatched, ["first", "fail", "last"]);
  process.stdout.write(JSON.stringify(dispatched));
})().catch((error) => { console.error(error); process.exit(1); });
'''
        result = self.run_node(source)
        self.assertEqual(json.loads(result.stdout), ["first", "fail", "last"])


if __name__ == "__main__":
    unittest.main()
