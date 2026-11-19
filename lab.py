"""Authorize a proposed action and verify the assigned outcome."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


ENABLE_LOGGING = "enable_audit_logging"


def _require_utc(instant: datetime) -> None:
    if instant.utcoffset() != timedelta(0):
        raise ValueError("authorization timestamps must be timezone-aware UTC")


@dataclass(frozen=True)
class Assignment:
    principal: str
    resource: str
    action: str
    expires_at: datetime
    finding_id: str

    def __post_init__(self) -> None:
        _require_utc(self.expires_at)


class Decision(Enum):
    ALLOWED = "assignment_matches"
    INVALID_PROPOSAL = "invalid_proposal"
    WRONG_PRINCIPAL = "wrong_principal"
    WRONG_RESOURCE = "wrong_resource"
    WRONG_ACTION = "wrong_action"
    EXPIRED_ASSIGNMENT = "expired_assignment"


@dataclass(frozen=True)
class Execution:
    decision: Decision
    success_claim: bool | None = None


class Executor:
    def __init__(
        self,
        assignment: Assignment,
        *,
        authenticated_principal: str,
        clock: Callable[[], datetime],
        enable_logging: Callable[[str], bool],
    ) -> None:
        self._assignment = assignment
        self._principal = authenticated_principal
        self._clock = clock
        self._enable_logging = enable_logging
        self._execution_attempts = 0

    @property
    def execution_attempts(self) -> int:
        return self._execution_attempts

    def execute(self, proposal: object) -> Execution:
        """Apply authorization on every call before invoking the write."""
        decision = self._authorize(proposal)
        if decision is not Decision.ALLOWED:
            return Execution(decision)

        self._execution_attempts += 1
        return Execution(decision, self._enable_logging(self._assignment.resource))

    def _authorize(self, proposal: object) -> Decision:
        if (
            type(proposal) is not dict
            or proposal.keys() != {"action", "resource"}
            or any(type(value) is not str or not value.strip() for value in proposal.values())
        ):
            return Decision.INVALID_PROPOSAL

        assignment = self._assignment
        now = self._clock()
        _require_utc(now)
        if now >= assignment.expires_at:
            return Decision.EXPIRED_ASSIGNMENT
        if self._principal != assignment.principal:
            return Decision.WRONG_PRINCIPAL
        if proposal["resource"] != assignment.resource:
            return Decision.WRONG_RESOURCE
        if proposal["action"] != assignment.action or assignment.action != ENABLE_LOGGING:
            return Decision.WRONG_ACTION
        return Decision.ALLOWED


def verify(assignment: Assignment, resource_state: Mapping[str, bool]) -> bool:
    """Check the assigned outcome using observed state."""
    return (
        assignment.action == ENABLE_LOGGING
        and resource_state.get(assignment.resource) is True
    )
