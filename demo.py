"""Run deterministic fixtures and emit one JSON event per case."""

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from lab import ENABLE_LOGGING, Assignment, Decision, Executor, verify


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
    proposal: dict[str, str]
    principal: str = PRINCIPAL
    drop_write: bool = False
    now: datetime = EXPIRY - TICK


CASES = (
    Case("A", VALID_PROPOSAL),
    Case("B", {**VALID_PROPOSAL, "resource": OTHER}),
    Case("C", {**VALID_PROPOSAL, "action": "disable_audit_logging"}),
    Case("D", VALID_PROPOSAL, drop_write=True),
    Case("E", VALID_PROPOSAL, principal="other-worker"),
    Case("before_expiry", VALID_PROPOSAL),
    Case("at_expiry", VALID_PROPOSAL, now=EXPIRY),
    Case("after_expiry", VALID_PROPOSAL, now=EXPIRY + TICK),
)

# Expected reason, success claim, verification, finding status, and target state.
EXPECTED = {
    "A": ("assignment_matches", True, "passed", "verified", True),
    "B": ("wrong_resource", None, "not_run", "open", False),
    "C": ("wrong_action", None, "not_run", "open", False),
    "D": ("assignment_matches", True, "failed", "open", False),
    "E": ("wrong_principal", None, "not_run", "open", False),
    "before_expiry": ("assignment_matches", True, "passed", "verified", True),
    "at_expiry": ("expired_assignment", None, "not_run", "open", False),
    "after_expiry": ("expired_assignment", None, "not_run", "open", False),
}


def run_case(case: Case) -> dict:
    resource_state = INITIAL_STATE.copy()

    def enable_logging(resource: str) -> bool:
        if resource not in resource_state:
            return False
        if not case.drop_write:
            resource_state[resource] = True
        return True

    executor = Executor(
        ASSIGNMENT,
        authenticated_principal=case.principal,
        clock=lambda: case.now,
        enable_logging=enable_logging,
    )
    before = resource_state.copy()
    result = executor.execute(case.proposal)
    allowed = result.decision is Decision.ALLOWED
    verification = "not_run"
    if result.success_claim is True:
        verification = "passed" if verify(ASSIGNMENT, resource_state) else "failed"

    if not allowed:
        outcome = "denied"
    elif result.success_claim is not True:
        outcome = "execution_failed"
    elif verification == "failed":
        outcome = "verification_failed"
    else:
        outcome = "verified"

    return {
        "case": case.label,
        "finding_id": ASSIGNMENT.finding_id,
        "ticket": FINDING.copy(),
        "authenticated_principal": case.principal,
        "proposed_action": case.proposal.get("action"),
        "proposed_target": case.proposal.get("resource"),
        "assigned_action": ASSIGNMENT.action,
        "assigned_target": ASSIGNMENT.resource,
        "authorization_decision": "allowed" if allowed else "denied",
        "authorization_reason": result.decision.value,
        "execution_attempted": executor.execution_attempts > 0,
        "execution_attempts": executor.execution_attempts,
        "executor_success_claim": result.success_claim,
        "state_before": before,
        "state_after": resource_state.copy(),
        "verification": verification,
        "finding_status": "verified" if outcome == "verified" else "open",
        "outcome": outcome,
    }


def check_expected(event: dict) -> None:
    reason, claim, verification, status, target_state = EXPECTED[event["case"]]
    expected = {
        "authorization_decision": "denied" if claim is None else "allowed",
        "authorization_reason": reason,
        "execution_attempted": claim is not None,
        "execution_attempts": int(claim is not None),
        "executor_success_claim": claim,
        "state_before": INITIAL_STATE,
        "state_after": {TARGET: target_state, OTHER: False},
        "verification": verification,
        "finding_status": status,
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
