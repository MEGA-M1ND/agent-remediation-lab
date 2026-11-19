import io
import json
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import timedelta, timezone
from unittest.mock import Mock, patch

from demo import (
    ASSIGNMENT,
    CASES,
    EXPIRY,
    INITIAL_STATE,
    OTHER,
    PRINCIPAL,
    TARGET,
    TICK,
    VALID_PROPOSAL,
    main,
    run_case,
)
from lab import Decision, Executor, verify


class WorkflowTests(unittest.TestCase):
    def test_cases_a_through_e(self):
        expectations = {
            "A": ("allowed", "assignment_matches", 1, True, "passed", "verified", True),
            "B": ("denied", "wrong_resource", 0, None, "not_run", "open", False),
            "C": ("denied", "wrong_action", 0, None, "not_run", "open", False),
            "D": ("allowed", "assignment_matches", 1, True, "failed", "open", False),
            "E": ("denied", "wrong_principal", 0, None, "not_run", "open", False),
        }
        fields = (
            "authorization_decision",
            "authorization_reason",
            "execution_attempts",
            "executor_success_claim",
            "verification",
            "finding_status",
        )
        for case in CASES[:5]:
            with self.subTest(case=case.label):
                *expected_result, target_state = expectations[case.label]
                event = run_case(case)
                self.assertEqual([event[field] for field in fields], expected_result)
                self.assertEqual(event["state_before"], {TARGET: False, OTHER: False})
                self.assertEqual(event["state_after"], {TARGET: target_state, OTHER: False})

    def test_verifier_reads_only_the_assigned_resource(self):
        self.assertFalse(verify(ASSIGNMENT, {TARGET: False, OTHER: True}))
        self.assertFalse(verify(ASSIGNMENT, {OTHER: True}))
        self.assertTrue(verify(ASSIGNMENT, {TARGET: True, OTHER: False}))

    def test_execution_failure_is_distinct_from_verification_failure(self):
        with patch("demo.INITIAL_STATE", {OTHER: False}):
            event = run_case(CASES[0])
        self.assertEqual(event["authorization_decision"], "allowed")
        self.assertTrue(event["execution_attempted"])
        self.assertIs(event["executor_success_claim"], False)
        self.assertEqual(event["verification"], "not_run")
        self.assertEqual(event["finding_status"], "open")
        self.assertEqual(event["outcome"], "execution_failed")

    def test_demo_emits_json_events_and_summary_counts(self):
        output = io.StringIO()
        with redirect_stdout(output):
            main()
        lines = output.getvalue().splitlines()
        events = [json.loads(line) for line in lines if line.startswith("{")]
        self.assertEqual([event["case"] for event in events], [case.label for case in CASES])
        self.assertTrue(all(event["finding_id"] == "F-001" for event in events))
        self.assertEqual(
            lines[-1],
            "Summary: 8 cases | verified: 2 | denied: 5 | execution failures: 0 | "
            "verification failures: 1",
        )

    def test_demo_exits_nonzero_when_a_case_differs_from_expectations(self):
        with patch("demo.verify", return_value=False), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(SystemExit, "A: expected verification='passed'"):
                main()


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.state = INITIAL_STATE.copy()
        self.now = EXPIRY - TICK
        self.write = Mock(side_effect=self.enable_logging)
        self.executor = self.make_executor()

    def make_executor(self, principal=PRINCIPAL):
        return Executor(
            ASSIGNMENT,
            authenticated_principal=principal,
            clock=lambda: self.now,
            enable_logging=self.write,
        )

    def enable_logging(self, resource):
        self.state[resource] = True
        return True

    def test_invalid_proposals_never_reach_the_writer(self):
        for proposal in (
            None,
            {"action": VALID_PROPOSAL["action"]},
            {**VALID_PROPOSAL, "resource": 123},
            {**VALID_PROPOSAL, "action": " "},
            {**VALID_PROPOSAL, "principal": PRINCIPAL},
            {**VALID_PROPOSAL, "drop_write": True},
            {**VALID_PROPOSAL, "expires_at": EXPIRY.isoformat()},
            {**VALID_PROPOSAL, "now": (EXPIRY - TICK).isoformat()},
        ):
            with self.subTest(proposal=proposal):
                result = self.executor.execute(proposal)
                self.assertIs(result.decision, Decision.INVALID_PROPOSAL)
                self.assertIsNone(result.success_claim)
                self.assertEqual(self.executor.execution_attempts, 0)
                self.assertEqual(self.state, INITIAL_STATE)
                self.write.assert_not_called()

    def test_scope_and_identity_denials_never_reach_the_writer(self):
        for index, decision in (
            (1, Decision.WRONG_RESOURCE),
            (2, Decision.WRONG_ACTION),
            (4, Decision.WRONG_PRINCIPAL),
        ):
            case = CASES[index]
            with self.subTest(case=case.label):
                executor = self.make_executor(case.principal)
                self.assertIs(executor.execute(case.proposal).decision, decision)
                self.assertEqual(executor.execution_attempts, 0)
                self.assertEqual(self.state, INITIAL_STATE)
                self.write.assert_not_called()

    def test_valid_proposal_just_before_expiry(self):
        result = self.executor.execute(VALID_PROPOSAL)

        self.assertIs(result.decision, Decision.ALLOWED)
        self.assertIs(result.success_claim, True)
        self.assertEqual(self.executor.execution_attempts, 1)
        self.assertEqual(self.state, {TARGET: True, OTHER: False})
        self.write.assert_called_once_with(TARGET)

    def test_valid_proposal_exactly_at_expiry(self):
        self.assert_expiry_denial(EXPIRY)

    def test_valid_proposal_just_after_expiry(self):
        self.assert_expiry_denial(EXPIRY + TICK)

    def assert_expiry_denial(self, now):
        before = self.state.copy()
        self.now = now
        result = self.executor.execute(VALID_PROPOSAL)

        self.assertIs(result.decision, Decision.EXPIRED_ASSIGNMENT)
        self.assertEqual(result.decision.value, "expired_assignment")
        self.assertIsNone(result.success_claim)
        self.assertEqual(self.executor.execution_attempts, 0)
        self.assertEqual(self.state, before)
        self.write.assert_not_called()

    def test_assignment_rejects_naive_and_non_utc_expiry(self):
        for expiry in (
            EXPIRY.replace(tzinfo=None),
            EXPIRY.astimezone(timezone(timedelta(hours=1))),
        ):
            with self.subTest(expiry=expiry):
                with self.assertRaisesRegex(ValueError, "timezone-aware UTC"):
                    replace(ASSIGNMENT, expires_at=expiry)

    def test_invalid_clock_readings_never_reach_the_writer(self):
        before = self.state.copy()
        for now in (
            self.now.replace(tzinfo=None),
            self.now.astimezone(timezone(timedelta(hours=1))),
        ):
            with self.subTest(now=now):
                self.now = now
                with self.assertRaisesRegex(ValueError, "timezone-aware UTC"):
                    self.executor.execute(VALID_PROPOSAL)
                self.assertEqual(self.executor.execution_attempts, 0)
                self.assertEqual(self.state, before)
                self.write.assert_not_called()

    def test_clock_is_checked_again_on_later_execution(self):
        self.assertIs(self.executor.execute(VALID_PROPOSAL).decision, Decision.ALLOWED)
        self.now = EXPIRY

        self.assertIs(
            self.executor.execute(VALID_PROPOSAL).decision, Decision.EXPIRED_ASSIGNMENT
        )
        self.assertEqual(self.executor.execution_attempts, 1)
        self.assertEqual(self.state, {TARGET: True, OTHER: False})
        self.write.assert_called_once_with(TARGET)


if __name__ == "__main__":
    unittest.main()
