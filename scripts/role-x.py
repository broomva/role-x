#!/usr/bin/env python3
"""role-x.py — CLI helpers for the role-x primitive (bstack P17).

Subcommands:
  validate <path>  Validate a lens markdown file against the schema
  list             List all lenses in the roles/ directory
  index            Regenerate roles/_index.md
  intake           UserPromptSubmit hook entry point — scores lenses,
                   emits event, outputs context to stdout (M2+)

The agent uses this CLI for lens authoring (validate before commit) and
discovery index generation. Runtime selection and mode-decision are
reasoning-enforced — see references/selection-algorithm.md. The intake
subcommand wires P17 into the Claude Code UserPromptSubmit hook so the
selection happens deterministically before every substantive prompt.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    print("error: PyYAML required (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)


REQUIRED_FIELDS = {
    "name": str,
    "status": str,
    "extends": (str, type(None)),
    "signals": dict,
    "context_loaders": dict,
    "default_mode": str,
    "quality_bar": list,
    "prompt_improvement_patterns": list,
    "mode_escalation": dict,
    "out_of_scope": list,
    "related_lenses": list,
    "created": (str, object),  # may be parsed as date by yaml
    "updated": (str, object),
}

# v0.3.0 — optional per-lens overrides. Validated when present, ignored when absent.
OPTIONAL_FIELDS = {
    "threshold": int,  # per-lens score threshold; defaults to DEFAULT_THRESHOLD
}

STATUS_VALUES = {"active", "candidate", "deprecated"}
MODE_VALUES = {"augment", "rewrite", "decompose"}

REQUIRED_SIGNAL_KEYS = {"paths", "prompt_keywords", "branch_patterns", "linear_labels"}
REQUIRED_CONTEXT_KEYS = {"files", "entities", "skills", "glob_hints"}
REQUIRED_ESCALATION_KEYS = {"rewrite_when", "decompose_when"}

# v0.3.0 — workspace-default scoring constants. Per-lens overrides via
# `threshold:` (top-level) and `signals.weights:` (nested) take precedence.
DEFAULT_THRESHOLD = 2
DEFAULT_SIGNAL_WEIGHTS = {
    "paths": 1,
    "prompt_keywords": 1,
    "branch_patterns": 1,
    "linear_labels": 1,
}
SIGNAL_WEIGHT_KEYS = set(DEFAULT_SIGNAL_WEIGHTS.keys())


def parse_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter from a markdown file."""
    if not text.startswith("---\n"):
        raise ValueError("file does not start with frontmatter delimiter '---'")
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        raise ValueError("frontmatter not closed with '---'")
    return yaml.safe_load(parts[1]) or {}


def validate_lens(path: Path) -> tuple[bool, list[str]]:
    """Validate a lens file. Returns (ok, errors)."""
    errors: list[str] = []

    if not path.exists():
        return False, [f"file not found: {path}"]

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, [f"cannot read {path}: {exc}"]

    try:
        fm = parse_frontmatter(text)
    except (ValueError, yaml.YAMLError) as exc:
        return False, [f"frontmatter parse error: {exc}"]

    # Check required top-level fields
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in fm:
            errors.append(f"missing required field: {field}")
            continue
        value = fm[field]
        if not isinstance(value, expected_type):
            errors.append(
                f"field {field} has type {type(value).__name__}, "
                f"expected {expected_type}"
            )

    # Enum validations (only if field present and right shape)
    if isinstance(fm.get("status"), str) and fm["status"] not in STATUS_VALUES:
        errors.append(
            f"status must be one of {sorted(STATUS_VALUES)}, got {fm['status']!r}"
        )
    if isinstance(fm.get("default_mode"), str) and fm["default_mode"] not in MODE_VALUES:
        errors.append(
            f"default_mode must be one of {sorted(MODE_VALUES)}, got {fm['default_mode']!r}"
        )

    # Name must match filename basename (without .md)
    if isinstance(fm.get("name"), str):
        expected_name = path.stem
        if fm["name"] != expected_name:
            errors.append(
                f"name {fm['name']!r} must match filename basename {expected_name!r}"
            )

    # Nested dict shape checks
    signals = fm.get("signals")
    if isinstance(signals, dict):
        for key in REQUIRED_SIGNAL_KEYS:
            if key not in signals:
                errors.append(f"signals.{key} missing")
            elif not isinstance(signals[key], list):
                errors.append(f"signals.{key} must be a list")
        # v0.3.0 optional: signals.weights — per-signal-type weight multipliers
        weights = signals.get("weights")
        if weights is not None:
            if not isinstance(weights, dict):
                errors.append("signals.weights must be a mapping if present")
            else:
                for k, v in weights.items():
                    if k not in SIGNAL_WEIGHT_KEYS:
                        errors.append(
                            f"signals.weights.{k} not recognised; expected one of {sorted(SIGNAL_WEIGHT_KEYS)}"
                        )
                        continue
                    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                        errors.append(
                            f"signals.weights.{k} must be a non-negative integer, got {v!r}"
                        )
    context = fm.get("context_loaders")
    if isinstance(context, dict):
        for key in REQUIRED_CONTEXT_KEYS:
            if key not in context:
                errors.append(f"context_loaders.{key} missing")
            elif not isinstance(context[key], list):
                errors.append(f"context_loaders.{key} must be a list")
    escalation = fm.get("mode_escalation")
    if isinstance(escalation, dict):
        for key in REQUIRED_ESCALATION_KEYS:
            if key not in escalation:
                errors.append(f"mode_escalation.{key} missing")
            elif not isinstance(escalation[key], list):
                errors.append(f"mode_escalation.{key} must be a list")

    # v0.3.0 optional top-level fields
    if "threshold" in fm:
        t = fm["threshold"]
        if not isinstance(t, int) or isinstance(t, bool) or t < 1:
            errors.append(f"threshold must be a positive integer when present, got {t!r}")

    return len(errors) == 0, errors


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate subcommand entry point."""
    ok, errors = validate_lens(Path(args.path))
    if ok:
        print(f"OK: {args.path} is a valid lens")
        return 0
    print(f"INVALID: {args.path}", file=sys.stderr)
    for err in errors:
        print(f"  - {err}", file=sys.stderr)
    return 1


def discover_lenses(roles_dir: Path) -> list[Path]:
    """Return sorted list of *.md files in roles_dir, excluding _index.md."""
    if not roles_dir.exists():
        return []
    paths = sorted(p for p in roles_dir.glob("*.md") if p.name != "_index.md")
    return paths


def cmd_list(args: argparse.Namespace) -> int:
    """List subcommand entry point."""
    roles_dir = Path(args.roles_dir)
    lenses = discover_lenses(roles_dir)
    if not lenses:
        print(f"no lenses found in {roles_dir}", file=sys.stderr)
        return 1
    for path in lenses:
        try:
            fm = parse_frontmatter(path.read_text(encoding="utf-8"))
            status = fm.get("status", "?")
            extends = fm.get("extends", "?")
            mode = fm.get("default_mode", "?")
            print(f"{path.stem}\tstatus={status}\textends={extends}\tmode={mode}")
        except (ValueError, yaml.YAMLError):
            print(f"{path.stem}\t(unparseable)")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    """Index subcommand entry point — generates roles/_index.md."""
    roles_dir = Path(args.roles_dir)
    lenses = discover_lenses(roles_dir)
    if not lenses:
        print(f"no lenses found in {roles_dir}", file=sys.stderr)
        return 1

    lines: list[str] = []
    lines.append("# Lens Registry — Auto-Generated Index")
    lines.append("")
    lines.append("This file is regenerated by `role-x index`. Do not edit by hand.")
    lines.append("")
    lines.append("| Lens | Status | Extends | Default Mode | Description |")
    lines.append("|---|---|---|---|---|")

    for path in lenses:
        try:
            fm = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, yaml.YAMLError):
            lines.append(f"| {path.stem} | (unparseable) | | | |")
            continue
        name = fm.get("name", path.stem)
        status = fm.get("status", "?")
        extends = fm.get("extends", "?") or "(base)"
        mode = fm.get("default_mode", "?")
        # Pull first non-heading line of body as description
        body = path.read_text(encoding="utf-8").split("---\n", 2)[-1]
        desc_lines = [
            line.strip() for line in body.splitlines()
            if line.strip() and not line.startswith("#")
        ]
        desc = desc_lines[0][:80] if desc_lines else ""
        lines.append(f"| [{name}]({path.name}) | {status} | {extends} | {mode} | {desc} |")

    index_path = roles_dir / "_index.md"
    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {index_path} ({len(lenses)} lenses)")
    return 0


### intake subcommand (M2 hook integration) ###


CARVE_OUT_MIN_WORDS = 3  # prompts shorter than this skip the intake reflex

# v0.4.1 — "domain-rich" heuristic. When intake routes to _meta-only AND the
# prompt is non-trivial AND has enough distinct meaningful tokens, surface a
# one-line nudge: "consider role-x init <slug>". Closes the gap where agents
# saw _meta-only repeatedly but never aggregated the signal.
DOMAIN_RICH_MIN_WORDS = 8
DOMAIN_RICH_MIN_TOKENS = 4

# v0.4.1 — coverage thresholds for the SessionStart hook's silent-when-healthy
# logic. If recent fire-rate is at-or-above this floor AND there's no
# clusters-above-threshold visible, the coverage hook stays silent.
COVERAGE_HEALTHY_FIRE_RATE = 30  # percent
EVENTS_PATH = Path.home() / ".config" / "broomva" / "role" / "events.jsonl"

# v0.4.0 — observability config. Privacy-by-default: no sanitized prompt
# capture unless the operator opts in via this config file. When absent,
# events.jsonl keeps recording prompt_digest (sha256) only, identical to
# v0.2.0-v0.3.0 behavior.
CONFIG_PATH = Path.home() / ".config" / "broomva" / "role" / "config.json"
CONFIG_DEFAULTS: dict[str, object] = {
    "capture_sanitized_prompt": False,
    "sanitization_strategy": "keywords",  # one of: "keywords" | "first_chars"
    "sanitization_top_n_keywords": 5,
    "sanitization_first_chars": 80,
}
SANITIZATION_STRATEGIES = {"keywords", "first_chars"}


def _find_workspace_root(start: Path | None = None) -> Path:
    """Walk up from `start` looking for a workspace marker (roles/, AGENTS.md, .git)."""
    current = (start or Path.cwd()).resolve()
    for parent in [current, *current.parents]:
        if (parent / "roles").is_dir() or (parent / "AGENTS.md").is_file():
            return parent
        if (parent / ".git").exists():
            return parent
    return current


def _git_signals(workspace: Path) -> dict:
    """Capture git-derived signals: branch, recently touched files."""
    signals: dict = {"branch": "", "touched_files": []}
    try:
        branch = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if branch.returncode == 0:
            signals["branch"] = branch.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    files: set[str] = set()
    for argset in (
        ["git", "-C", str(workspace), "diff", "--name-only"],
        ["git", "-C", str(workspace), "diff", "--name-only", "--cached"],
        ["git", "-C", str(workspace), "diff", "--name-only", "HEAD~1", "HEAD"],
    ):
        try:
            result = subprocess.run(argset, capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line:
                        files.add(line)
        except (subprocess.SubprocessError, FileNotFoundError):
            continue
    signals["touched_files"] = sorted(files)
    return signals


def _tokenize_prompt(prompt: str) -> set[str]:
    """Case-insensitive token set for keyword matching."""
    return {tok.lower() for tok in re.findall(r"[A-Za-z][A-Za-z0-9_-]+", prompt)}


def _resolve_weights(lens: dict) -> dict[str, int]:
    """v0.3.0 — resolve effective per-signal-type weights for a lens.

    Per-lens `signals.weights.<type>` overrides DEFAULT_SIGNAL_WEIGHTS for that
    type only; unspecified types stay at default. Returns a fully-populated dict.
    """
    declared = ((lens.get("signals") or {}).get("weights") or {})
    return {
        key: int(declared.get(key, DEFAULT_SIGNAL_WEIGHTS[key]))
        for key in SIGNAL_WEIGHT_KEYS
    }


def _resolve_threshold(lens: dict) -> int:
    """v0.3.0 — resolve the effective selection threshold for a lens."""
    declared = lens.get("threshold")
    if isinstance(declared, int) and not isinstance(declared, bool) and declared >= 1:
        return declared
    return DEFAULT_THRESHOLD


def _score_lens(lens: dict, branch: str, touched_files: list[str], prompt_tokens: set[str]) -> dict:
    """Score a lens's frontmatter against the current signals.

    Returns breakdown dict with raw match counts (for backward-compat event
    schema) plus weighted total. Per-lens `signals.weights` (v0.3.0) multiplies
    raw counts when computing the total used for threshold comparison.
    """
    signals = lens.get("signals", {}) or {}
    paths = signals.get("paths") or []
    prompt_keywords = signals.get("prompt_keywords") or []
    branch_patterns = signals.get("branch_patterns") or []

    path_hits = sum(
        1 for glob in paths
        if any(fnmatch.fnmatch(f, glob) for f in touched_files)
    )
    keyword_hits = sum(
        1 for kw in prompt_keywords
        if str(kw).lower() in prompt_tokens
    )
    branch_hits = sum(
        1 for pat in branch_patterns
        if branch and fnmatch.fnmatch(branch, pat)
    )
    weights = _resolve_weights(lens)
    total = (
        path_hits * weights["paths"]
        + keyword_hits * weights["prompt_keywords"]
        + branch_hits * weights["branch_patterns"]
        # linear_labels still 0 — Linear MCP probe not wired
    )
    return {
        "paths": path_hits,  # raw counts (backward-compat for event schema)
        "prompt_keywords": keyword_hits,
        "branch_patterns": branch_hits,
        "linear_labels": 0,
        "weights_applied": weights,  # v0.3.0 — surfaces resolved weights for debugging
        "total": total,
    }


def _load_lens(path: Path) -> dict | None:
    """Read a lens file, return parsed frontmatter dict (or None on parse error)."""
    try:
        text = path.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        if isinstance(fm, dict) and fm.get("name"):
            return fm
    except (ValueError, yaml.YAMLError, OSError):
        return None
    return None


def _walk_extends(name: str, registry: dict[str, dict]) -> list[str]:
    """Walk the extends: chain from `name` back to base. Returns ordered list including starting lens."""
    chain: list[str] = []
    seen: set[str] = set()
    current: str | None = name
    while current and current not in seen:
        chain.append(current)
        seen.add(current)
        lens = registry.get(current)
        if not lens:
            break
        parent = lens.get("extends")
        if parent is None or parent in seen:
            break
        current = parent
    return chain


def _select_lenses(
    roles_dir: Path,
    signals: dict,
    prompt: str,
    threshold: int = DEFAULT_THRESHOLD,
) -> dict:
    """Score all lenses; return selection dict with selected, mode, signals.

    v0.3.0: each lens can override `threshold` (top-level) and
    `signals.weights.<type>` (nested) — the global `threshold` argument here
    is only used as the default when a lens doesn't declare its own.
    """
    lenses: dict[str, dict] = {}
    for path in discover_lenses(roles_dir):
        lens = _load_lens(path)
        if not lens:
            continue
        if lens.get("status") != "active":
            continue
        lenses[lens["name"]] = lens

    prompt_tokens = _tokenize_prompt(prompt)
    branch = signals.get("branch", "")
    touched = signals.get("touched_files", [])

    scored: list[tuple[str, int, dict, int]] = []
    for name, lens in lenses.items():
        if name == "_meta":
            continue  # _meta is always applied as the base, not scored
        breakdown = _score_lens(lens, branch, touched, prompt_tokens)
        per_lens_threshold = _resolve_threshold(lens) if "threshold" in lens else threshold
        scored.append((name, breakdown["total"], breakdown, per_lens_threshold))
    scored.sort(key=lambda x: x[1], reverse=True)

    selected_above_threshold = [(n, t, b) for n, t, b, th in scored if t >= th]
    selected_names: list[str] = [n for n, _, _ in selected_above_threshold]

    if not selected_names and "_meta" in lenses:
        selected_names = []  # only _meta will apply via the extension chain

    # Resolve extends chain: each selected lens walks back to _meta
    extension_chain: list[str] = []
    for name in selected_names:
        for step in _walk_extends(name, lenses):
            if step not in extension_chain:
                extension_chain.append(step)
    if "_meta" in lenses and "_meta" not in extension_chain:
        extension_chain.append("_meta")

    # Decide mode: take strongest signal among selected, else _meta default
    primary_mode = "augment"
    escalation_reason: str | None = None
    if len(selected_names) >= 2:
        primary_mode = "decompose"
        escalation_reason = "≥2 lenses scored above threshold — multi-domain decomposition recommended"
    elif selected_names:
        primary_lens = lenses[selected_names[0]]
        primary_mode = primary_lens.get("default_mode", "augment")
    else:
        meta = lenses.get("_meta")
        if meta:
            primary_mode = meta.get("default_mode", "augment")

    selection = {
        "lenses_selected": selected_names,
        "lenses_extended": extension_chain,
        "mode": primary_mode,
        "mode_escalation_reason": escalation_reason,
        "signals_matched": {
            "paths": sum(b["paths"] for _, _, b in selected_above_threshold),
            "prompt_keywords": sum(b["prompt_keywords"] for _, _, b in selected_above_threshold),
            "branch_patterns": sum(b["branch_patterns"] for _, _, b in selected_above_threshold),
            "linear_labels": 0,
        },
        "per_lens_scores": {n: b for n, _, b, _ in scored},
        "per_lens_thresholds": {n: th for n, _, _, th in scored},
        "registry": lenses,
    }
    return selection


def _load_config(config_path: Path = CONFIG_PATH) -> dict:
    """Load observability config; return safe defaults on absence or parse error.

    Privacy-by-default: missing config = no sanitized prompt capture.
    """
    config = dict(CONFIG_DEFAULTS)
    try:
        if config_path.exists():
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for key in CONFIG_DEFAULTS:
                    if key in raw:
                        config[key] = raw[key]
    except (OSError, json.JSONDecodeError):
        pass  # any failure → safe defaults
    # Validate enum value
    if config["sanitization_strategy"] not in SANITIZATION_STRATEGIES:
        config["sanitization_strategy"] = CONFIG_DEFAULTS["sanitization_strategy"]
    return config


def _sanitize_prompt(prompt: str, config: dict) -> dict | None:
    """Produce a sanitized representation per config, or None if disabled.

    Returns dict with {"strategy": str, "value": list[str] | str} or None.
    """
    if not config.get("capture_sanitized_prompt"):
        return None
    strategy = config.get("sanitization_strategy", "keywords")
    if strategy == "keywords":
        top_n = int(config.get("sanitization_top_n_keywords", 5))
        tokens = _tokenize_prompt(prompt)
        # Deduplicate while preserving order of first appearance
        seen: set[str] = set()
        ordered: list[str] = []
        for tok in re.findall(r"[A-Za-z][A-Za-z0-9_-]+", prompt):
            low = tok.lower()
            if low not in seen and len(low) > 2:  # drop stop-words shorter than 3
                seen.add(low)
                ordered.append(low)
        return {"strategy": "keywords", "value": ordered[:top_n]}
    if strategy == "first_chars":
        n = int(config.get("sanitization_first_chars", 80))
        return {"strategy": "first_chars", "value": prompt[:n]}
    return None  # unknown strategy → no capture


def _emit_event(
    session_id: str,
    prompt: str,
    selection: dict,
    events_path: Path = EVENTS_PATH,
    config: dict | None = None,
) -> None:
    """Append an intake event to events.jsonl (best-effort, never raises).

    v0.4.0: includes optional `prompt_sanitized` field when config opts in.
    """
    try:
        events_path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": "intake",
            "session": session_id,
            "prompt_digest": "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "prompt_word_count": len(prompt.split()),
            "lenses_selected": selection["lenses_selected"],
            "lenses_extended": selection["lenses_extended"],
            "mode": selection["mode"],
            "mode_escalation_reason": selection["mode_escalation_reason"],
            "signals_matched": selection["signals_matched"],
        }
        cfg = config if config is not None else _load_config()
        sanitized = _sanitize_prompt(prompt, cfg)
        if sanitized is not None:
            event["prompt_sanitized"] = sanitized
        with events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass  # never fail the hook


def _format_intake_context(selection: dict) -> str:
    """Render the selection as a markdown block that becomes agent context."""
    lenses_selected = selection["lenses_selected"]
    extension_chain = selection["lenses_extended"]
    mode = selection["mode"]
    registry = selection["registry"]

    lines: list[str] = []
    lines.append("[role-x intake — P17 reflex applied]")
    if lenses_selected:
        sig = selection["signals_matched"]
        signal_summary = ", ".join(
            f"{k}={v}" for k, v in sig.items() if v
        ) or "none"
        lines.append(
            f"Lens(es): {', '.join(lenses_selected)} (signals: {signal_summary}); "
            f"extension chain: {' → '.join(extension_chain)}"
        )
    else:
        lines.append("Lens(es): _meta only (no domain lens scored ≥2)")
    lines.append(f"Mode: {mode}")
    if selection["mode_escalation_reason"]:
        lines.append(f"Mode escalation reason: {selection['mode_escalation_reason']}")

    # Compose quality_bar across the extension chain (child overrides parent)
    quality_bar: list[str] = []
    context_files: list[str] = []
    suggestions: list[dict] = []
    seen_bar: set[str] = set()
    seen_files: set[str] = set()
    for name in reversed(extension_chain):  # parent first, child overrides
        lens = registry.get(name)
        if not lens:
            continue
        for entry in lens.get("quality_bar") or []:
            if isinstance(entry, str) and entry not in seen_bar:
                quality_bar.append(entry)
                seen_bar.add(entry)
        loaders = lens.get("context_loaders") or {}
        for f in (loaders.get("files") or []):
            if isinstance(f, str) and f not in seen_files:
                context_files.append(f)
                seen_files.add(f)
        for sug in lens.get("prompt_improvement_patterns") or []:
            if isinstance(sug, dict):
                suggestions.append(sug)

    if quality_bar:
        lines.append("Quality bar (P14 dep-chain template):")
        for entry in quality_bar:
            lines.append(f"  - {entry}")
    if context_files:
        lines.append("Context files to surface:")
        for f in context_files:
            lines.append(f"  - {f}")
    if suggestions and mode != "augment":
        lines.append("Prompt-improvement suggestions (optional):")
        for sug in suggestions:
            sig = sug.get("signal", "")
            text = sug.get("suggestion", "")
            if sig and text:
                lines.append(f"  - if {sig!r}: {text}")
    lines.append("")
    lines.append(
        "Agents: apply the quality_bar entries as the P14 enumeration template for this response. "
        "If mode != augment, surface the rewrite/decompose proposal to the user before proceeding."
    )
    # v0.4.1: when no domain lens fired AND the prompt is domain-rich enough
    # to plausibly merit one, surface a one-line "consider authoring a lens"
    # nudge. Pure suggestion — agent decides whether to act on it.
    nudge = selection.get("authoring_nudge")
    if nudge:
        lines.append("")
        lines.append(nudge)
    return "\n".join(lines)


def _domain_rich(prompt: str, word_count: int) -> bool:
    """Heuristic: is the prompt substantive enough to plausibly need a lens?"""
    if word_count < DOMAIN_RICH_MIN_WORDS:
        return False
    tokens = {
        tok.lower()
        for tok in re.findall(r"[A-Za-z][A-Za-z0-9_-]+", prompt)
        if len(tok) > 3  # filter trivial connectors
    }
    return len(tokens) >= DOMAIN_RICH_MIN_TOKENS


def _build_authoring_nudge(prompt: str, selection: dict) -> str | None:
    """v0.4.1 — return a 1-line role-x init suggestion when warranted."""
    if selection.get("lenses_selected"):
        return None  # a domain lens already fired — no nudge
    word_count = len(prompt.split())
    if not _domain_rich(prompt, word_count):
        return None
    # Pick a short candidate slug from the prompt's most distinctive tokens
    tokens = [
        tok.lower()
        for tok in re.findall(r"[A-Za-z][A-Za-z0-9_-]+", prompt)
        if len(tok) > 3
    ]
    # Dedupe in order
    seen: set[str] = set()
    ordered: list[str] = []
    for tok in tokens:
        if tok not in seen:
            seen.add(tok)
            ordered.append(tok)
    slug = "-".join(ordered[:2]) if ordered else "candidate"
    return (
        f"Note: no domain lens scored ≥2 for this prompt. If this kind of "
        f"work recurs, consider expanding the registry: "
        f"`role-x init {slug}` (status: candidate)."
    )


def cmd_intake(args: argparse.Namespace) -> int:
    """Intake subcommand — UserPromptSubmit hook entry point.

    Reads JSON event payload from stdin (Claude Code hook protocol) OR
    accepts --prompt/--workspace flags for manual invocation and testing.
    Always exits 0 (never blocks the user's turn).
    """
    # Resolve prompt + session id from flags first, then stdin fallback.
    prompt = args.prompt
    session_id = args.session or os.environ.get("CLAUDE_SESSION_ID") or "unknown"

    if prompt is None:
        try:
            stdin_data = sys.stdin.read() if not sys.stdin.isatty() else ""
        except OSError:
            stdin_data = ""
        if stdin_data:
            try:
                payload = json.loads(stdin_data)
                prompt = payload.get("prompt") or payload.get("user_prompt") or ""
                session_id = payload.get("session_id") or session_id
            except json.JSONDecodeError:
                prompt = stdin_data  # accept raw prompt text as fallback

    if not prompt or len(prompt.split()) < CARVE_OUT_MIN_WORDS:
        return 0  # carve-out: trivial/short prompts skip intake

    workspace = Path(args.workspace).resolve() if args.workspace else _find_workspace_root()
    roles_dir = workspace / "roles"
    if not roles_dir.is_dir():
        return 0  # no lens registry → nothing to do, exit silently

    signals = _git_signals(workspace)
    selection = _select_lenses(roles_dir, signals, prompt)
    # v0.4.1: attach authoring nudge for _meta-only domain-rich prompts
    selection["authoring_nudge"] = _build_authoring_nudge(prompt, selection)
    _emit_event(session_id, prompt, selection)
    print(_format_intake_context(selection))
    return 0


### suggest subcommand (v0.4.0 — observability for organic lens growth) ###


def _parse_duration(spec: str) -> int:
    """Parse a duration spec like '7d', '24h', '90m', '3600s' into seconds."""
    if not spec:
        return 7 * 86400
    unit = spec[-1].lower()
    try:
        amount = int(spec[:-1])
    except ValueError:
        try:
            return int(spec)  # bare number = seconds
        except ValueError:
            return 7 * 86400
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    return amount * multipliers.get(unit, 86400)


def _read_events_since(events_path: Path, since_seconds: int) -> list[dict]:
    """Read events.jsonl, returning entries with ts within the window. Best-effort."""
    if not events_path.exists():
        return []
    cutoff = datetime.now(timezone.utc).timestamp() - since_seconds
    out: list[dict] = []
    try:
        for line in events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = event.get("ts", "")
            try:
                event_time = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
            except (ValueError, AttributeError):
                continue
            if event_time >= cutoff:
                out.append(event)
    except OSError:
        return []
    return out


def _cluster_unrouted(events: list[dict], min_cluster_size: int = 2) -> list[dict]:
    """Cluster events that routed to _meta-only by shared sanitized keywords.

    Requires `prompt_sanitized.strategy == "keywords"` on events. Returns a list
    of clusters with keywords/event_count/session_count/suggested_name. Events
    lacking sanitized capture are skipped silently — caller decides to surface.
    """
    keyword_to_events: dict[str, list[dict]] = {}
    for ev in events:
        if ev.get("lenses_selected"):
            continue  # already routed
        sanitized = ev.get("prompt_sanitized") or {}
        if sanitized.get("strategy") != "keywords":
            continue
        for kw in sanitized.get("value") or []:
            keyword_to_events.setdefault(kw, []).append(ev)

    # Score keywords by frequency
    keyword_freq = {kw: len(evs) for kw, evs in keyword_to_events.items()}
    top_keywords = sorted(keyword_freq.items(), key=lambda x: x[1], reverse=True)

    # Greedy clustering: take top keyword, gather its events, then look at the
    # most-co-occurring other keyword to form a 2-keyword cluster
    clusters: list[dict] = []
    used_events: set[str] = set()  # by prompt_digest
    for kw, _ in top_keywords[:20]:
        cluster_events = [
            ev for ev in keyword_to_events[kw]
            if ev.get("prompt_digest") not in used_events
        ]
        if len(cluster_events) < min_cluster_size:
            continue
        # Find co-occurring keywords inside this cluster
        co_freq: dict[str, int] = {}
        for ev in cluster_events:
            for other_kw in (ev.get("prompt_sanitized", {}).get("value") or []):
                if other_kw != kw:
                    co_freq[other_kw] = co_freq.get(other_kw, 0) + 1
        co_top = sorted(co_freq.items(), key=lambda x: x[1], reverse=True)[:2]
        cluster_keywords = [kw] + [k for k, _ in co_top]
        sessions = {ev.get("session", "") for ev in cluster_events}
        for ev in cluster_events:
            digest = ev.get("prompt_digest")
            if digest:
                used_events.add(digest)
        clusters.append({
            "keywords": cluster_keywords,
            "event_count": len(cluster_events),
            "session_count": len(sessions),
            "suggested_name": "-".join(cluster_keywords)[:40],
        })
    return clusters


def _lens_drift_summary(events: list[dict]) -> dict[str, dict]:
    """For each lens that fired in the window, summarize fire count + sessions.

    Returns dict {lens_name: {fires, sessions, avg_word_count}}.
    """
    summary: dict[str, dict] = {}
    for ev in events:
        for lens in ev.get("lenses_selected") or []:
            entry = summary.setdefault(
                lens, {"fires": 0, "sessions": set(), "word_count_sum": 0}
            )
            entry["fires"] += 1
            entry["sessions"].add(ev.get("session", ""))
            entry["word_count_sum"] += int(ev.get("prompt_word_count") or 0)
    out: dict[str, dict] = {}
    for lens, entry in summary.items():
        fires = entry["fires"]
        out[lens] = {
            "fires": fires,
            "sessions": len(entry["sessions"]),
            "avg_word_count": (entry["word_count_sum"] / fires) if fires else 0.0,
        }
    return out


def cmd_suggest(args: argparse.Namespace) -> int:
    """Suggest new lenses + per-lens drift signals from events.jsonl telemetry."""
    events_path = Path(args.events_path) if args.events_path else EVENTS_PATH
    since_seconds = _parse_duration(args.since)
    events = _read_events_since(events_path, since_seconds)

    if not events:
        print(f"[role-x suggest] no events in {events_path} within --since {args.since}")
        return 0

    total = len(events)
    fired = sum(1 for ev in events if ev.get("lenses_selected"))
    unrouted = total - fired
    pct_fired = (100.0 * fired / total) if total else 0.0

    print(f"[role-x suggest] window: --since {args.since}, events: {total}")
    print(f"  fired ≥1 lens: {fired} ({pct_fired:.0f}%)")
    print(f"  _meta only:    {unrouted} ({100 - pct_fired:.0f}%)")
    print()

    has_sanitized = any(
        (ev.get("prompt_sanitized") or {}).get("strategy") == "keywords"
        for ev in events
    )
    if not has_sanitized:
        print("Cluster discovery requires sanitized prompt capture (privacy-by-default off).")
        print("  → To enable, write:")
        print(f"    {CONFIG_PATH}")
        print('    {"capture_sanitized_prompt": true, "sanitization_strategy": "keywords"}')
        print("  Past events without capture won't be clusterable, but new ones will.")
        print()
    else:
        clusters = _cluster_unrouted(events, min_cluster_size=max(2, args.threshold))
        if clusters:
            print(f"Top {len(clusters)} emergent keyword clusters in _meta-only events:")
            for i, cluster in enumerate(clusters[: args.limit], 1):
                kws = ", ".join(cluster["keywords"])
                print(
                    f"  {i}. [{kws}] — {cluster['event_count']} events, "
                    f"{cluster['session_count']} sessions"
                )
                print(f"     → role-x init {cluster['suggested_name']}")
            print()
        else:
            print("No _meta-only clusters above threshold — registry coverage looks good.")
            print()

    drift = _lens_drift_summary(events)
    if drift:
        print("Active lens drift summary:")
        for lens, stats in sorted(drift.items(), key=lambda x: x[1]["fires"], reverse=True):
            print(
                f"  {lens}: {stats['fires']} fires, {stats['sessions']} sessions, "
                f"avg prompt {stats['avg_word_count']:.0f} words"
            )
        print()
        print("Future v0.5.0 will add `role-x tune <lens>` for per-lens drift detail.")

    return 0


### coverage subcommand (v0.4.1 — SessionStart-friendly silent-when-healthy report) ###


def cmd_coverage(args: argparse.Namespace) -> int:
    """Brief registry-health summary suitable for a SessionStart hook.

    Silent (exit 0, no output) when registry coverage looks healthy. Prints a
    3-5 line nudge when fire-rate is below the floor OR when sanitized capture
    is off so cluster discovery can't run.
    """
    events_path = Path(args.events_path) if args.events_path else EVENTS_PATH
    since_seconds = _parse_duration(args.since)
    events = _read_events_since(events_path, since_seconds)

    total = len(events)
    if total < args.min_events and not args.force:
        return 0  # not enough events to report meaningfully

    fired = sum(1 for ev in events if ev.get("lenses_selected"))
    unrouted = total - fired
    pct_fired = (100.0 * fired / total) if total else 0.0

    has_sanitized = any(
        (ev.get("prompt_sanitized") or {}).get("strategy") == "keywords"
        for ev in events
    )

    is_healthy = pct_fired >= COVERAGE_HEALTHY_FIRE_RATE and has_sanitized
    if is_healthy and not args.force:
        return 0  # silent — registry coverage looks fine

    # Build a tight nudge (≤5 lines including the action hints)
    print(
        f"[role-x coverage] {total} events over {args.since}. "
        f"Fire-rate: {pct_fired:.0f}% "
        f"({'low' if pct_fired < COVERAGE_HEALTHY_FIRE_RATE else 'ok'})."
    )
    if not has_sanitized:
        print(
            "  Sanitized prompt capture is OFF — cluster discovery disabled. "
            f"Enable: {CONFIG_PATH}"
        )
        print(
            '  Body: {"capture_sanitized_prompt": true, '
            '"sanitization_strategy": "keywords"}'
        )
    elif pct_fired < COVERAGE_HEALTHY_FIRE_RATE:
        # We have sanitized data but coverage is still low — gesture toward suggest
        print("  Run `role-x suggest` for emergent cluster + drift report.")
    print("  Author next: `role-x init <name>` (status: candidate, promote on rule-of-three).")
    return 0


### init subcommand (v0.4.0 — scaffold a new lens from CLI args) ###


_INIT_RESERVED_NAMES = {"_index"}


def _csv_to_list(spec: str | None) -> list[str]:
    if not spec:
        return []
    return [item.strip() for item in spec.split(",") if item.strip()]


def cmd_init(args: argparse.Namespace) -> int:
    """Scaffold a new lens file under roles/.

    Always emits status: candidate (rule-of-three not yet met). The author is
    expected to commit the file, then promote to status: active after ≥3
    positive-outcome uses (the bstack engine P16 path).
    """
    name = args.name.strip()
    if not re.fullmatch(r"[a-z][a-z0-9-]*", name):
        print(
            f"error: lens name must be kebab-case starting with a letter "
            f"(got {name!r})",
            file=sys.stderr,
        )
        return 2
    if name in _INIT_RESERVED_NAMES:
        print(f"error: {name!r} is a reserved lens name", file=sys.stderr)
        return 2

    roles_dir = Path(args.roles_dir)
    if not roles_dir.exists():
        roles_dir.mkdir(parents=True, exist_ok=True)
    lens_path = roles_dir / f"{name}.md"
    if lens_path.exists() and not args.force:
        print(
            f"error: {lens_path} already exists. Use --force to overwrite.",
            file=sys.stderr,
        )
        return 1

    keywords = _csv_to_list(args.keywords)
    paths = _csv_to_list(args.paths)
    branches = _csv_to_list(args.branch_patterns)
    labels = _csv_to_list(args.linear_labels)
    extends = args.extends or "_meta"
    mode = args.mode
    if mode not in MODE_VALUES:
        print(
            f"error: --mode must be one of {sorted(MODE_VALUES)}, got {mode!r}",
            file=sys.stderr,
        )
        return 2

    today = datetime.now(timezone.utc).date().isoformat()

    def _yaml_list(items: list[str]) -> str:
        if not items:
            return " []"
        return "\n" + "\n".join(f"    - \"{item}\"" for item in items)

    threshold_block = ""
    if args.threshold is not None:
        if args.threshold < 1:
            print("error: --threshold must be >= 1", file=sys.stderr)
            return 2
        threshold_block = f"threshold: {args.threshold}\n"

    content = (
        "---\n"
        f"name: {name}\n"
        "status: candidate\n"
        f"extends: {extends}\n"
        f"{threshold_block}"
        "signals:\n"
        f"  paths:{_yaml_list(paths)}\n"
        f"  prompt_keywords:{_yaml_list(keywords)}\n"
        f"  branch_patterns:{_yaml_list(branches)}\n"
        f"  linear_labels:{_yaml_list(labels)}\n"
        "context_loaders:\n"
        "  files: []\n"
        "  entities: []\n"
        "  skills: []\n"
        "  glob_hints: []\n"
        f"default_mode: {mode}\n"
        "quality_bar: []\n"
        "prompt_improvement_patterns: []\n"
        "mode_escalation:\n"
        "  rewrite_when: []\n"
        "  decompose_when: []\n"
        "out_of_scope: []\n"
        "related_lenses: []\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        "---\n"
        "\n"
        f"# {name} lens\n"
        "\n"
        f"> Scaffolded by `role-x init {name}` on {today}. Status: **candidate**.\n"
        ">\n"
        "> Promote to `status: active` after at least 3 positive-outcome uses (bstack engine P16).\n"
        "\n"
        "## Scope\n"
        "\n"
        "TODO: state what this lens covers and what it explicitly doesn't.\n"
        "\n"
        "## Quality bar to enforce (P14 dep-chain template)\n"
        "\n"
        "TODO: list domain-specific quality_bar entries. The agent will surface these\n"
        "as the dep-chain template whenever this lens fires.\n"
        "\n"
        "## Common anti-patterns this lens should flag\n"
        "\n"
        "TODO: list the failure modes this lens exists to prevent.\n"
        "\n"
        "## Composition triggers\n"
        "\n"
        "TODO: which other lenses commonly compose with this one?\n"
    )

    lens_path.write_text(content, encoding="utf-8")
    print(f"wrote {lens_path}")
    print()
    print("Next steps:")
    print(f"  1. Edit {lens_path} — fill in context_loaders + quality_bar + body TODOs")
    print(f"  2. python3 {sys.argv[0]} validate {lens_path}")
    print(f"  3. python3 {sys.argv[0]} index --roles-dir {roles_dir}")
    print(f"  4. git add {lens_path} {roles_dir}/_index.md && git commit")
    return 0


### Argparse + main ###


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="role-x",
        description="CLI helpers for the role-x primitive (bstack P17)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_validate = sub.add_parser("validate", help="validate a lens markdown file against the schema")
    p_validate.add_argument("path", help="path to the lens .md file")
    p_validate.set_defaults(func=cmd_validate)

    p_list = sub.add_parser("list", help="list all lenses in the roles/ directory")
    p_list.add_argument("--roles-dir", default="roles", help="path to roles directory (default: roles)")
    p_list.set_defaults(func=cmd_list)

    p_index = sub.add_parser("index", help="regenerate roles/_index.md")
    p_index.add_argument("--roles-dir", default="roles", help="path to roles directory (default: roles)")
    p_index.set_defaults(func=cmd_index)

    p_intake = sub.add_parser(
        "intake",
        help="UserPromptSubmit hook entry point (M2): score lenses, emit event, output context",
    )
    p_intake.add_argument(
        "--prompt",
        default=None,
        help="user prompt content (if omitted, read JSON payload from stdin)",
    )
    p_intake.add_argument(
        "--workspace",
        default=None,
        help="workspace root (default: walk up from cwd looking for roles/ or AGENTS.md)",
    )
    p_intake.add_argument(
        "--session",
        default=None,
        help="session id (default: $CLAUDE_SESSION_ID env or 'unknown')",
    )
    p_intake.set_defaults(func=cmd_intake)

    p_coverage = sub.add_parser(
        "coverage",
        help="(v0.4.1) brief registry-health summary; silent when coverage is healthy",
    )
    p_coverage.add_argument(
        "--since", default="7d", help="window (default 7d)",
    )
    p_coverage.add_argument(
        "--events-path", default=None, help=f"path to events.jsonl (default: {EVENTS_PATH})",
    )
    p_coverage.add_argument(
        "--min-events", type=int, default=10,
        help="minimum events in window before reporting (default 10)",
    )
    p_coverage.add_argument(
        "--force", action="store_true", help="always print, even when healthy",
    )
    p_coverage.set_defaults(func=cmd_coverage)

    p_suggest = sub.add_parser(
        "suggest",
        help="(v0.4.0) analyze events.jsonl; suggest new lenses + per-lens drift signals",
    )
    p_suggest.add_argument(
        "--since",
        default="7d",
        help="window (e.g. 7d, 24h, 90m); default 7d",
    )
    p_suggest.add_argument(
        "--threshold",
        type=int,
        default=2,
        help="minimum event count for a keyword cluster to surface (default 2)",
    )
    p_suggest.add_argument(
        "--limit",
        type=int,
        default=10,
        help="maximum clusters to print (default 10)",
    )
    p_suggest.add_argument(
        "--events-path",
        default=None,
        help=f"path to events.jsonl (default: {EVENTS_PATH})",
    )
    p_suggest.set_defaults(func=cmd_suggest)

    p_init = sub.add_parser(
        "init",
        help="(v0.4.0) scaffold a new candidate lens under roles/",
    )
    p_init.add_argument("name", help="kebab-case lens name (becomes roles/<name>.md)")
    p_init.add_argument("--roles-dir", default="roles", help="path to roles directory (default: roles)")
    p_init.add_argument("--keywords", default="", help="comma-separated prompt_keywords")
    p_init.add_argument("--paths", default="", help="comma-separated path globs")
    p_init.add_argument("--branch-patterns", default="", help="comma-separated branch_patterns")
    p_init.add_argument("--linear-labels", default="", help="comma-separated linear_labels")
    p_init.add_argument("--extends", default="_meta", help="parent lens name (default _meta)")
    p_init.add_argument("--mode", default="augment", help="default_mode (augment | rewrite | decompose)")
    p_init.add_argument("--threshold", type=int, default=None, help="optional per-lens threshold (≥1)")
    p_init.add_argument("--force", action="store_true", help="overwrite if file already exists")
    p_init.set_defaults(func=cmd_init)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
