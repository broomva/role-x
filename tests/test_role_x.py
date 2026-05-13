"""Tests for scripts/role-x.py CLI."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "role-x.py"
FIXTURES = Path(__file__).parent / "fixtures"


def run_cli(*args: str) -> tuple[int, str, str]:
    """Run role-x.py with args; return (returncode, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


# --- validate subcommand ---

def test_validate_valid_lens_returns_zero():
    rc, out, err = run_cli("validate", str(FIXTURES / "valid-lens.md"))
    assert rc == 0, f"expected rc=0, got {rc}; stderr={err}"
    assert "OK" in out or "valid" in out.lower()


def test_validate_missing_required_returns_nonzero():
    rc, out, err = run_cli("validate", str(FIXTURES / "invalid-lens-missing-required.md"))
    assert rc != 0, f"expected rc!=0, got {rc}; stdout={out}"
    combined = (out + err).lower()
    assert "missing" in combined or "required" in combined


def test_validate_nonexistent_file_returns_nonzero():
    rc, out, err = run_cli("validate", "/nonexistent/lens.md")
    assert rc != 0
    combined = (out + err).lower()
    assert "not found" in combined or "no such file" in combined


# --- list subcommand ---

def test_list_prints_known_lenses(tmp_path):
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    (roles_dir / "_meta.md").write_text(_FIXTURE_META, encoding="utf-8")
    (roles_dir / "test-a.md").write_text(_FIXTURE_LENS_A, encoding="utf-8")

    rc, out, err = run_cli("list", "--roles-dir", str(roles_dir))
    assert rc == 0, err
    assert "_meta" in out
    assert "test-a" in out


def test_list_empty_dir_returns_nonzero(tmp_path):
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    rc, out, err = run_cli("list", "--roles-dir", str(roles_dir))
    assert rc != 0


# --- index subcommand ---

def test_index_generates_index_file(tmp_path):
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    (roles_dir / "_meta.md").write_text(_FIXTURE_META, encoding="utf-8")
    (roles_dir / "test-a.md").write_text(_FIXTURE_LENS_A, encoding="utf-8")

    rc, out, err = run_cli("index", "--roles-dir", str(roles_dir))
    assert rc == 0, err

    index_path = roles_dir / "_index.md"
    assert index_path.exists()
    body = index_path.read_text(encoding="utf-8")
    assert "_meta" in body
    assert "test-a" in body


_FIXTURE_META = """---
name: _meta
status: active
extends: null
signals:
  paths: []
  prompt_keywords: []
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
# _meta
Base lens.
"""

_FIXTURE_LENS_A = """---
name: test-a
status: active
extends: _meta
signals:
  paths: ["**/*.test"]
  prompt_keywords: ["a"]
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
# test-a
Test lens A.
"""
