import unittest

from demo import CASES, EXPIRY, INITIAL_STATE, TICK, VALID_PROPOSAL, build_executor
from lab import Assignment, Decision, Executor


class ExecutorTests(unittest.TestCase):
    def test_cases_a_through_e(self):
        for label, proposal, expected in CASES:
            with self.subTest(case=label):
                executor = build_executor(EXPIRY - TICK)
                before = executor.snapshot()
                self.assertIs(executor.execute(proposal), expected)
                self.assertEqual(executor.audit_log, (expected,))
                if label == "A":
                    self.assertEqual(executor.execution_attempts, 1)
                    self.assertEqual(
                        executor.snapshot(), {"resource-a": True, "resource-b": False}
                    )
                else:
                    self.assertEqual(executor.execution_attempts, 0)
                    self.assertEqual(executor.snapshot(), before)

    def test_valid_proposal_just_before_expiry(self):
        executor = build_executor(EXPIRY - TICK)

        self.assertIs(executor.execute(VALID_PROPOSAL), Decision.EXECUTED)
        self.assertEqual(executor.execution_attempts, 1)
        self.assertEqual(executor.snapshot(), {"resource-a": True, "resource-b": False})
        self.assertEqual(executor.audit_log, (Decision.EXECUTED,))

    def test_valid_proposal_exactly_at_expiry(self):
        self.assert_expiry_denial(build_executor(EXPIRY))

    def test_valid_proposal_just_after_expiry(self):
        self.assert_expiry_denial(build_executor(EXPIRY + TICK))

    def test_clock_is_checked_again_on_later_execution(self):
        now = EXPIRY - TICK
        assignment = Assignment("agent-1", "resource-a", "remediate", EXPIRY)
        executor = Executor(assignment, INITIAL_STATE, clock=lambda: now)
        self.assertIs(executor.execute(VALID_PROPOSAL), Decision.EXECUTED)
        before_expiry = executor.snapshot()

        now = EXPIRY
        self.assertIs(executor.execute(VALID_PROPOSAL), Decision.EXPIRED_ASSIGNMENT)
        self.assertEqual(executor.execution_attempts, 1)
        self.assertEqual(executor.snapshot(), before_expiry)
        self.assertEqual(
            executor.audit_log, (Decision.EXECUTED, Decision.EXPIRED_ASSIGNMENT)
        )

    def assert_expiry_denial(self, executor):
        before = executor.snapshot()
        self.assertEqual(before, INITIAL_STATE)

        self.assertIs(executor.execute(VALID_PROPOSAL), Decision.EXPIRED_ASSIGNMENT)
        self.assertEqual(executor.execution_attempts, 0)
        self.assertEqual(executor.snapshot(), before)
        self.assertEqual(executor.audit_log, (Decision.EXPIRED_ASSIGNMENT,))


if __name__ == "__main__":
    unittest.main()
