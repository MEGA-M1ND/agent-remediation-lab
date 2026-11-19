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
    Case,
    main,
    run_case,
)
from lab import Decision, Executor, changed_outside_assignment, verify


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

    def test_side_effect_check_compares_all_outside_resources_with_the_baseline(self):
        before = {TARGET: False, OTHER: True, "changed": True, "removed": False}
        after = {TARGET: True, OTHER: True, "changed": False, "added": False}
        self.assertEqual(
            changed_outside_assignment(ASSIGNMENT, before, after),
            ["added", "changed", "removed"],
        )

    def test_execution_failure_is_distinct_from_verification_failure(self):
        with patch("demo.INITIAL_STATE", {OTHER: False}):
            event = run_case(CASES[0])
        self.assertEqual(event["authorization_decision"], "allowed")
        self.assertTrue(event["execution_attempted"])
        self.assertIs(event["executor_success_claim"], False)
        self.assertEqual(event["execution_status"], "failed")
        self.assertIsNone(event["execution_error"])
        self.assertEqual(event["target_verification"], "failed")
        self.assertEqual(event["side_effect_check"], "passed")
        self.assertEqual(event["verification"], "failed")
        self.assertEqual(event["finding_status"], "open")
        self.assertEqual(event["outcome"], "execution_failed")

    def test_demo_emits_json_events_and_summary_counts(self):
        output = io.StringIO()
        with redirect_stdout(output):
            main()
        lines = output.getvalue().splitlines()
        events = [json.loads(line) for line in lines if line.startswith("{")]
        self.assertEqual([event["case"] for event in events], [case.label for case in CASES])
        for event, case in zip(events, CASES):
            with self.subTest(case=case.label):
                self.assertEqual(event["finding_id"], "F-001")
                self.assertEqual(event["authorization_checked_at"], case.now.isoformat())
                self.assertEqual(event["assignment_expires_at"], EXPIRY.isoformat())
        self.assertEqual(
            lines[-1],
            "Summary: 11 cases | verified: 2 | denied: 5 | execution failures: 2 | "
            "verification failures: 2",
        )

    def test_collateral_change_keeps_finding_open_after_a_successful_write(self):
        case = next(case for case in CASES if case.label == "collateral_write")
        event = run_case(case)

        self.assertEqual(event["execution_status"], "succeeded")
        self.assertIs(event["executor_success_claim"], True)
        self.assertEqual(event["execution_attempts"], 1)
        self.assertEqual(event["state_before"], {TARGET: False, OTHER: False})
        self.assertEqual(event["state_after"], {TARGET: True, OTHER: True})
        self.assertEqual(event["target_verification"], "passed")
        self.assertEqual(event["side_effect_check"], "failed")
        self.assertEqual(event["unexpected_side_effects"], [OTHER])
        self.assertEqual(event["verification"], "failed")
        self.assertEqual(event["outcome"], "verification_failed")
        self.assertEqual(event["finding_status"], "open")

    def test_writer_exceptions_emit_events_and_keep_the_finding_open(self):
        output = io.StringIO()
        with redirect_stdout(output):
            main()
        events = {}
        for line in output.getvalue().splitlines():
            if line.startswith("{"):
                event = json.loads(line)
                events[event["case"]] = event

        for label, target_changed, message in (
            ("exception_before_write", False, "writer failed before changing state"),
            ("exception_after_write", True, "writer failed after changing target"),
        ):
            with self.subTest(case=label):
                event = events[label]
                target_result = "passed" if target_changed else "failed"
                self.assertEqual(event["authorization_decision"], "allowed")
                self.assertEqual(event["authorization_reason"], "assignment_matches")
                self.assertTrue(event["execution_attempted"])
                self.assertEqual(event["execution_attempts"], 1)
                self.assertEqual(event["execution_status"], "failed")
                self.assertIsNone(event["executor_success_claim"])
                self.assertEqual(
                    event["execution_error"], {"type": "RuntimeError", "message": message}
                )
                self.assertEqual(event["state_before"], {TARGET: False, OTHER: False})
                self.assertEqual(event["state_after"], {TARGET: target_changed, OTHER: False})
                self.assertEqual(event["target_verification"], target_result)
                self.assertEqual(event["side_effect_check"], "passed")
                self.assertEqual(event["unexpected_side_effects"], [])
                self.assertEqual(event["verification"], target_result)
                self.assertEqual(event["outcome"], "execution_failed")
                self.assertEqual(event["finding_status"], "open")

    def test_event_represents_checks_that_did_not_run(self):
        event = run_case(Case("invalid", None))
        self.assertEqual(event["authorization_reason"], "invalid_proposal")
        self.assertIsNone(event["authorization_checked_at"])
        self.assertEqual(event["assignment_expires_at"], EXPIRY.isoformat())
        self.assertEqual(event["execution_status"], "not_run")
        self.assertEqual(event["target_verification"], "not_run")
        self.assertEqual(event["side_effect_check"], "not_run")
        self.assertIsNone(event["unexpected_side_effects"])

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
        self.assertEqual(result.authorization_checked_at, now)
        self.assertIsNone(result.success_claim)
        self.assertEqual(self.executor.execution_attempts, 0)
        self.assertEqual(self.state, before)
        self.write.assert_not_called()

    def test_authorization_records_the_single_clock_reading_used(self):
        checked_at = EXPIRY - TICK
        clock = Mock(side_effect=[checked_at, EXPIRY])
        executor = Executor(
            ASSIGNMENT,
            authenticated_principal=PRINCIPAL,
            clock=clock,
            enable_logging=self.write,
        )

        result = executor.execute(VALID_PROPOSAL)

        self.assertIs(result.decision, Decision.ALLOWED)
        self.assertEqual(result.authorization_checked_at, checked_at)
        clock.assert_called_once_with()

    def test_writer_keyboard_interrupt_propagates(self):
        self.write.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.executor.execute(VALID_PROPOSAL)
        self.assertEqual(self.executor.execution_attempts, 1)

    def test_clock_error_propagates_without_calling_writer(self):
        executor = Executor(
            ASSIGNMENT,
            authenticated_principal=PRINCIPAL,
            clock=Mock(side_effect=RuntimeError("clock failure")),
            enable_logging=self.write,
        )
        with self.assertRaisesRegex(RuntimeError, "clock failure"):
            executor.execute(VALID_PROPOSAL)
        self.assertEqual(executor.execution_attempts, 0)
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
