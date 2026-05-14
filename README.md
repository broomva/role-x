# role-x — bstack P17: Lens-Routed Request Articulation

> **The typed routing layer above P5 parallel-agent dispatch.** On every substantive user input, the first-touch agent reflexively selects a domain lens, loads its substantive context, and decides single-agent vs surfaced rewrite vs parallel-team plan. No "act as X" persona theater — substantive context grounding only.

[![CI](https://github.com/broomva/role-x/actions/workflows/test.yml/badge.svg)](https://github.com/broomva/role-x/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![skills.sh](https://img.shields.io/badge/install-npx%20skills%20add%20broomva%2Frole--x-blue)](https://skills.sh)

## Why role-x exists

Modern frontier-model evidence ([PRISM USC 2026](https://arxiv.org/html/2603.18507v1), [Zheng et al. arXiv 2311.10054](https://arxiv.org/html/2311.10054v3), [Anthropic best-practices](https://claude.com/blog/best-practices-for-prompt-engineering)) shows that naive "act as expert X" persona prompting **hurts** code/factual accuracy — MMLU drops 71.6% → 66.3% with long expert personas; "no or small negative effects" across 162 personas × 4 LLMs × 2410 questions. Telling a model it's an expert does not impart expertise.

What *does* work is **substantive context grounding**: concrete files, conventions, prior decisions, domain-specific checklists. `role-x` makes that grounding **addressable, composable, and self-improving** via a Markdown lens registry the agent reasons over before responding.

## What role-x is

A bstack P17 skill providing:

1. **Lens registry** — `roles/_meta.md` (always-loaded base) + `roles/<name>.md` per-domain lenses. Each lens has YAML frontmatter (signals, context_loaders, quality_bar, prompt_improvement_patterns, mode_escalation, out_of_scope) and a prose body.
2. **Three modes per request** — `augment` (silent context load, default) / `rewrite` (surfaced prompt refinement, user accepts) / `decompose` (parallel-agent plan via P5, user-approved).
3. **CLI helpers** (this repo's `scripts/role-x.py`):
   - `role-x list` — list all lenses in `roles/`
   - `role-x validate <path>` — validate lens YAML frontmatter against schema
   - `role-x index` — regenerate `roles/_index.md` discovery file
4. **Reference docs** — schema, selection algorithm, mode-decision tree, feedback loop (M2+).

## Quick start

```bash
# 1. Install via skills.sh
npx skills add broomva/role-x

# 2. Create a lens registry in your workspace
mkdir -p roles
# Author roles/_meta.md (always-loaded base) and per-domain lenses

# 3. Validate a lens against the schema
python3 ~/.agents/skills/role-x/scripts/role-x.py validate roles/_meta.md
# → OK: roles/_meta.md is a valid lens

# 4. List all lenses
python3 ~/.agents/skills/role-x/scripts/role-x.py list --roles-dir roles

# 5. Regenerate the discovery index
python3 ~/.agents/skills/role-x/scripts/role-x.py index --roles-dir roles
# → wrote roles/_index.md (N lenses)
```

## How the agent uses role-x

At UserPromptSubmit for substantive work, the agent reasons through:

```
1. Snapshot signals (P15)
   - current branch (git rev-parse --abbrev-ref HEAD)
   - touched files (git diff --name-only)
   - prompt keywords
   - Linear ticket labels

2. Score lens registry
   For each roles/<name>.md:
     score = matches in {paths, prompt_keywords, branch_patterns, linear_labels}
   Threshold: score ≥ 2

3. Resolve extends: chain
   Walk back to _meta; merge context_loaders + quality_bar + prompt_improvement_patterns

4. Decide mode
   augment | rewrite | decompose
   per lens default_mode + mode_escalation

5. Surface to user (unless augment)
   "Applying lens(es) X, Y because [signals]. Suggestions: …. Proceeding."

6. Emit event to ~/.config/broomva/role/events.jsonl  (M2 — hook-driven)
```

Selection and mode-decision are **reasoning-enforced** (bstack-idiom, same as P10/P14/P15/P16). The CLI validates lens schemas and generates the discovery index; it does **not** run selection at runtime.

## Subcommands

| Command | Purpose |
|---|---|
| `role-x list [--roles-dir roles]` | List all lenses with status + extends + default_mode |
| `role-x validate <path>` | Validate a lens markdown file against the schema (frontmatter shape, required fields, enum values, name-matches-filename) |
| `role-x index [--roles-dir roles]` | Regenerate `roles/_index.md` discovery file |
| `role-x intake [--prompt … --workspace … --session …]` | **v0.2.0+** — `UserPromptSubmit` hook entry point. Scores lenses against current signals (git + prompt content), walks `extends:` chain, decides mode, emits event to `~/.config/broomva/role/events.jsonl`, prints agent-context to stdout. Reads JSON from stdin if `--prompt` omitted (the Claude Code hook protocol). |

## Hook integration (v0.2.0+)

The `intake` subcommand can fire automatically on every substantive user prompt via a Claude Code `UserPromptSubmit` hook. Add to your workspace's `.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$HOME/.agents/skills/role-x/scripts/role-x-intake-hook.sh",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

The hook:

- Reads the prompt JSON payload from stdin
- Resolves workspace via `$CLAUDE_PROJECT_DIR` (or `$PWD`)
- Scores `roles/*.md` against signals (git branch, touched files, prompt keywords)
- Selects lens(es) with score ≥2, walks `extends:` chain to `_meta`
- Decides mode (`augment` / `rewrite` / `decompose`)
- Appends a structured event to `~/.config/broomva/role/events.jsonl`
- Prints the lens metadata + composed `quality_bar` + suggestions to stdout (added to the agent's working context)

**Always exits 0.** Graceful-fails if PyYAML is missing, the workspace has no `roles/` directory, or the prompt is shorter than 3 words (carve-out for trivial prompts).

### Test the hook locally

```bash
echo '{"prompt": "implement rust cargo tokio async support", "session_id": "manual"}' \
  | CLAUDE_PROJECT_DIR=$PWD ~/.agents/skills/role-x/scripts/role-x-intake-hook.sh
```

Expected output: lens selected, mode decided, quality_bar surfaced, event appended to events.jsonl.

### Event schema

```json
{
  "ts": "<ISO-8601 UTC>",
  "event": "intake",
  "session": "<session id>",
  "prompt_digest": "sha256:<hex>",
  "prompt_word_count": 42,
  "lenses_selected": ["rust-systems"],
  "lenses_extended": ["rust-systems", "_meta"],
  "mode": "augment",
  "mode_escalation_reason": null,
  "signals_matched": {"paths": 0, "prompt_keywords": 4, "branch_patterns": 0, "linear_labels": 0}
}
```

See [`references/feedback-loop.md`](references/feedback-loop.md) for the full design (M4 dream cycle consumes this telemetry).

## Lens schema (minimal example)

```yaml
---
name: rust-systems
status: active
extends: _meta
signals:
  paths: ["**/Cargo.toml", "**/*.rs"]
  prompt_keywords: ["rust", "cargo", "tokio", "MSRV"]
  branch_patterns: ["feat/rust-*"]
  linear_labels: ["lang:rust"]
context_loaders:
  files: ["AGENTS.md#Conventions", "core/life/CLAUDE.md"]
  entities: ["research/entities/concept/stability-budget.md"]
  skills: ["rust-best-practices"]
  glob_hints: ["core/life/rust-toolchain.toml"]
default_mode: augment
quality_bar:
  - "MSRV declared in Cargo.toml is honored (workspace default: 1.85)"
  - "Edition 2024 idioms used"
  - "No unwrap() in non-test code unless documented"
prompt_improvement_patterns:
  - signal: "no MSRV mentioned"
    suggestion: "Specify target MSRV"
mode_escalation:
  rewrite_when: ["prompt asks for new API without naming trait shape"]
  decompose_when: ["prompt spans ≥2 crates with no shared types"]
out_of_scope: ["Non-Rust files"]
related_lenses: ["api-design", "security-review"]
created: 2026-05-13
updated: 2026-05-13
---
# rust-systems lens
[Body: prose detail, anti-patterns, composition triggers]
```

Full schema reference: [`references/lens-schema.md`](references/lens-schema.md).

## Cardinal invariant

> **No `act as X` persona rewrites.** Lenses load substantive context (files, conventions, checklists, optional suggestions). They do *not* insert persona declarations into the model's working context. The 2026 research is clear: persona declarations don't add expertise and frequently hurt accuracy.

## Where role-x fits in the bstack

```
User intent → P17 role-x intake → P15 state snapshot → Linear (P3) → Agent (P5)
                ↓ typed edges (lens per fan-out)
              P5 parallel dispatch becomes a typed graph
                ↓ lens.quality_bar IS the P14 dep-chain template
              P14 enumeration is domain-specific
                ↓ events.jsonl (M2)
              P13 dream cycle consolidates lens rules (M4)
                ↓ per-lens rule-of-three
              P16 promotes candidate lenses to status: active
```

`role-x` composes with — does not duplicate — existing primitives. See [`broomva/workspace`](https://github.com/broomva/workspace) `AGENTS.md` §P17 for the full reflexive trigger rule.

## Tests

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r tests/requirements-dev.txt
python3 -m pytest tests/ -v
```

## Spec & design

Full design lives at [`broomva/workspace`](https://github.com/broomva/workspace) under `docs/superpowers/specs/2026-05-13-role-x-primitive-design.md` (570 lines) and the implementation plan at `docs/superpowers/plans/2026-05-13-role-x-primitive-implementation.md` (2068 lines).

## Roadmap

- **v0.1.0** — Markdown lens registry + CLI (`validate`, `list`, `index`) + reference docs
- **v0.2.0** (this release) — `intake` subcommand + `UserPromptSubmit` hook + `~/.config/broomva/role/events.jsonl` capture
- **v0.3.0 (M3)** — Seed lens corpus expansion (`ts-nextjs`, `api-design`, `security-review`, `infra-deploy`, `docs-research`)
- **v0.4.0 (M4)** — P13 dream cycle: `role-x-replay.py` with replay-against-frozen-substrate; `status.json` per-lens stats cache
- **v0.5.0 (M5)** — `persona-*` skill referenceability + thin lens wrappers + `PostToolUse` / `Stop` outcome hooks

## License

MIT — see [LICENSE](LICENSE).

## Related

- [broomva/workspace](https://github.com/broomva/workspace) — unified workspace + governance (P17 §AGENTS.md, `roles/` registry)
- [broomva/bstack](https://github.com/broomva/bstack) — bstack catalog skill (counts P1-P17)
- [broomva/p9](https://github.com/broomva/p9) — bstack P7 (CI watcher + productive wait)
- [broomva/persist](https://github.com/broomva/persist) — bstack P12 (cross-context restart loop)
- [broomva/bookkeeping](https://github.com/broomva/bookkeeping) — bstack P6 (knowledge graph engine)
