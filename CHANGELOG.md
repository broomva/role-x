# Changelog

All notable changes to `role-x` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] — 2026-05-14

Trigger-strategy upgrade: lenses can now declare their own `threshold` and
per-signal-type `weights`. Closes the "every lens shares the same global
scoring rules" limitation in v0.1.0/v0.2.0.

### Added

- **Per-lens threshold override** — optional top-level `threshold: int` in lens
  frontmatter. Defaults to workspace global (`DEFAULT_THRESHOLD = 2`). Specialist
  lenses can set `threshold: 3` to avoid false positives; broad lenses can set
  `threshold: 1` to fire on a single strong signal.
- **Per-signal-type weights** — optional nested `signals.weights:` block. Each
  signal type (`paths`, `prompt_keywords`, `branch_patterns`, `linear_labels`)
  can declare its own multiplier (default 1 each). Use cases:
  - Weight branch patterns higher (e.g. `branch_patterns: 3`) when branch name
    is a strong intent signal
  - Set a signal type to `0` to disable it for a specific lens without removing
    the declaration
  - Amplify keyword matches (e.g. `prompt_keywords: 2`) for lenses where a
    single keyword hit should suffice
- **Validation extensions** — `role-x validate` now rejects:
  - `threshold` that is non-integer, boolean, or `<1`
  - `signals.weights` entries with non-int or negative values
  - `signals.weights` keys not in the recognised signal-type set
- **7 new tests** — boundary cases for per-lens threshold (1 and 3), weighted
  amplification, zero-weight signal disabling, and schema validation. Total: 20/20.
- **Output**: `_score_lens` breakdown now includes `weights_applied` so a future
  `role-x explain` subcommand can surface why a lens fired (or didn't).
- **Event log**: `per_lens_thresholds` map added to internal selection dict for
  future telemetry consumers. Wire-format `events.jsonl` schema is unchanged
  (raw counts in `signals_matched`, not weighted) — backward-compat preserved
  for M4 dream-cycle consumers.

### Changed

- `_score_lens` total is now `sum(raw_count × weight)` per signal type instead
  of `sum(raw_count)`. Lenses without `signals.weights` are unaffected (all
  weights default to 1, identical to v0.2.0 behavior).
- `_select_lenses` uses `_resolve_threshold(lens)` per-lens instead of a single
  global threshold. The `threshold=` argument remains the fallback default.
- Test count: 13 → 20 (Python 3.11 + 3.12 matrix).

### Backward compatibility

- All v0.1.0/v0.2.0 lenses (no `threshold`, no `signals.weights`) keep their
  exact prior behavior. Verified: workspace's `roles/_meta.md` + `roles/rust-systems.md`
  unchanged in scoring outcome.
- `events.jsonl` schema unchanged — recorded counts remain raw (unweighted).
- CLI surface unchanged — `validate` / `list` / `index` / `intake` subcommands
  all preserve their v0.2.0 signatures.

### Migration

No migration needed. Existing lenses keep working. To opt into the new
strategies, add `threshold:` or `signals.weights:` to a lens's frontmatter
and re-run `role-x validate <lens>` to confirm.

### Example: a security-review lens with strict threshold

```yaml
---
name: security-review
status: active
extends: _meta
threshold: 3                  # require ≥3 signals — avoid false positives
signals:
  paths:
    - "**/auth/**"
    - "**/credentials*"
  prompt_keywords:
    - "auth", "secret", "credential", "JWT", "OAuth"
  branch_patterns:
    - "feat/auth-*"
    - "feat/security-*"
  linear_labels:
    - "topic:security"
  weights:
    branch_patterns: 3          # branch is a strong signal — 1 hit = 3 score
    prompt_keywords: 1
    paths: 1
…
---
```

A prompt mentioning "auth" on `feat/auth-something` branch → 1 keyword (×1) + 1 branch
(×3) = 4 ≥ threshold 3 → fires.

## [0.2.0] — 2026-05-13

Hook integration (M2): role-x intake fires automatically on every substantive
user prompt via a Claude Code `UserPromptSubmit` hook. Closes the
reasoning-enforcement gap from v0.1.0 — now machine-checkable.

### Added
- `scripts/role-x-intake-hook.sh` — Claude Code `UserPromptSubmit` hook
  wrapper. Reads JSON payload from stdin, calls `role-x.py intake`,
  outputs context to stdout (added to the agent's working context).
  Graceful-fails (exit 0) if PyYAML missing, `roles/` absent, or workspace
  not detected. Never blocks a user turn.
- `role-x intake` subcommand on `scripts/role-x.py`. Reads JSON event from
  stdin **or** accepts `--prompt`/`--workspace`/`--session` flags for
  testing. Snapshots git signals (branch, touched files), tokenizes prompt
  keywords, scores all `roles/*.md` lenses, walks `extends:` chain,
  decides mode (augment / rewrite / decompose), emits structured event to
  `~/.config/broomva/role/events.jsonl`, prints intake context to stdout.
- 7 new tests covering carve-outs (short prompts, missing `roles/`),
  keyword matching, event persistence, multi-domain decompose escalation,
  `_meta`-only fallback, stdin JSON protocol.

### Changed
- Test count: 6 → **13** (all green on Python 3.11 + 3.12 CI).
- `references/feedback-loop.md` is now wired up: hook + intake subcommand
  produce events the M4 dream cycle will replay.

### Workspace wiring (separate PR in `broomva/workspace`)
This release ships the hook *script*. The workspace's `.claude/settings.json`
must register the hook to fire automatically:

```json
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
```

The hook is reasoning-supplementing, not blocking — `exit 0` always.

### Manual invocation (test or fallback)

```bash
# Direct CLI test
python3 ~/.agents/skills/role-x/scripts/role-x.py intake \
  --prompt "your prompt here" \
  --workspace "$PWD" \
  --session "manual"

# Via the hook script (simulating Claude Code stdin)
echo '{"prompt": "your prompt", "session_id": "manual"}' \
  | ~/.agents/skills/role-x/scripts/role-x-intake-hook.sh
```

## [0.1.0] — 2026-05-13

Initial release. Ships the Markdown lens registry + Python CLI for the bstack
P17 primitive (Lens-Routed Request Articulation).

### Added
- `SKILL.md` — skill front-door with frontmatter for skills.sh discovery
- `scripts/role-x.py` — CLI with `validate`, `list`, `index` subcommands
- `references/lens-schema.md` — YAML frontmatter field reference
- `references/selection-algorithm.md` — scoring algorithm (paths + prompt_keywords + branch_patterns + linear_labels, threshold ≥2)
- `references/mode-selection.md` — augment/rewrite/decompose decision tree
- `references/feedback-loop.md` — Nous-pattern telemetry design (implementation deferred to v0.2.0+)
- `tests/test_role_x.py` — pytest battery covering validate (3 tests) + list + index subcommands
- `tests/fixtures/` — valid + invalid lens fixtures for testing
- `.github/workflows/test.yml` — CI: pytest on push/PR
- `README.md`, `LICENSE` (MIT), `CHANGELOG.md`, `.gitignore`

### Deferred (roadmap)
- **v0.2.0 (M2)** — Hook integration (UserPromptSubmit / PostToolUse / Stop) + events.jsonl capture + status.json cache
- **v0.3.0 (M3)** — Seed lens corpus expansion (ts-nextjs, api-design, security-review, infra-deploy, docs-research)
- **v0.4.0 (M4)** — P13 dream cycle: `role-x-replay.py` with replay-against-frozen-substrate
- **v0.5.0 (M5)** — `persona-*` skill referenceability + thin lens wrappers

### Design provenance
Reframed by 2026 research that empirically debunks naive "act as X" persona prompting for code/factual tasks:
- Hu, Rostami, Thomason — PRISM (USC, [arXiv 2603.18507](https://arxiv.org/html/2603.18507v1)): MMLU drop 71.6% → 66.3% with long expert personas
- Zheng et al. ([arXiv 2311.10054](https://arxiv.org/html/2311.10054v3)) — 162-persona × 4-LLM study: "no or small negative effects"
- [Anthropic best-practices](https://claude.com/blog/best-practices-for-prompt-engineering) — lists heavy role prompting as outdated

The substance is in *what the agent loads next* — concrete files, conventions, prior decisions, domain-specific checklists — not in *how the agent introduces itself*. v0.1.0 ships that substance.
