# Agent Remediation Lab

Agent Remediation Lab demonstrates how an executor authorizes remediation against a trusted assignment. The demo uses two in-memory resources and Python 3.10 or later. It has no third-party runtime dependencies.

Run the demo and test suite from the repository root.

```sh
python3 demo.py
python3 -m unittest discover -v
```

The harness supplies a frozen assignment with a timezone-aware UTC expiry and injects a fixed UTC clock. A proposal carries an assignee, resource, and action. At each call to `Executor.execute()`, the executor reads its trusted clock and compares it with the assignment expiry. An otherwise valid proposal can execute while `now < expires_at`. At equality or later, the executor records `expired_assignment`, makes zero execution attempts for that call, and leaves both resources unchanged.

| Case | Proposal | Result before expiry |
| --- | --- | --- |
| A | Assigned agent, assigned resource, permitted action | Executes on resource A |
| B | Targets resource B | `wrong_resource` |
| C | Requests an unsupported action | `wrong_action` |
| D | Claims another assignee | `wrong_assignee` |
| E | Targets a resource absent from the lab | `wrong_resource` |

The demo and tests also exercise a valid proposal one microsecond before expiry, at expiry, and one microsecond after expiry.

## CI/CD

GitHub Actions runs the demo and full test suite on pull requests to `main` and pushes to `main`. Successful `main` builds publish a ZIP of the verified demo, tests, and documentation as a workflow artifact. The delivery job checks that the demo runs from the archive.

See the [threat model](THREAT_MODEL.md) for trust boundaries and scope.
