"""An in-memory executor for a single trusted remediation assignment."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


def _require_utc(instant: datetime) -> None:
    if instant.utcoffset() != timedelta(0):
        raise ValueError("authorization timestamps must be timezone-aware UTC")


@dataclass(frozen=True)
class Assignment:
    assignee: str
    resource: str
    action: str
    expires_at: datetime

    def __post_init__(self) -> None:
        _require_utc(self.expires_at)


@dataclass(frozen=True)
class Proposal:
    assignee: str
    resource: str
    action: str


class Decision(Enum):
    EXECUTED = "executed"
    WRONG_ASSIGNEE = "wrong_assignee"
    WRONG_RESOURCE = "wrong_resource"
    WRONG_ACTION = "wrong_action"
    EXPIRED_ASSIGNMENT = "expired_assignment"
    UNKNOWN_RESOURCE = "unknown_resource"


class Executor:
    def __init__(
        self,
        assignment: Assignment,
        resources: Mapping[str, bool],
        clock: Callable[[], datetime],
    ) -> None:
        self._assignment = assignment
        self._resources = dict(resources)
        self._clock = clock
        self._audit_log: list[Decision] = []
        self._execution_attempts = 0

    @property
    def execution_attempts(self) -> int:
        return self._execution_attempts

    @property
    def audit_log(self) -> tuple[Decision, ...]:
        return tuple(self._audit_log)

    def snapshot(self) -> dict[str, bool]:
        """Return a copy of both resource states for inspection."""
        return self._resources.copy()

    def execute(self, proposal: Proposal) -> Decision:
        """Check authorization and record the outcome at the public boundary."""
        decision = self._authorize(proposal)
        if decision is Decision.EXECUTED:
            self._execution_attempts += 1
            self._resources[proposal.resource] = True
        self._audit_log.append(decision)
        return decision

    def _authorize(self, proposal: Proposal) -> Decision:
        now = self._clock()
        _require_utc(now)
        assignment = self._assignment
        if now >= assignment.expires_at:
            return Decision.EXPIRED_ASSIGNMENT
        if proposal.assignee != assignment.assignee:
            return Decision.WRONG_ASSIGNEE
        if proposal.resource != assignment.resource:
            return Decision.WRONG_RESOURCE
        if proposal.action != assignment.action or proposal.action != "remediate":
            return Decision.WRONG_ACTION
        if proposal.resource not in self._resources:
            return Decision.UNKNOWN_RESOURCE
        return Decision.EXECUTED
