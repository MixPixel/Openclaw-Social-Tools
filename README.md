# Openclaw Social Tools

A small, deterministic toolset for managing a social media workflow on top of [OpenClaw](https://openclaw.io).

---

## Philosophy

Most social media automation relies too heavily on LLMs for tasks that are purely mechanical — counting characters, checking scheduling conflicts, validating states. This project separates concerns deliberately:

- **LLM layer** → reasoning, tone, content decisions, brief interpretation
- **Tool layer** → validation, scheduling logic, state transitions, queue writes

This keeps token usage low, makes behaviour predictable and auditable, and lets you swap the LLM without rewriting the workflow.

---

## Architecture Overview

See [`docs/architecture.md`](docs/architecture.md) for the full design, but here is the short version:

```
[Content Brief Builder]
         │
         ▼
    (LLM drafts post)
         │
         ▼
  [Validate Post]  ──── fail ──→  (LLM revises)
         │ pass
         ▼
[Approval State Manager]
         │ approved
         ▼
  [Find Next Slot]
         │
         ▼
  [Schedule Post]
         │
         ▼
   (Platform delivery)
```

Each box is a deterministic tool. The LLM is only invoked at the points marked `(LLM ...)`.

---

## Tools

| Tool | Spec | Purpose |
|---|---|---|
| `content-brief-builder` | [spec](docs/specs/content-brief-builder.md) | Assembles a structured brief to feed into the LLM |
| `validate-post` | [spec](docs/specs/validate-post.md) | Checks a draft against platform rules |
| `approval-state-manager` | [spec](docs/specs/approval-state-manager.md) | Manages draft → approved state transitions |
| `find-next-slot` | [spec](docs/specs/find-next-slot.md) | Returns the next available posting slot |
| `schedule-post` | [spec](docs/specs/schedule-post.md) | Writes an approved post to the scheduling queue |

---

## Repository Layout

```
Openclaw-Social-Tools/
├── docs/
│   ├── architecture.md       # Design principles and workflow diagram
│   └── specs/                # Per-tool specification files
├── tools/                    # Tool implementations (coming soon)
│   ├── validate_post/
│   ├── find_next_slot/
│   ├── approval_state_manager/
│   ├── schedule_post/
│   └── content_brief_builder/
├── tests/                    # Test suite
├── templates/                # Prompt and brief templates
└── sample_data/              # Example inputs and outputs for testing
```

---

## Status

This project is in the scaffolding phase. Tool specs are complete; implementations are next.
