# Threat model

The lab protects the state of two in-memory resources and the integrity of the executor's decision and attempt records. The executor trusts the harness to supply the assignment, its UTC expiry, and the clock. It treats proposal fields as untrusted input. The assignee field is a claim evaluated against the assignment. A production caller would need an authenticated identity at this boundary.

Every public execution call samples the injected clock and denies expired assignments before attempting to change either resource. The permitted interval ends at the expiry instant. Proposals have no fields for authorization timestamps or clocks. The executor records `expired_assignment` separately from assignee, resource, and action denials. Every denial preserves the state of both resources and does not increment the execution-attempt counter.

A process or harness that can alter the trusted clock or replace the executor can invalidate the result. A production system would need trusted time, protected assignment provenance, and durable audit storage. This lab models a synchronous, in-memory operation, so expiry governs admission at the execution call. A valid proposal may be repeated before expiry.
