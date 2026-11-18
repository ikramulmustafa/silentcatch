"""Command line interface for silentcatch."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from .detector import Finding, Verdict, analyse_file

EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".tox", ".mypy_cache", ".pytest_cache", "build", "dist",
}


def _iter_python_files(paths: list[str]) -> list[str]:
    found: list[str] = []
    for raw in paths:
        p = Path(raw)
        if p.is_file() and p.suffix == ".py":
            found.append(str(p))
        elif p.is_dir():
            for sub in p.rglob("*.py"):
                if any(part in EXCLUDED_DIRS for part in sub.parts):
                    continue
                found.append(str(sub))
    return sorted(set(found))


def _changed_files(base_ref: str) -> list[str] | None:
    """Files changed against base_ref, or None if git is unavailable."""
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base_ref}...HEAD"],
            capture_output=True, text=True, check=True, timeout=30,
        )
    # silentcatch: allow -- git absence is an expected condition, caller handles None
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None
    names = [n for n in out.stdout.splitlines() if n.endswith(".py")]
    return [n for n in names if Path(n).is_file()]


def _changed_lines(base_ref: str, path: str) -> set[int] | None:
    """Line numbers added or modified in `path` relative to base_ref."""
    try:
        out = subprocess.run(
            ["git", "diff", "-U0", f"{base_ref}...HEAD", "--", path],
            capture_output=True, text=True, check=True, timeout=30,
        )
    # silentcatch: allow -- git absence is an expected condition, caller handles None
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None

    lines: set[int] = set()
    for row in out.stdout.splitlines():
        if not row.startswith("@@"):
            continue
        # @@ -old,count +new,count @@
        try:
            new_part = row.split("+", 1)[1].split("@@", 1)[0].strip()
            if "," in new_part:
                start_s, count_s = new_part.split(",", 1)
                start, count = int(start_s), int(count_s)
            else:
                start, count = int(new_part), 1
            lines.update(range(start, start + max(count, 1)))
        # silentcatch: allow -- malformed hunk header, skip this hunk
        except (ValueError, IndexError):
            continue
    return lines


def _emit_github_annotation(f: Finding) -> None:
    level = "error" if f.is_failure else "warning"
    title = "Swallowed exception" if f.is_failure else "Logged but not re-raised"
    msg = f.message.replace("\n", " ")
    print(f"::{level} file={f.path},line={f.line},title={title}::{msg}")


def _emit_human(f: Finding) -> None:
    marker = "FAIL" if f.is_failure else "WARN"
    print(f"{marker}  {f.path}:{f.line}  {f.message}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="silentcatch",
        description=(
            "Find exception handlers that swallow failures. "
            "Built for codebases where agents write code faster than humans review it."
        ),
    )
    parser.add_argument("paths", nargs="*", default=["."],
                        help="Files or directories to scan (default: .)")
    parser.add_argument("--base", metavar="REF",
                        help="Only report findings on lines changed since REF "
                             "(e.g. origin/main). Requires git.")
    parser.add_argument("--strict", action="store_true",
                        help="Also fail on broad handlers that log but do not re-raise.")
    parser.add_argument("--format", choices=["human", "github"], default=None,
                        help="Output format. Defaults to github inside GitHub Actions.")
    args = parser.parse_args(argv)

    fmt = args.format or ("github" if os.environ.get("GITHUB_ACTIONS") == "true" else "human")

    if args.base:
        changed = _changed_files(args.base)
        if changed is None:
            print("silentcatch: could not run git, scanning all paths instead",
                  file=sys.stderr)
            targets = _iter_python_files(args.paths)
            line_filter: dict[str, set[int]] = {}
        else:
            targets = changed
            line_filter = {}
            for path in targets:
                lines = _changed_lines(args.base, path)
                if lines is not None:
                    line_filter[path] = lines
    else:
        targets = _iter_python_files(args.paths)
        line_filter = {}

    findings: list[Finding] = []
    for path in targets:
        for f in analyse_file(path):
            allowed = line_filter.get(path)
            if allowed is not None and f.line not in allowed:
                continue
            findings.append(f)

    failures = [f for f in findings if f.is_failure]
    warnings = [f for f in findings if not f.is_failure]

    for f in findings:
        if fmt == "github":
            _emit_github_annotation(f)
        else:
            _emit_human(f)

    if fmt == "human":
        print()
        if not findings:
            scope = "changed lines" if args.base else "scanned files"
            print(f"silentcatch: no swallowed exceptions in {scope}.")
        else:
            print(f"silentcatch: {len(failures)} swallowed, {len(warnings)} logged-only.")
            print("Add `# silentcatch: allow` above a handler that is deliberate.")

    if failures:
        return 1
    if args.strict and warnings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
