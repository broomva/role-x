"""Tests for scripts/role-x.py CLI."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "role-x.py"
FIXTURES = Path(__file__).parent / "fixtures"


def run_cli(*args: str, input_text: str | None = None, env: dict | None = None) -> tuple[int, str, str]:
    """Run role-x.py with args; return (returncode, stdout, stderr)."""
    full_env = {**os.environ, **(env or {})}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        input=input_text,
        env=full_env,
    )
    return result.returncode, result.stdout, result.stderr


def _seed_workspace(tmp_path: Path) -> Path:
    """Build a minimal workspace with roles/_meta.md + roles/rust.md for intake tests."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    roles = workspace / "roles"
    roles.mkdir()
    (roles / "_meta.md").write_text(_FIXTURE_META, encoding="utf-8")
    (roles / "rust.md").write_text(_FIXTURE_RUST, encoding="utf-8")
    return workspace


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

# Intake fixtures — include keyword-based signals so scoring fires.

_FIXTURE_RUST = """---
name: rust
status: active
extends: _meta
signals:
  paths: ["**/*.rs", "**/Cargo.toml"]
  prompt_keywords: ["rust", "cargo", "tokio", "async"]
  branch_patterns: []
  linear_labels: []
context_loaders:
  files: ["AGENTS.md"]
  entities: []
  skills: []
  glob_hints: []
default_mode: augment
quality_bar:
  - "MSRV 1.85 honored"
prompt_improvement_patterns:
  - signal: "no MSRV"
    suggestion: "specify MSRV"
mode_escalation:
  rewrite_when: []
  decompose_when: []
out_of_scope: []
related_lenses: []
created: 2026-05-13
updated: 2026-05-13
---
# rust
Test rust lens.
"""

_FIXTURE_TS = """---
name: ts
status: active
extends: _meta
signals:
  paths: ["**/*.ts", "**/package.json"]
  prompt_keywords: ["next.js", "typescript", "react"]
  branch_patterns: []
  linear_labels: []
context_loaders:
  files: []
  entities: []
  skills: []
  glob_hints: []
default_mode: augment
quality_bar:
  - "Biome enforced"
prompt_improvement_patterns: []
mode_escalation:
  rewrite_when: []
  decompose_when: []
out_of_scope: []
related_lenses: []
created: 2026-05-13
updated: 2026-05-13
---
# ts
Test ts lens.
"""


# --- intake subcommand (M2) ---

def test_intake_short_prompt_exits_silently(tmp_path):
    """Carve-out: prompts shorter than 3 words skip intake."""
    workspace = _seed_workspace(tmp_path)
    rc, out, err = run_cli(
        "intake", "--prompt", "hi", "--workspace", str(workspace), "--session", "t",
    )
    assert rc == 0
    assert out.strip() == ""


def test_intake_no_roles_dir_exits_silently(tmp_path):
    """If workspace has no roles/ dir, intake exits 0 with no output."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("#\n", encoding="utf-8")
    rc, out, err = run_cli(
        "intake",
        "--prompt", "this is a substantive prompt that needs handling",
        "--workspace", str(workspace),
        "--session", "t",
    )
    assert rc == 0
    assert out.strip() == ""


def test_intake_keyword_match_selects_lens(tmp_path):
    """Intake selects rust lens via prompt keyword matches and outputs context."""
    workspace = _seed_workspace(tmp_path)
    events = tmp_path / "events.jsonl"
    env = {"HOME": str(tmp_path)}  # redirect ~/.config/... via HOME override

    rc, out, err = run_cli(
        "intake",
        "--prompt", "refactor the rust cargo build with tokio async runtime",
        "--workspace", str(workspace),
        "--session", "test-session-123",
        env=env,
    )
    assert rc == 0
    assert "role-x intake" in out
    assert "rust" in out
    assert "augment" in out
    assert "MSRV 1.85 honored" in out  # quality_bar from rust lens
    # Should NOT pick ts lens — none of its keywords match
    assert "Biome" not in out


def test_intake_writes_event(tmp_path):
    """Intake appends a JSONL event to ~/.config/broomva/role/events.jsonl."""
    workspace = _seed_workspace(tmp_path)
    env = {"HOME": str(tmp_path)}

    rc, out, _ = run_cli(
        "intake",
        "--prompt", "implement rust cargo async tokio support",
        "--workspace", str(workspace),
        "--session", "test-event-write",
        env=env,
    )
    assert rc == 0
    events_path = tmp_path / ".config" / "broomva" / "role" / "events.jsonl"
    assert events_path.exists()
    lines = events_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["event"] == "intake"
    assert event["session"] == "test-event-write"
    assert event["lenses_selected"] == ["rust"]
    assert event["mode"] == "augment"
    assert event["prompt_digest"].startswith("sha256:")
    assert event["signals_matched"]["prompt_keywords"] >= 2


def test_intake_multi_domain_decomposes(tmp_path):
    """Prompts hitting ≥2 lenses (rust + ts) escalate to decompose mode."""
    workspace = _seed_workspace(tmp_path)
    env = {"HOME": str(tmp_path)}

    rc, out, _ = run_cli(
        "intake",
        "--prompt", "migrate rust cargo backend and typescript next.js react frontend together",
        "--workspace", str(workspace),
        "--session", "decompose-test",
        env=env,
    )
    assert rc == 0
    assert "decompose" in out.lower()
    # Both lens names should appear
    assert "rust" in out
    assert "ts" in out


def test_intake_no_match_applies_meta_only(tmp_path):
    """Prompt that hits no domain lens falls back to _meta with augment mode."""
    workspace = _seed_workspace(tmp_path)
    env = {"HOME": str(tmp_path)}

    rc, out, _ = run_cli(
        "intake",
        "--prompt", "design a strategy for quarterly planning narrative outline",
        "--workspace", str(workspace),
        "--session", "meta-only-test",
        env=env,
    )
    assert rc == 0
    assert "_meta only" in out
    assert "augment" in out


def test_intake_stdin_json_payload(tmp_path):
    """Intake accepts a JSON payload on stdin (the Claude Code hook protocol)."""
    workspace = _seed_workspace(tmp_path)
    env = {"HOME": str(tmp_path)}
    payload = json.dumps({
        "prompt": "build a new rust cargo async tokio service",
        "session_id": "stdin-test",
    })

    rc, out, _ = run_cli(
        "intake",
        "--workspace", str(workspace),
        input_text=payload,
        env=env,
    )
    assert rc == 0
    assert "rust" in out
    events_path = tmp_path / ".config" / "broomva" / "role" / "events.jsonl"
    assert events_path.exists()
    event = json.loads(events_path.read_text(encoding="utf-8").strip())
    assert event["session"] == "stdin-test"
