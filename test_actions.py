import concurrent.futures
import tempfile
import unittest
from pathlib import Path

from web_app.actions import ActionProposalService
from web_app.models import ActionSuggestion


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


class ActionProposalTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.service = ActionProposalService(clock=self.clock)
        self.cwd = str(Path(tempfile.gettempdir()).resolve())

    def propose(self, command="git status", session="session-a"):
        return self.service.propose(
            session,
            [ActionSuggestion(command=command, cwd=f"  {self.cwd}  ", explanation="  Explain it  ")],
            ["pack:skill", "pack:skill"],
            self.cwd,
        )[0]

    def test_normalizes_records_classifies_destructive_and_unknown_and_enforces_session(self):
        normal = self.propose("  git status  ")
        destructive = self.propose("Remove-Item -Recurse C:\\temp", "session-b")
        unknown = self.propose("mystery-tool --do-it", "session-c")

        self.assertEqual(normal.command, "git status")
        self.assertEqual(normal.cwd, self.cwd)
        self.assertEqual(normal.explanation, "Explain it")
        self.assertEqual(normal.source_skill_ids, ["pack:skill"])
        self.assertEqual(normal.risk, "normal")
        self.assertEqual(destructive.risk, "destructive")
        self.assertIn("destructive pattern", destructive.risk_reason)
        self.assertEqual(unknown.risk, "destructive")
        self.assertIn("unknown command", unknown.risk_reason)
        with self.assertRaises(PermissionError):
            self.service.get("wrong-session", normal.id)

    def test_normal_approval_is_terminal_bound_expires_and_is_one_shot(self):
        proposal = self.propose()
        approval = self.service.approve("session-a", proposal.id, "terminal-a")

        self.assertFalse(approval.requires_confirmation)
        self.assertEqual(approval.expires_in, 300)
        with self.assertRaises(PermissionError):
            self.service.consume(proposal.id, approval.token, "terminal-b")
        command = self.service.consume(proposal.id, approval.token, "terminal-a")
        self.assertEqual(command.command, "git status")
        with self.assertRaises(PermissionError):
            self.service.consume(proposal.id, approval.token, "terminal-a")

        expiring = self.propose("git diff", "session-b")
        token = self.service.approve("session-b", expiring.id, "terminal-a").token
        self.clock.value += 301
        with self.assertRaises(PermissionError):
            self.service.consume(expiring.id, token, "terminal-a")

    def test_destructive_requires_typed_phrase_and_uses_60_second_token(self):
        proposal = self.propose("git reset --hard")
        first = self.service.approve("session-a", proposal.id, "terminal-a")

        self.assertTrue(first.requires_confirmation)
        self.assertIsNone(first.token)
        with self.assertRaises(PermissionError):
            self.service.confirm_destructive("session-a", proposal.id, "terminal-a", "wrong phrase")
        final = self.service.confirm_destructive(
            "session-a", proposal.id, "terminal-a", first.confirmation_phrase
        )
        self.assertEqual(final.expires_in, 60)
        self.clock.value += 61
        with self.assertRaises(PermissionError):
            self.service.consume(proposal.id, final.token, "terminal-a")

    def test_reject_edit_supersession_and_restart_invalidate_authority(self):
        rejected = self.propose()
        rejected_token = self.service.approve("session-a", rejected.id, "terminal-a").token
        self.service.reject("session-a", rejected.id)
        with self.assertRaises(PermissionError):
            self.service.consume(rejected.id, rejected_token, "terminal-a")

        edited = self.propose("git diff", "session-b")
        edited_token = self.service.approve("session-b", edited.id, "terminal-a").token
        replacement = self.service.edit(
            "session-b", edited.id, ActionSuggestion(command="git log", cwd=self.cwd, explanation="changed")
        )
        self.assertNotEqual(edited.id, replacement.id)
        with self.assertRaises(PermissionError):
            self.service.consume(edited.id, edited_token, "terminal-a")

        old = self.propose("git status", "session-c")
        old_token = self.service.approve("session-c", old.id, "terminal-a").token
        self.propose("git diff", "session-c")
        with self.assertRaises(PermissionError):
            self.service.consume(old.id, old_token, "terminal-a")

        restarted = ActionProposalService(clock=self.clock)
        with self.assertRaises(KeyError):
            restarted.get("session-c", old.id)

    def test_concurrent_consumption_allows_exactly_one_winner(self):
        proposal = self.propose()
        token = self.service.approve("session-a", proposal.id, "terminal-a").token

        def consume():
            try:
                self.service.consume(proposal.id, token, "terminal-a")
                return True
            except PermissionError:
                return False

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: consume(), range(20)))
        self.assertEqual(results.count(True), 1)


if __name__ == "__main__":
    unittest.main()
