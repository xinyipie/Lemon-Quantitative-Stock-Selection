# Daily Report Reliability Design

## Goal

Make scheduled market reports observable and reliably publishable without weakening source, entity, or numeric traceability checks.

## Design

The first AI document remains subject to the existing deterministic validator. If validation fails, one repair request receives the public facts, rejected document, and exact validation errors. The repaired document passes through the same validator. No error is ignored and no numeric allow-list is expanded.

If the repair remains invalid or the model is unavailable, the service builds a conservative deterministic report. It uses an existing evidence id, contains no unsupported numeric claims, and limits itself to market structure, risk, and follow-up verification. If that document also fails validation, publication fails and the previous valid report remains unchanged.

Scheduled workers write subprocess output directly to persistent task logs while continuing to update the dashboard status JSON. The status file remains a current-state view; logs become the durable execution history.

## Accuracy Constraints

- Never relax `validate_report()`.
- Never publish an untraceable number, stock, industry, or event.
- Never overwrite the latest valid report with a failed draft.
- AI repair is limited to correcting the rejected document from approved public facts.
- Deterministic fallback must contain no unsupported numeric tokens.

## Verification

Targeted tests cover repaired publication, deterministic fallback, failed fallback preservation, worker log persistence, and scheduled runner log wiring.
