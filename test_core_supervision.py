import tempfile
import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from web_app.core.contracts import TaskCommand
from web_app.core.store import TaskStore


def _command(task_id: str, command_id: str) -> TaskCommand:
    return TaskCommand(
        command_id=command_id,
        task_id=task_id,
        thread_id="thread-1",
        project_id="project-1",
        command_type="capability.execute",
        payload={
            "capability_id": "native.read",
            "operation": "read",
            "project_root": ".",
            "target_path": "README.md",
        },
    )


class DurableSupervisionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.temporary.name) / "tasks.sqlite")

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def test_dependency_readiness_changes_only_after_dependency_completes(self):
        from web_app.core.contracts import TaskEventDraft

        self.store.create(_command("task-a", "command-a"))
        self.store.create(_command("task-b", "command-b"))
        self.store.set_dependencies("task-b", ("task-a",))
        self.assertEqual([item.task_id for item in self.store.ready_tasks()], ["task-a"])

        self.store.append("task-a", TaskEventDraft(event_type="task.started"))
        self.store.append("task-a", TaskEventDraft(event_type="task.completed"))

        self.assertEqual([item.task_id for item in self.store.ready_tasks()], ["task-b"])

    def test_store_assigns_telemetry_identity_and_sequence(self):
        first = self.store.record_telemetry("runtime.started", {"pid": 42})
        second = self.store.record_telemetry("runtime.ready", {"pid": 42})

        self.assertNotEqual(first.telemetry_id, second.telemetry_id)
        self.assertEqual((first.sequence, second.sequence), (1, 2))
        self.assertEqual(self.store.telemetry(after_sequence=1), (second,))

    def test_concurrent_heartbeat_writers_are_serialized_and_staleness_is_derived(self):
        threads = [
            threading.Thread(target=self.store.record_heartbeat, args=("web", index, "ready"))
            for index in range(1, 9)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        heartbeat = self.store.runtime_heartbeat("web")
        self.assertIn(heartbeat.pid, range(1, 9))
        stale = self.store.runtime_heartbeat(
            "web",
            now=heartbeat.observed_at + timedelta(seconds=61),
            stale_after=timedelta(seconds=60),
        )
        self.assertTrue(stale.stale)

    def test_watchdog_records_child_exit_and_clean_shutdown(self):
        from supervisor import SupervisorWatchdog

        class FakeProcess:
            pid = 91
            returncode = None

            def poll(self):
                return self.returncode

            def terminate(self):
                self.returncode = 0

            def wait(self, timeout=None):
                return self.returncode

        process = FakeProcess()
        calls = []
        watchdog = SupervisorWatchdog(
            Path(self.temporary.name),
            self.store,
            command=("python", "-m", "uvicorn"),
            popen_factory=lambda *args, **kwargs: calls.append((args, kwargs)) or process,
        )
        watchdog.start()
        process.returncode = 7

        self.assertFalse(watchdog.poll_once())
        watchdog.stop()

        kinds = [item.kind for item in self.store.telemetry()]
        self.assertIn("runtime.child_started", kinds)
        self.assertIn("runtime.child_exited", kinds)
        self.assertIn("runtime.supervisor_stopped", kinds)
        self.assertTrue(calls[0][1]["env"]["OLLAMA_NO_CLOUD"] == "1")

    def test_watchdog_recovers_a_failed_child_without_recreating_tasks(self):
        from supervisor import SupervisorWatchdog

        class FakeProcess:
            def __init__(self, pid, returncode):
                self.pid = pid
                self.returncode = returncode

            def poll(self):
                return self.returncode

            def terminate(self):
                self.returncode = 0

            def wait(self, timeout=None):
                return self.returncode

        processes = [FakeProcess(101, 7), FakeProcess(102, None)]
        self.store.create(_command("task-existing", "command-existing"))
        watchdog = SupervisorWatchdog(
            Path(self.temporary.name), self.store,
            command=("python", "-m", "uvicorn"),
            popen_factory=lambda *args, **kwargs: processes.pop(0),
            max_restarts=1,
        )
        watchdog.start()
        self.assertFalse(watchdog.poll_once())
        self.assertTrue(watchdog.recover_once())
        self.assertEqual(watchdog.process.pid, 102)
        self.assertEqual(self.store.get("task-existing").events[0].causation_id, "command-existing")
        self.assertIn("runtime.child_restarting", [item.kind for item in self.store.telemetry()])


if __name__ == "__main__":
    unittest.main()
