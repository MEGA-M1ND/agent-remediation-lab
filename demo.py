"""Run deterministic fixtures and emit one JSON event per case."""

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from lab import (
    ENABLE_LOGGING,
    Assignment,
    Decision,
    Executor,
    changed_outside_assignment,
    verify,
)


FINDING = {
    "id": "F-001",
    "resource": "demo-audit-store",
    "report": "Audit logging is disabled",
}
TARGET = "demo-audit-store"
OTHER = "demo-archive"
PRINCIPAL = "remediation-worker"
EXPIRY = datetime(2030, 1, 1, tzinfo=timezone.utc)
TICK = timedelta(microseconds=1)
ASSIGNMENT = Assignment(PRINCIPAL, TARGET, ENABLE_LOGGING, EXPIRY, "F-001")
INITIAL_STATE = {TARGET: False, OTHER: False}
VALID_PROPOSAL = {"action": ENABLE_LOGGING, "resource": TARGET}


@dataclass(frozen=True)
class Case:
    label: str
    proposal: object
    principal: str = PRINCIPAL
    drop_write: bool = False
    now: datetime = EXPIRY - TICK
    writer_fault: str | None = None


CASES = (
    Case("A", VALID_PROPOSAL),
    Case("B", {**VALID_PROPOSAL, "resource": OTHER}),
    Case("C", {**VALID_PROPOSAL, "action": "disable_audit_logging"}),
    Case("D", VALID_PROPOSAL, drop_write=True),
    Case("E", VALID_PROPOSAL, principal="other-worker"),
    Case("before_expiry", VALID_PROPOSAL),
    Case("at_expiry", VALID_PROPOSAL, now=EXPIRY),
    Case("after_expiry", VALID_PROPOSAL, now=EXPIRY + TICK),
    Case("collateral_write", VALID_PROPOSAL, writer_fault="collateral_write"),
    Case("exception_before_write", VALID_PROPOSAL, writer_fault="exception_before_write"),
    Case("exception_after_write", VALID_PROPOSAL, writer_fault="exception_after_write"),
)

# Expected reason, success claim, target state, and archive state.
EXPECTED = {
    "A": ("assignment_matches", True, True, False),
    "B": ("wrong_resource", None, False, False),
    "C": ("wrong_action", None, False, False),
    "D": ("assignment_matches", True, False, False),
    "E": ("wrong_principal", None, False, False),
    "before_expiry": ("assignment_matches", True, True, False),
    "at_expiry": ("expired_assignment", None, False, False),
    "after_expiry": ("expired_assignment", None, False, False),
    "collateral_write": ("assignment_matches", True, True, True),
    "exception_before_write": ("assignment_matches", None, False, False),
    "exception_after_write": ("assignment_matches", None, True, False),
}
EXPECTED_ERRORS = {
    "exception_before_write": {
        "type": "RuntimeError",
        "message": "writer failed before changing state",
    },
    "exception_after_write": {
        "type": "RuntimeError",
        "message": "writer failed after changing target",
    },
}


def run_case(case: Case) -> dict:
    resource_state = INITIAL_STATE.copy()

    def enable_logging(resource: str) -> bool:
        if case.writer_fault == "exception_before_write":
            raise RuntimeError("writer failed before changing state")
        if resource not in resource_state:
            return False
        if not case.drop_write:
            resource_state[resource] = True
        if case.writer_fault == "collateral_write":
            resource_state[OTHER] = True
        if case.writer_fault == "exception_after_write":
            raise RuntimeError("writer failed after changing target")
        return True

    executor = Executor(
        ASSIGNMENT,
        authenticated_principal=case.principal,
        clock=lambda: case.now,
        enable_logging=enable_logging,
    )
    before = resource_state.copy()
    result = executor.execute(case.proposal)
    after = resource_state.copy()
    allowed = result.decision is Decision.ALLOWED
    attempted = executor.execution_attempts > 0
    execution_status = "not_run"
    verification = "not_run"
    target_verification = "not_run"
    side_effect_check = "not_run"
    unexpected_side_effects = None
    if attempted:
        execution_status = "succeeded" if result.success_claim is True else "failed"
        target_ok = verify(ASSIGNMENT, after)
        unexpected_side_effects = changed_outside_assignment(ASSIGNMENT, before, after)
        target_verification = "passed" if target_ok else "failed"
        side_effect_check = "failed" if unexpected_side_effects else "passed"
        verification = "passed" if target_ok and not unexpected_side_effects else "failed"

    if not allowed:
        outcome = "denied"
    elif execution_status != "succeeded":
        outcome = "execution_failed"
    elif verification == "passed":
        outcome = "verified"
    else:
        outcome = "verification_failed"

    proposal = case.proposal if type(case.proposal) is dict else {}
    checked_at = result.authorization_checked_at
    execution_error = None
    if result.error_type is not None:
        execution_error = {"type": result.error_type, "message": result.error_message}

    return {
        "case": case.label,
        "finding_id": ASSIGNMENT.finding_id,
        "ticket": FINDING.copy(),
        "authenticated_principal": case.principal,
        "proposed_action": proposal.get("action"),
        "proposed_target": proposal.get("resource"),
        "assigned_action": ASSIGNMENT.action,
        "assigned_target": ASSIGNMENT.resource,
        "authorization_decision": "allowed" if allowed else "denied",
        "authorization_reason": result.decision.value,
        "authorization_checked_at": checked_at.isoformat() if checked_at is not None else None,
        "assignment_expires_at": ASSIGNMENT.expires_at.isoformat(),
        "execution_attempted": attempted,
        "execution_attempts": executor.execution_attempts,
        "execution_status": execution_status,
        "executor_success_claim": result.success_claim,
        "execution_error": execution_error,
        "state_before": before,
        "state_after": after,
        "target_verification": target_verification,
        "side_effect_check": side_effect_check,
        "unexpected_side_effects": unexpected_side_effects,
        "verification": verification,
        "finding_status": "verified" if outcome == "verified" else "open",
        "outcome": outcome,
    }


def check_expected(event: dict) -> None:
    label = event["case"]
    reason, claim, target_state, archive_state = EXPECTED[label]
    allowed = reason == "assignment_matches"
    verification = "not_run"
    target_verification = "not_run"
    side_effect_check = "not_run"
    execution_status = "not_run"
    unexpected_side_effects = None
    if allowed:
        verification = "passed" if target_state and not archive_state else "failed"
        target_verification = "passed" if target_state else "failed"
        side_effect_check = "failed" if archive_state else "passed"
        execution_status = "succeeded" if claim is True else "failed"
        unexpected_side_effects = [OTHER] if archive_state else []
    expected = {
        "authorization_decision": "allowed" if allowed else "denied",
        "authorization_reason": reason,
        "execution_attempted": allowed,
        "execution_attempts": int(allowed),
        "execution_status": execution_status,
        "executor_success_claim": claim,
        "execution_error": EXPECTED_ERRORS.get(label),
        "state_before": INITIAL_STATE,
        "state_after": {TARGET: target_state, OTHER: archive_state},
        "verification": verification,
        "target_verification": target_verification,
        "side_effect_check": side_effect_check,
        "unexpected_side_effects": unexpected_side_effects,
        "finding_status": "verified" if claim is True and verification == "passed" else "open",
    }
    for field, value in expected.items():
        if event[field] != value:
            raise SystemExit(
                f"{event['case']}: expected {field}={value!r}, got {event[field]!r}"
            )


def main() -> None:
    counts: Counter[str] = Counter()
    for case in CASES:
        event = run_case(case)
        print(json.dumps(event))
        check_expected(event)
        counts[event["outcome"]] += 1
        print(
            f"{case.label}: {event['outcome']} "
            f"({event['authorization_reason']}), finding {event['finding_status']}"
        )

    print(
        f"Summary: {counts.total()} cases | verified: {counts['verified']} | "
        f"denied: {counts['denied']} | execution failures: {counts['execution_failed']} | "
        f"verification failures: {counts['verification_failed']}"
    )


if __name__ == "__main__":
    main()
