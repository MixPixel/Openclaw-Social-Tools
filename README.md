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

## Quickstart

Publish a text post to Twitter:

```bash
# 1. Add credentials
echo "TWITTER_API_KEY=..." >> .env
echo "TWITTER_API_SECRET=..." >> .env
echo "TWITTER_ACCESS_TOKEN=..." >> .env
echo "TWITTER_ACCESS_SECRET=..." >> .env

# 2. Run
echo '{"content": "Hello from OpenClaw!"}' \
  | python -m tools.publish_pipeline --platform twitter
```

See [docs/publish-pipeline-cli.md](docs/publish-pipeline-cli.md) for the full
CLI reference including `.env` format, result shape, and current limitations.

---

## Tools

| Tool | Spec | Status |
|---|---|---|
| `publish_pipeline` | [spec](docs/specs/publish-pipeline.md) | Twitter delivery working; other platforms stubbed |
| `validate-post` | [spec](docs/specs/validate-post.md) | Complete |
| `validate-asset` | [spec](docs/specs/validate-asset.md) | Complete |
| `upload-asset` | [spec](docs/specs/upload-asset.md) | Complete (Twitter); others stubbed |
| `approval-state-manager` | [spec](docs/specs/approval-state-manager.md) | Complete |
| `find-next-slot` | [spec](docs/specs/find-next-slot.md) | Complete |
| `schedule-post` | [spec](docs/specs/schedule-post.md) | Complete |
| `publish-post` | [spec](docs/specs/publish-post.md) | Queue works; not wired to live delivery |
| `content-brief-builder` | [spec](docs/specs/content-brief-builder.md) | Not yet implemented |

---

## Repository Layout

```
Openclaw-Social-Tools/
├── docs/
│   ├── publish-pipeline-cli.md   # CLI usage guide
│   ├── architecture.md
│   └── specs/                    # Per-tool specification files
├── tools/
│   ├── publish_pipeline/         # End-to-end publish CLI
│   ├── validate_post/
│   ├── validate_asset/
│   ├── upload_asset/
│   ├── platform_adapters/        # Twitter implemented; others stubbed
│   ├── find_next_slot/
│   ├── approval_state_manager/
│   ├── schedule_post/
│   └── publish_post/
├── tests/
└── config/
    └── asset_policy.json
```
