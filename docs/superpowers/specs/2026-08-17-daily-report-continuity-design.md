# Daily Report Continuity Design

## Goal

Publish one trustworthy daily market report for every scheduled report date without allowing AI-generated unsupported figures into the published report.

## Decision

The report remains authored by `deepseek-v4-pro` whenever its output passes the existing deterministic traceability validator. If the first draft and one AI revision both fail validation, or the AI returns no document, the system publishes a deterministic fact report built only from the already-approved public facts for that run.

## Constraints

- Numeric traceability validation remains unchanged and is never relaxed.
- Failed AI prose is not published or exposed in the user-facing UI.
- The fallback uses the same facts, evidence ids, cutoffs, and publication path as the AI report.
- A fallback document must pass the same validator before publication.
- If facts are incomplete or the deterministic fallback cannot pass validation, publication still fails rather than publishing an unsafe report.

## Observable Result

`generation_mode` is `pro_reasoning`, `validated_revision`, or `data_fallback`. A fallback is a valid daily report, not an error page or a failed draft.
