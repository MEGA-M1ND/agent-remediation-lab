# Agent Remediation Lab

Can an executor correctly authorize a fix and independently verify that it worked? This deterministic simulation answers that question for a synthetic finding, **F-001**, which reports disabled audit logging on `demo-audit-store`. Both that resource and `demo-archive` start with logging disabled in every case.

## Run the lab

Use Python 3.11 or later from the repository root. The lab uses the standard library.

**Windows (PowerShell)**

```powershell
python demo.py
python -m unittest discover -v
```

**macOS and Linux**

```sh
python3 demo.py
python3 -m unittest discover -v
```

## Predict the outcomes first

Read the five inputs below and predict which calls will reach the write operation, which resources will change, and which findings will end up verified. For D, decide whether the executor's success claim is enough to close the finding. Then run the demo and compare your predictions with `execution_attempted`, `state_after`, and `verification` in each JSON event.

| Case | Input |
| --- | --- |
| A | The assigned worker asks to enable logging on the assigned store. |
| B | The assigned worker asks to enable logging on the archive. |
| C | The assigned worker asks to disable logging on the assigned store. |
| D | The assigned worker submits A's proposal. The harness makes the write report success while leaving storage untouched. |
| E | A different authenticated worker submits A's proposal. |

## Expected output

The demo emits a JSON event and a readable line for each case. The readable lines are:

```text
A: verified (assignment_matches), finding verified
B: denied (wrong_resource), finding open
C: denied (wrong_action), finding open
D: verification_failed (assignment_matches), finding open
E: denied (wrong_principal), finding open
before_expiry: verified (assignment_matches), finding verified
at_expiry: denied (expired_assignment), finding open
after_expiry: denied (expired_assignment), finding open
Summary: 8 cases | verified: 2 | denied: 5 | execution failures: 0 | verification failures: 1
```

The summary counts come from the actual events. The demo exits with a nonzero status if a case differs from its expected outcome.

## Authorization expiry

The trusted assignment carries the UTC deadline. The harness injects a fixed UTC clock for each fixture. The executor reads that clock on each well-formed call to `execute()`. Proposals contain only the action and resource.

| Clock reading for an otherwise valid proposal | Expected result |
| --- | --- |
| One microsecond before expiry | Allowed. The assigned resource changes and the archive stays unchanged. |
| Exactly at expiry | `expired_assignment`. Zero execution attempts and both resources unchanged. |
| One microsecond after expiry | `expired_assignment`. Zero execution attempts and both resources unchanged. |

## Walkthrough

1. In `demo.py`, the harness loads the ticket and supplies an authenticated principal, a trusted assignment, a fixed UTC clock, and fresh state for both resources. The ticket provides context. The trusted assignment binds F-001 to the assigned action and resource.
2. In `lab.py`, `Executor.execute()` validates that the proposal contains two nonempty strings, `action` and `resource`. It checks the trusted principal, assigned scope, and UTC deadline before it calls the write operation.
3. After a reported success, `verify()` reads the state of the resource named in the trusted assignment. Only a passed verification closes the finding. The harness leaves the finding open after a denial, reported execution failure, or verification failure and records each outcome separately.
4. `tests/test_lab.py` checks the A–E fixtures, proposal validation, and expiry boundaries. Its write spy confirms that a denied call never reaches the write operation.

These fixtures model a deterministic in-memory workflow. Real identity authentication, hostile process isolation, LLM prompt-injection resistance, and production cloud enforcement remain future work. See [the threat model](THREAT_MODEL.md).

GitHub Actions runs both commands with Python 3.11 on Windows, macOS, and Linux for pull requests and pushes to `main`. A successful `main` build also tests and publishes a downloadable ZIP as a workflow artifact.
