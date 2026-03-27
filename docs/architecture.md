# Architecture

## Core Principle: Separate Reasoning from Execution

LLMs are expensive, non-deterministic, and hard to test. Most of what a social media workflow does is not creative — it is mechanical. This project draws a hard line:

| Concern | Handled by |
|---|---|
| What should I say? | LLM |
| Is this post valid? | Tool (deterministic) |
| When should I post? | Tool (deterministic) |
| Has this been approved? | Tool (state machine) |
| Write to the queue | Tool (deterministic) |

The LLM is a collaborator at two points only: drafting content from a brief, and revising content that failed validation. Everything else runs without it.

---

## Two-Layer Model

```
┌─────────────────────────────────────────────────┐
│                  LLM LAYER                      │
│  - Interprets briefs                            │
│  - Drafts post content                          │
│  - Revises rejected drafts                      │
│  - Makes tone / angle decisions                 │
└───────────────┬─────────────────────────────────┘
                │  structured inputs / outputs
┌───────────────▼─────────────────────────────────┐
│               TOOL LAYER                        │
│  - Validates rules (character limits, formats)  │
│  - Manages approval state transitions           │
│  - Finds scheduling slots                       │
│  - Writes to the post queue                     │
│  - Builds structured briefs                     │
└─────────────────────────────────────────────────┘
```

The tool layer never makes judgement calls. Each tool has defined inputs, outputs, and failure modes documented in its spec. They are designed to be:

- **Idempotent** — calling the same tool twice with the same input produces the same result
- **Auditable** — every state change is logged with a timestamp and actor
- **Testable** — no LLM dependency means unit tests are fast and deterministic

---

## Workflow Sequence

```
Step 1  ──  content-brief-builder          [NOT YET IMPLEMENTED]
            Accepts raw intent (topic, audience, platform, constraints).
            Returns a structured brief object.

Step 2  ──  LLM
            Receives the brief. Returns a post draft.

Step 3  ──  validate-post
            Checks the draft against platform rules.
            Returns pass or a list of validation errors.

            If fail → back to LLM with error context (Step 2)
            If pass → continue

Step 4  ──  approval-state-manager
            Transitions post from "draft" to "pending_approval".
            Human (or automated rule) approves or rejects.
            Transitions to "approved" or "rejected".

Step 5  ──  find-next-slot
            Given a schedule config, returns the next available datetime.

Step 6  ──  schedule-post
            Writes the approved post + slot to the queue.
            Returns a queue ID and confirmation.

Step 7  ──  publish_pipeline (CLI: python -m tools.publish_pipeline)
            Validates content, uploads media attachments, dispatches to the
            platform adapter, and returns a structured JSON result.

            Currently: Twitter text posts work end-to-end.
            Other platforms: stub adapters return ADAPTER_EXCEPTION.
```

Note: Steps 1–6 and Step 7 are not yet wired together automatically. Step 7
(`publish_pipeline`) can be called directly today with a JSON post payload.
`publish_post` (the queue-based delivery path) is implemented but not yet
connected to the live platform adapters.

---

## Design Decisions

### Why not just use the LLM for validation?
Validation rules are exact (280 characters, no forbidden words, valid URL format). LLMs get these wrong occasionally and cannot guarantee consistency. A rule-based validator is fast, free, and 100% reliable.

### Why a separate approval state manager?
Without explicit state tracking, it is easy to schedule posts that were never approved, or approve posts that were already scheduled. A state machine with logged transitions makes the audit trail clear and prevents illegal state jumps.

### Why separate find-next-slot from schedule-post?
Slot-finding is a read operation (what slot is free?). Scheduling is a write operation (claim this slot). Keeping them separate makes it easy to preview available slots without side effects, and simplifies testing.

### Why a content-brief-builder?
Passing raw, unstructured intent to an LLM inflates token usage and produces inconsistent output. A structured brief enforces the fields the LLM needs, nothing more, and gives it a consistent format to reason over.

---

## Data Flow Between Tools

```
content-brief-builder  →  { brief }
{ brief }              →  LLM  →  { draft }
{ draft, platform }    →  validate-post  →  { result, errors? }
{ post_id, actor }     →  approval-state-manager  →  { new_state, log_entry }
{ schedule_config }    →  find-next-slot  →  { slot_datetime }
{ post, slot }         →  schedule-post  →  { queue_id, confirmation }
{ post_payload }       →  publish_pipeline  →  { success, post_id, errors? }
```

Inside `publish_pipeline`, media attachments flow through a sub-pipeline:

```
{ asset }  →  validate_asset  →  { valid? }
{ asset }  →  upload_asset    →  { asset_ref }
{ entry + asset_refs }  →  platform_adapter  →  { platform_post_id }
```

All tool inputs and outputs are JSON-serialisable. No tool depends on another tool's internal state — they communicate only through data.
