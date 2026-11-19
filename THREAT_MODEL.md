# Threat model

## Assets and actors

The assets are audit-logging state on `demo-audit-store` and `demo-archive`, the status of finding F-001, and the integrity of the decision and verification records. The actors are the proposed-action sender, the authenticated worker represented by the trusted harness, the executor that authorizes writes, and the verifier that checks observed state.

## Trust boundaries

- The sender controls the ticket and proposal. The proposal schema accepts only the action and resource. Extra fields and malformed values are rejected. Apparent identities, deadlines, or fault controls supplied in a proposal cannot change authorization.
- The harness supplies the authenticated principal, assignment, UTC deadline, and clock. The fixed assignment scopes `remediation-worker` to `enable_audit_logging` on `demo-audit-store` and binds the result to F-001. Ticket data is shown in the event for context.
- The public execution boundary authorizes every request before it invokes the simulated writer. A valid request at or after expiry is denied as `expired_assignment`. The writer can claim success while dropping the write, as the trusted harness demonstrates in D.
- The verifier receives the trusted assignment and directly reads the shared in-memory state. It checks audit logging on the assigned target after a success claim. A denial or reported execution failure skips verification. Only successful state verification marks F-001 verified.

## Fixture coverage

| Case | Control exercised | Result |
| --- | --- | --- |
| A | Valid principal, scope, and action | Assigned logging enabled and F-001 verified |
| B | Proposal names the other resource | Denied before any write |
| C | Proposal names an unapproved action | Denied before any write |
| D | Writer reports success after dropping the requested write | Verification fails and F-001 stays open |
| E | Trusted context supplies a different authenticated principal | Denied before any write |

All five cases begin with logging disabled on both resources. The archive remains unchanged in every case. The expiry fixtures check the instant before the deadline, equality, and the instant after it.

## Remaining limitations

This is a deterministic, in-process simulation. Its results show the behavior of these fixtures. The harness stands in for identity authentication, trusted assignment issuance, and trusted time. A hostile process with access to the writer, the verifier, or the backing state falls outside this model. LLM prompt-injection resistance, production cloud enforcement, and durable audit storage are future work. Verification is a point-in-time check, and a valid proposal can be repeated before its assignment expires.
