# Changelog

All notable changes to `role-x` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
