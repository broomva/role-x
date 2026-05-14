# Changelog

All notable changes to `role-x` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.1] — 2026-05-14

Closes the meta-progression gap. The per-prompt routing was wired in v0.2.0;
v0.4.0 shipped the observability substrate; v0.4.1 wires the agent-facing
nudges so the *expression* of the system progresses naturally — without
requiring the user to remember to run `role-x suggest` or notice when the
registry undercovers their work.

### Added

- **In-prompt authoring nudge** — when intake routes to `_meta` only **AND**
  the prompt is "domain-rich" (≥8 words, ≥4 distinct meaningful tokens), the
  agent's working-context output appends one line:

  ```
  Note: no domain lens scored ≥2 for this prompt. If this kind of work
  recurs, consider expanding the registry: `role-x init <slug>` (status:
  candidate).
  ```

  The slug is auto-derived from the first 2 distinctive tokens. Tuning
  knobs: `DOMAIN_RICH_MIN_WORDS = 8`, `DOMAIN_RICH_MIN_TOKENS = 4`.

- **`role-x coverage`** — brief registry-health summary suitable for a
  SessionStart hook. Silent (exit 0, no output) when fire-rate ≥30% AND
  sanitized capture is enabled. Surfaces a 3-5 line nudge otherwise.

  ```
  role-x coverage [--since 7d --min-events N --force --events-path PATH]
  ```

- **`scripts/role-x-coverage-hook.sh`** — Claude Code `SessionStart` hook
  wrapper. 24h cooldown via `~/.config/broomva/role/coverage-stamp` (override
  via `ROLE_X_COVERAGE_COOLDOWN_HOURS`). Graceful-fail on missing Python /
  missing PyYAML / missing CLI. Always exits 0. Wired into workspace via
  `.claude/settings.json` `SessionStart` entry (separate PR on
  broomva/workspace).

- **8 new tests** (30 → **38 total**):
  - `intake_nudges_for_meta_only_domain_rich_prompt`
  - `intake_no_nudge_when_lens_fires`
  - `intake_no_nudge_for_short_prompt`
  - `coverage_silent_when_healthy`
  - `coverage_reports_when_no_sanitized_capture`
  - `coverage_reports_low_fire_rate`
  - `coverage_silent_below_min_events`
  - `coverage_force_prints_when_below_min`

### Why this exists (the gap closed)

v0.4.0 made `role-x suggest` available, but nothing reminded agents to *run*
it. The system captured 31 unrouted prompts over 7 days but no one noticed
the pattern. v0.4.1 fixes that with two complementary nudges:

| Cadence | Mechanism | Trigger |
|---|---|---|
| Per-prompt | Intake context appendix | `_meta`-only AND domain-rich prompt |
| Per-session (≤1/24h) | SessionStart hook → `coverage` | Fire-rate < 30% OR sanitized capture off |

Both are non-blocking and exit silently when the registry is healthy. Like
P8 skill-freshness, they nudge but never gate.

### Backward compatibility

- All v0.1.0-v0.4.0 lenses work unchanged.
- Event schema unchanged — nudge is computed at runtime, not stored.
- CLI signatures preserved.
- The intake context output has a new optional appendix; agents that don't
  consume it experience no change.

### Workspace wiring (separate PR on broomva/workspace)

To enable the SessionStart hook, add to `.claude/settings.json`:

```json
"SessionStart": [
  {
    "hooks": [
      {
        "type": "command",
        "command": "$HOME/.agents/skills/role-x/scripts/role-x-coverage-hook.sh",
        "timeout": 5
      }
    ]
  }
]
```

If the role-x install doesn't have v0.4.1+ yet, the hook silently exits 0.
No new failure mode introduced.

## [0.4.0] — 2026-05-14

Observability for organic lens growth. Closes the half-loop from v0.3.0 — the
substrate that lets the `roles/` registry expand from real telemetry instead
of speculative authoring. Two new subcommands + opt-in sanitized prompt
capture + a privacy-by-default config layer.

### Added

- **`role-x suggest`** — analyze `events.jsonl` over a window; report fire
  rate, per-lens drift, and (when sanitized capture is enabled) emergent
  keyword clusters in `_meta`-only events with suggested lens names.
  Read-only — never mutates the registry. Hints at the config knob when
  cluster discovery is disabled.

  ```
  role-x suggest --since 7d [--threshold N] [--limit M] [--events-path PATH]
  ```

- **`role-x init <name>`** — scaffold a new `status: candidate` lens under
  `roles/<name>.md` from CLI flags. Always emits candidates (rule-of-three
  not yet met); author promotes to `status: active` after ≥3 positive-outcome
  uses (P16). Scaffolded file passes `validate` immediately.

  ```
  role-x init <name>
    [--roles-dir DIR]
    [--keywords K1,K2,…]
    [--paths P1,P2,…]
    [--branch-patterns B1,B2,…]
    [--linear-labels L1,L2,…]
    [--threshold N]
    [--extends NAME]
    [--mode MODE]
    [--force]
  ```

- **Opt-in sanitized prompt capture** — when `~/.config/broomva/role/config.json`
  contains `{"capture_sanitized_prompt": true}`, the intake hook records a
  sanitized representation (default: top-N unique keywords) alongside the
  existing `prompt_digest`. Two strategies supported:

  | Strategy | Captured | Use when |
  |---|---|---|
  | `keywords` (default) | top N distinct alphanumeric tokens, lowercased | Lens authoring, cluster discovery — **recommended** |
  | `first_chars` | first N characters of the raw prompt | Higher-fidelity debugging; more sensitive to PII |

  Config example:
  ```json
  {
    "capture_sanitized_prompt": true,
    "sanitization_strategy": "keywords",
    "sanitization_top_n_keywords": 5
  }
  ```

  **Privacy invariant**: absent config = no sanitized capture. Existing
  v0.1.0/v0.2.0/v0.3.0 installations with no config file behave identically
  to before — only `prompt_digest` (sha256) recorded.

- **Event schema additions** (backward-compatible): events now optionally
  carry `prompt_sanitized: {strategy, value}`. Events lacking this field
  continue to validate against the existing schema. M5 dream-cycle consumers
  must handle both shapes.

- **10 new tests** (20 → **30 total**): suggest fire-rate summary, lens drift,
  cluster discovery, config-hint path, empty log, init success, invalid name
  rejection, overwrite refusal, sanitized capture on, sanitized capture off.

### Changed

- `_emit_event` accepts an optional `config` parameter (default: load from
  CONFIG_PATH). Backward-compatible — existing callers unaffected.
- `references/feedback-loop.md` marked v0.4.0 substrate as **shipped**; M4
  dream-cycle phase header retitled to v0.5.0+ (`tune` + `propose-lens`) and
  v0.6.0+ (`role-x-replay.py`).

### Backward compatibility

- No schema breaking changes. Lenses authored under v0.1.0-v0.3.0 work
  unchanged.
- Existing `events.jsonl` files are readable by `role-x suggest` without
  modification (cluster discovery silently disabled until sanitized capture
  starts producing events).
- CLI surface preserved — all v0.1.0-v0.3.0 subcommands keep their signatures.
- No new required config files. Privacy-by-default; opt-in via config.

### What this enables

```bash
# After 7+ days of telemetry with sanitized capture on:
$ role-x suggest --since 7d
[role-x suggest] window: --since 7d, events: 247
  fired ≥1 lens: 89 (36%)
  _meta only:    158 (64%)

Top 3 emergent keyword clusters in _meta-only events:
  1. [deploy, vercel, env] — 12 events, 6 sessions
     → role-x init deploy-vercel-env
  2. [spec, synthesis, research, entity] — 9 events, 7 sessions
     → role-x init spec-synthesis-research
  3. [tenant, exclusive-rentals, sentinel] — 5 events, 2 sessions
     → role-x init tenant-exclusive-rentals

Active lens drift summary:
  rust-systems: 41 fires, 18 sessions, avg prompt 14 words
  ts-nextjs:    27 fires, 12 sessions, avg prompt 11 words
  ...
```

Data-driven lens authoring — no more speculation about "what lenses might be
useful".

### Roadmap reshuffle

- **v0.5.0** — `role-x tune <lens>` (propose keyword/threshold/weight diffs
  from event log) + `role-x propose-lens <cluster>` (generate candidate lens
  from cluster). PRs only — never silent mutations.
- **v0.6.0 (M5)** — `role-x-replay.py` (full P13 dream cycle: gather → replay
  → prune → consolidate → index). Auto-promotion of candidates on positive
  outcomes.
- **v0.7.0** — `Stop` + `PostToolUse` outcome hooks → quality signals per
  lens-use (did the agent reference the loaded context? did the PR merge
  green? Nous score on resulting entity?).
- **v0.8.0** — Lens decay + auto-demotion of unused lenses.

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
