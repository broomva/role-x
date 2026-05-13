# Lens Schema Reference

Each lens lives at `roles/<name>.md` and consists of YAML frontmatter
(machine-readable) + Markdown body (prose detail).

## Required frontmatter fields

| Field | Type | Description |
|---|---|---|
| `name` | string | unique identifier (kebab-case); must match filename basename (`roles/rust-systems.md` → `name: rust-systems`) |
| `status` | enum | `active` (lens applies in selection), `candidate` (logged but not applied), `deprecated` (kept for history) |
| `extends` | string or `null` | parent lens name; `null` only for `_meta`; defaults to `_meta` if omitted |
| `signals.paths` | list of glob patterns | path patterns evaluated against current branch's touched files |
| `signals.prompt_keywords` | list of strings | case-insensitive token match in user prompt |
| `signals.branch_patterns` | list of glob patterns | current-branch name patterns |
| `signals.linear_labels` | list of strings | optional Linear ticket labels |
| `context_loaders.files` | list of strings | workspace-relative file paths to surface in working context |
| `context_loaders.entities` | list of strings | KG entity page paths |
| `context_loaders.skills` | list of strings | skill identifiers flagged as "in scope" |
| `context_loaders.glob_hints` | list of glob patterns | globs to surface as "likely relevant" |
| `default_mode` | enum | `augment` / `rewrite` / `decompose` |
| `quality_bar` | list of strings | domain-specific P14 dep-chain checklist |
| `prompt_improvement_patterns` | list of `{signal, suggestion}` objects | optional improvements, surfaced not auto-applied |
| `mode_escalation.rewrite_when` | list of strings | triggers for `augment → rewrite` |
| `mode_escalation.decompose_when` | list of strings | triggers for `* → decompose` |
| `out_of_scope` | list of strings | what this lens explicitly delegates to other lenses |
| `related_lenses` | list of strings | commonly-composed lens names |
| `created` | ISO date | YYYY-MM-DD |
| `updated` | ISO date | YYYY-MM-DD |

## Optional fields

None at v1. New optional fields require a schema bump + entry in this reference.

## Body content

The Markdown body is for the agent's reasoning context when the lens
fires. Typical sections:

- **Workspace conventions** specific to this domain
- **Common anti-patterns** the lens flags
- **Composition triggers** — when this lens commonly composes with others
- **Reference docs** — links to authoritative sources

The body is human-readable but agent-consumed — assume an agent will be
reading it before responding to a user prompt in this domain.

## Validation

Run `python3 scripts/role-x.py validate roles/<name>.md`
to check frontmatter against schema. CI gate (M2+) enforces validation
in pre-commit.

## Example: minimal valid lens

```yaml
---
name: example
status: active
extends: _meta
signals:
  paths: ["**/*.example"]
  prompt_keywords: ["example"]
  branch_patterns: []
  linear_labels: []
context_loaders:
  files: []
  entities: []
  skills: []
  glob_hints: []
default_mode: augment
quality_bar: []
prompt_improvement_patterns: []
mode_escalation:
  rewrite_when: []
  decompose_when: []
out_of_scope: []
related_lenses: []
created: 2026-05-13
updated: 2026-05-13
---

# example lens
```
