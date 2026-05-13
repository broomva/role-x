# Selection Algorithm

When the first-touch agent receives a substantive user input, it executes:

## Step 1: Snapshot signals

- `current_branch` — `git rev-parse --abbrev-ref HEAD`
- `touched_files` — `git diff --name-only HEAD~1 HEAD` + `git diff --name-only` (uncommitted)
- `prompt_tokens` — case-insensitive tokenization of user prompt
- `linear_labels` — from active Linear ticket if discoverable from branch name

## Step 2: Load lens registry

- Read `roles/_meta.md` (always)
- Read all `roles/*.md` where `status: active`
- Cache at session start; reload only on session restart

## Step 3: Score each lens

For each lens L:

```
score(L) =
  sum(1 for glob in L.signals.paths if any(fnmatch(f, glob) for f in touched_files))
+ sum(1 for kw in L.signals.prompt_keywords if kw.lower() in prompt_tokens)
+ sum(1 for pat in L.signals.branch_patterns if fnmatch(current_branch, pat))
+ sum(1 for lbl in L.signals.linear_labels if lbl in linear_labels)
```

## Step 4: Select lens(es)

- Threshold: `score(L) >= 2` (at least two independent signals match)
- Composition: if multiple lenses pass, apply all in descending score order
- Fallback: if no lens passes, apply `_meta` only

## Step 5: Resolve extension chain

For each selected lens, walk `extends:` back to `_meta`:

```
chain(L) = [L, L.extends, L.extends.extends, ..., _meta]
```

Merge `context_loaders` + `quality_bar` + `prompt_improvement_patterns`
with **child overrides parent** semantics (a child lens can override a
parent's entry by re-stating it with new content).

## Step 6: Decide mode

See `mode-selection.md` for the mode-decision tree.

## Step 7: Emit event

Log to `~/.config/broomva/role/events.jsonl`:

```json
{"ts":"<ISO>","event":"intake","session":"<id>","prompt_digest":"sha256:<hash>","lenses_selected":["<names>"],"lenses_extended":["<chain>"],"mode":"<mode>","signals_matched":{"paths":N,"prompt_keywords":N,"branch_patterns":N,"linear_labels":N}}
```

M1: reasoning-enforced (agent appends manually). M2: hook-driven via
UserPromptSubmit Claude Code hook.

## Reasoning-enforced caveat

The algorithm above is the *contract*. Agents implement it via
reasoning, not via a deterministic script — same pattern as P10, P14,
P15, P16. The Python CLI (`role-x.py`) validates lens schemas and
generates the discovery index but does NOT run selection at runtime.

A future enhancement (M2+) may add `role-x select --prompt "..."` for
deterministic scoring, which would let the agent verify its
reasoning-enforced choice against the algorithm. Not in M1 scope.
