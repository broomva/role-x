# Feedback Loop (M2+ — out of M1 scope)

Lens-use telemetry feeds back into lens-rule improvements via the P13
dream cycle. This file documents the design; implementation lands in
M2-M4 follow-on plans.

## Three hook integration points (M2)

| Hook event | Captured | Storage |
|---|---|---|
| `UserPromptSubmit` | session id, prompt content snapshot (digest only), selected lens(es), mode, escalation reason if any, signals matched | `~/.config/broomva/role/events.jsonl` |
| `PostToolUse` | session id, tool name, lens-loaded context referenced (heuristic: did tool inputs intersect with `context_loaders.files`?) | same file |
| `Stop` | session id, lens-use outcome (CI green? PR merged without changes? user accepted suggestions? bookkeeping score?) | same file |

Events append one-per-line (flock-protected). Schema is intentionally
narrow — no model output content, no PII, just routing decisions and
their downstream signals.

## Dream-cycle consolidation (M4)

`python3 scripts/role-x-replay.py <lens-name>` runs the P13 5-phase dream cycle applied to lens rules:

| Phase | Action |
|---|---|
| **Gather** | Read `events.jsonl` for the lens over a bounded window (default 30 days). Bundle into `~/.config/broomva/role/consolidation-runs/<lens>-<date>/bundle.jsonl`. |
| **Replay** | Re-score each event against a *frozen snapshot* of the lens at bundle-creation time. Compute counterfactuals: what would the lens have done if its rules were updated? |
| **Prune** | Discard events showing no behavior change between live and counterfactual replay, or where outcome metric showed no improvement. |
| **Consolidate** | Emit a YAML diff against the lens's frontmatter (new signals, refined quality_bar entries, new prompt_improvement_patterns). Commit via PR. |
| **Index** | Update `roles/_index.md`; update `~/.config/broomva/role/status.json`. |

Critical: replay does NOT touch the live lens; it computes counterfactuals
against the frozen snapshot. This is the stop-gradient property that
distinguishes dream cycles from shadow dreams.

## Cadence

- Per-50-uses-per-lens (statistically sufficient for rule-change signal)
- OR weekly (whichever fires first)
- Manual invocation always available

## M2 scope (next plan)

- UserPromptSubmit + PostToolUse + Stop hook scripts
- `.claude/settings.json` registration
- events.jsonl + status.json initialization on first use
- `role-x.py events` subcommand for log inspection

## M4 scope (later plan)

- `role-x-replay.py` 5-phase dream cycle script
- Frozen-snapshot management under `consolidation-runs/`
- LLM judge integration for counterfactual scoring
- Auto-PR for consolidation diffs
