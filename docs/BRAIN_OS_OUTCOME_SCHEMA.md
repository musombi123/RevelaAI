# Brain OS Outcome Telemetry Schema

**Schema version:** 1.1  
**Status:** implemented; production routing is not controlled by this telemetry.

## Purpose

Outcome telemetry supports reliability analysis and offline routing evaluation. It is not a transcript store and it does not itself authorize automatic route changes.

## Record fields

| Field | Meaning |
|---|---|
| `schema_version` | Schema version for migration and reporting. |
| `category` | Allowlisted task category, such as `coding`, `security`, `elimu` or `scripture`. |
| `success` | Legacy field; means technical delivery success only. |
| `delivery_success` | Explicit technical delivery result. |
| `task_success` | Nullable boolean task result. Null means unknown, not success. |
| `latency_ms` | Bounded response latency in milliseconds. |
| `feedback_label` | Optional categorical feedback label, never free-form comments. |
| `user_feedback` | `helpful` or `unhelpful`, tracked separately from correctness. |
| `quality_label` | `correct` or `incorrect`, tracked separately from delivery. |
| `resolution_label` | `resolved` or `unresolved`. |
| `outcome_source` | Allowlisted source class. Routing shadow evaluation trusts task-success labels only from `validator` or `admin_review`. |
| `provider`, `route` | Optional bounded, normalized system dimensions. |
| `actor` | Allowlisted actor class, not a user/account identifier. |
| `created_at` | UTC timestamp used for freshness evaluation. |

Raw prompts, model responses, direct user identifiers, credentials and arbitrary feedback text must not be written to these outcome records.

## Compatibility and migration

- Schema 1.1 adds explicit `delivery_success`, nullable `task_success`, categorical feedback dimensions, source class, provider and route dimensions.
- Existing records may contain only `success` and `feedback_label`. Readers use `success` as a fallback for delivery only.
- The response field `success_rate` remains a backward-compatible alias for delivery success rate. It must not be interpreted as task quality.
- Missing task labels remain unknown. Do not backfill task success from delivery success.
- Existing records are not rewritten in place. New writes use schema 1.1.

## Freshness and sample requirements

- The category summary reports the most recent observed timestamp and the count of stale/unparseable records within its latest-200-record window. The summary freshness window is 72 hours.
- Routing shadow evaluation uses recent records only, requires at least 20 trusted task labels per provider, and reports 95% Wilson intervals.
- Shadow evaluation accepts task-success labels only from the `validator` and `admin_review` source classes. Chat delivery telemetry does not qualify.
- Conflicting task-quality and delivery evidence suppresses a favorable candidate recommendation.
- The shadow evaluator never changes the live route. A favorable result only permits further offline evaluation.

## Failure handling

Telemetry is best-effort on the chat request path. A persistence error must not turn a successful generated answer into a failed chat response. The integration regression test injects an outcome-store failure and asserts the chat endpoint still returns the answer.

## Operational limits

These records are evidence inputs, not ground truth by default. Review validator correctness, feedback abuse, provider sample representativeness, privacy retention, and access controls before using telemetry to justify a live canary. Any future live routing experiment requires a separately reviewed policy, explicit approval, monitoring, canary thresholds and rollback criteria.