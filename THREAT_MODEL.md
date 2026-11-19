# Threat model

## Assets and actors

The assets are audit-logging state on `demo-audit-store` and `demo-archive`, the status of finding F-001, and the integrity of the decision and verification records. The actors are the proposed-action sender, the authenticated worker represented by the trusted harness, the executor that authorizes writes, and the verifier that checks observed state.

## Trust boundaries

- The sender controls the ticket and proposal. The proposal schema accepts only the action and resource. Extra fields and malformed values are rejected. Apparent identities, deadlines, or fault controls supplied in a proposal cannot change authorization.
- The harness supplies the authenticated principal, the assignment, and a fixed clock for each fixture. The assignment carries the UTC deadline, scopes `remediation-worker` to `enable_audit_logging` on `demo-audit-store`, and binds the result to F-001. Ticket data is shown in the event for context.
- The public execution boundary reads the trusted clock once per well-formed proposal. The event records that reading and the assignment expiry as UTC ISO 8601 strings. A malformed proposal has a `null` check time. An otherwise valid proposal is admitted only before expiry. At or after expiry, `expired_assignment` leaves both resources unchanged. Expiry governs admission. A write that has started can finish after expiry. Naive timestamps and nonzero UTC offsets cause a configuration error before any write.
- The writer can drop a write, change a second resource, or raise before or after changing state. The executor records ordinary writer exceptions with their type and message while retaining the authorization decision and attempt count. Interrupts and errors outside the writer call propagate.
- The harness takes trusted snapshots of all simulated resources before and after execution. After any write attempt, the verifier checks the assigned resource's intended state and looks for changed, added, or removed resources outside the assignment. A denial skips both checks. F-001 closes only when the writer reports success and both state checks pass.

## Fixture coverage

| Case | Control exercised | Result |
| --- | --- | --- |
| A | Valid principal, scope, and action | Assigned logging enabled and F-001 verified |
| B | Proposal names the other resource | Denied before any write |
| C | Proposal names an unapproved action | Denied before any write |
| D | Writer reports success after dropping the requested write | Verification fails and F-001 stays open |
| E | Trusted context supplies a different authenticated principal | Denied before any write |
| `collateral_write` | Writer changes the target and archive and reports success | Target passes and the unexpected archive change keeps F-001 open |
| `exception_before_write` | Writer raises before changing state | Target check fails, the error is recorded, and F-001 stays open |
| `exception_after_write` | Writer changes the target and raises | Observed state passes both checks, the error is recorded, and F-001 stays open |

Every fixture starts with logging disabled on both resources. The expiry fixtures check the instant before the deadline, equality, and the instant after it.

## Remaining limitations

This is a deterministic, in-process simulation. Its results show the behavior of these fixtures. The harness stands in for identity authentication, trusted assignment issuance, and trusted time. A hostile process with access to the writer, the verifier, or the backing state falls outside this model. LLM prompt-injection resistance, production cloud enforcement, and durable audit storage are future work. Before-and-after snapshots detect differences in the observed resource inventory. They miss transient changes that are reverted between reads, later writes, and effects outside that inventory. The lab has no rollback, so a resource can remain changed after an execution failure. A valid proposal can be repeated before its assignment expires.
