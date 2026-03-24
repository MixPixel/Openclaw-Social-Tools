# CLAUDE.md — Openclaw Social Tools

This repo contains small, deterministic tools for an OpenClaw social media workflow. LLM reasoning is kept strictly separate from rule-based execution — the tools handle mechanical tasks; the LLM handles creative and judgement tasks.

---

## Rules

**Language**
Prefer Python for all tool implementations. Use the standard library where possible.

**Tool scope**
Keep every tool single-purpose. One tool does one job. If a tool is growing a second responsibility, split it.

**Output format**
Return structured JSON wherever possible. Every tool output should be machine-readable without parsing freeform text.

**Documentation**
Every tool must have a spec in `docs/specs/` before or alongside its implementation. Do not implement a tool without a corresponding spec.

**Dependencies**
Avoid unnecessary frameworks and libraries. Reach for the standard library first. Add a dependency only when it provides clear, non-trivial value.

**Planning**
Always propose a plan before large changes — new tools, significant refactors, changes that touch multiple files. Write the plan before writing code.

**Sequencing**
Never build multiple tools at once unless explicitly asked. Finish one tool (spec, implementation, tests) before starting the next.

**Frameworks**
Do not introduce web frameworks, ORMs, or heavyweight abstractions. These are CLI/library tools, not a web application.
