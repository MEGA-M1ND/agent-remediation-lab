"""Deterministic harness for the Agent Remediation Lab."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from lab import Assignment, Decision, Executor, Proposal


EXPIRY = datetime(2030, 1, 1, tzinfo=timezone.utc)
TICK = timedelta(microseconds=1)
VALID_PROPOSAL = Proposal("agent-1", "resource-a", "remediate")
INITIAL_STATE = {"resource-a": False, "resource-b": False}


def build_executor(now: datetime) -> Executor:
    assignment = Assignment(
        assignee="agent-1",
        resource="resource-a",
        action="remediate",
        expires_at=EXPIRY,
    )
    return Executor(assignment, INITIAL_STATE, clock=lambda: now)


CASES = (
    ("A", VALID_PROPOSAL, Decision.EXECUTED),
    ("B", replace(VALID_PROPOSAL, resource="resource-b"), Decision.WRONG_RESOURCE),
    ("C", replace(VALID_PROPOSAL, action="delete"), Decision.WRONG_ACTION),
    ("D", replace(VALID_PROPOSAL, assignee="agent-2"), Decision.WRONG_ASSIGNEE),
    ("E", replace(VALID_PROPOSAL, resource="missing"), Decision.WRONG_RESOURCE),
)


def main() -> None:
    for label, proposal, expected in CASES:
        executor = build_executor(EXPIRY - TICK)
        run_case(label, executor, proposal, expected)

    for label, instant, expected in (
        ("Just before expiry", EXPIRY - TICK, Decision.EXECUTED),
        ("Exactly at expiry", EXPIRY, Decision.EXPIRED_ASSIGNMENT),
        ("Just after expiry", EXPIRY + TICK, Decision.EXPIRED_ASSIGNMENT),
    ):
        run_case(label, build_executor(instant), VALID_PROPOSAL, expected)


def run_case(
    label: str, executor: Executor, proposal: Proposal, expected: Decision
) -> None:
    before = executor.snapshot()
    decision = executor.execute(proposal)
    expected_state = before.copy()
    should_execute = expected is Decision.EXECUTED
    if should_execute:
        expected_state[proposal.resource] = True
    if (
        decision is not expected
        or executor.execution_attempts != int(should_execute)
        or executor.snapshot() != expected_state
        or executor.audit_log != (expected,)
    ):
        raise RuntimeError(f"{label} failed with decision {decision.value}")
    print(
        f"{label}: {decision.value}, attempts={executor.execution_attempts}, "
        f"state={executor.snapshot()}"
    )


if __name__ == "__main__":
    main()
