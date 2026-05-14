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

STATUS_VALUES = {"active", "candidate", "deprecated"}
MODE_VALUES = {"augment", "rewrite", "decompose"}

REQUIRED_SIGNAL_KEYS = {"paths", "prompt_keywords", "branch_patterns", "linear_labels"}
REQUIRED_CONTEXT_KEYS = {"files", "entities", "skills", "glob_hints"}
REQUIRED_ESCALATION_KEYS = {"rewrite_when", "decompose_when"}


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
EVENTS_PATH = Path.home() / ".config" / "broomva" / "role" / "events.jsonl"


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


def _score_lens(lens: dict, branch: str, touched_files: list[str], prompt_tokens: set[str]) -> dict:
    """Score a lens's frontmatter against the current signals. Returns breakdown dict."""
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
    total = path_hits + keyword_hits + branch_hits
    return {
        "paths": path_hits,
        "prompt_keywords": keyword_hits,
        "branch_patterns": branch_hits,
        "linear_labels": 0,  # not wired yet
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


def _select_lenses(roles_dir: Path, signals: dict, prompt: str, threshold: int = 2) -> dict:
    """Score all lenses; return selection dict with selected, mode, signals."""
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

    scored: list[tuple[str, int, dict]] = []
    for name, lens in lenses.items():
        if name == "_meta":
            continue  # _meta is always applied as the base, not scored
        breakdown = _score_lens(lens, branch, touched, prompt_tokens)
        scored.append((name, breakdown["total"], breakdown))
    scored.sort(key=lambda x: x[1], reverse=True)

    selected_above_threshold = [(n, t, b) for n, t, b in scored if t >= threshold]
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
        "per_lens_scores": {n: b for n, _, b in scored},
        "registry": lenses,
    }
    return selection


def _emit_event(session_id: str, prompt: str, selection: dict, events_path: Path = EVENTS_PATH) -> None:
    """Append an intake event to events.jsonl (best-effort, never raises)."""
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
    return "\n".join(lines)


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
    _emit_event(session_id, prompt, selection)
    print(_format_intake_context(selection))
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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
