#!/usr/bin/env python3
"""role-x.py — CLI helpers for the role-x primitive (bstack P17).

Subcommands:
  validate <path>  Validate a lens markdown file against the schema
  list             List all lenses in the roles/ directory
  index            Regenerate roles/_index.md

The agent uses this CLI for lens authoring (validate before commit) and
discovery index generation. Runtime selection and mode-decision are
reasoning-enforced — see references/selection-algorithm.md.
"""
from __future__ import annotations

import argparse
import sys
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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
