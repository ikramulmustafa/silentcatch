"""Detect exception handlers that swallow failures silently."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import Enum


class Verdict(str, Enum):
    SILENT = "silent"
    LOGGED_ONLY = "logged_only"
    OK = "ok"


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    col: int
    verdict: Verdict
    exception_type: str
    message: str

    @property
    def is_failure(self) -> bool:
        return self.verdict is Verdict.SILENT


# Call names that count as "this failure was recorded somewhere"
LOG_METHODS = frozenset({
    "debug", "info", "warning", "warn", "error", "exception",
    "critical", "fatal", "log",
})

# Common logger-ish receivers. Checked loosely: we care about the method name,
# but requiring a plausible receiver keeps `response.error(...)` from counting.
LOG_RECEIVERS = frozenset({
    "log", "logger", "logging", "logs", "_log", "_logger",
    "self", "cls", "app", "current_app", "LOG", "LOGGER",
    "structlog", "loguru",
})

# Calls that mean the failure is being reported, not hidden.
REPORTING_CALLS = frozenset({
    "capture_exception", "capture_message", "report", "report_error",
    "notify", "notify_error", "track_exception", "record_exception",
    "print_exc", "format_exc", "add_note",
})

SUPPRESS_COMMENT = "silentcatch: allow"


class _HandlerInspector(ast.NodeVisitor):
    """Walks a handler body looking for evidence the failure was not swallowed."""

    def __init__(self) -> None:
        self.reraises = False
        self.raises_new = False
        self.logs = False
        self.returns_or_assigns_fallback = False
        self.has_other_statements = False

    def visit_Raise(self, node: ast.Raise) -> None:
        if node.exc is None:
            self.reraises = True
        else:
            self.raises_new = True
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr in LOG_METHODS:
                receiver = _root_name(func.value)
                if receiver is None or receiver in LOG_RECEIVERS:
                    self.logs = True
            if func.attr in REPORTING_CALLS:
                self.logs = True
        elif isinstance(func, ast.Name):
            if func.id in REPORTING_CALLS:
                self.logs = True
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        self.returns_or_assigns_fallback = True
        self.generic_visit(node)


def _root_name(node: ast.AST) -> str | None:
    """Best-effort receiver name: logger.error -> 'logger', a.b.error -> 'b'."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_bare_or_broad(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    name = _root_name(handler.type)
    return name in {"Exception", "BaseException"}


def _exception_label(handler: ast.ExceptHandler) -> str:
    if handler.type is None:
        return "bare except"
    return ast.unparse(handler.type)


def _body_is_only_pass(body: list[ast.stmt]) -> bool:
    return all(isinstance(stmt, (ast.Pass, ast.Expr)) and
               (isinstance(stmt, ast.Pass) or isinstance(stmt.value, ast.Constant))
               for stmt in body)


def _suppressed(handler: ast.ExceptHandler, source_lines: list[str]) -> bool:
    """Honour a `# silentcatch: allow` comment on the except line or the one above."""
    idx = handler.lineno - 1
    candidates = []
    if 0 <= idx < len(source_lines):
        candidates.append(source_lines[idx])
    if 0 <= idx - 1 < len(source_lines):
        candidates.append(source_lines[idx - 1])
    return any(SUPPRESS_COMMENT in line for line in candidates)


def analyse_source(source: str, path: str = "<unknown>") -> list[Finding]:
    """Return findings for one Python source string."""
    try:
        tree = ast.parse(source)
    # silentcatch: allow -- unparseable files are not our concern
    except SyntaxError:
        return []

    source_lines = source.splitlines()
    findings: list[Finding] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if _suppressed(node, source_lines):
            continue

        inspector = _HandlerInspector()
        for stmt in node.body:
            inspector.visit(stmt)

        if inspector.reraises or inspector.raises_new:
            continue

        label = _exception_label(node)
        broad = _is_bare_or_broad(node)

        if inspector.logs:
            # Logged but not re-raised. Only worth flagging on broad handlers,
            # where the code continues past an error it does not understand.
            if broad:
                findings.append(Finding(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset,
                    verdict=Verdict.LOGGED_ONLY,
                    exception_type=label,
                    message=(
                        f"`{label}` is logged but not re-raised. "
                        "Execution continues past an error the code did not "
                        "specifically anticipate."
                    ),
                ))
            continue

        if _body_is_only_pass(node.body):
            detail = "the handler does nothing at all"
        elif inspector.returns_or_assigns_fallback:
            detail = "the handler returns a value instead of surfacing the failure"
        else:
            detail = "nothing in the handler records or re-raises the error"

        findings.append(Finding(
            path=path,
            line=node.lineno,
            col=node.col_offset,
            verdict=Verdict.SILENT,
            exception_type=label,
            message=f"`{label}` is swallowed: {detail}.",
        ))

    return findings


def analyse_file(path: str) -> list[Finding]:
    try:
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
    # silentcatch: allow -- unreadable files are skipped by design
    except (OSError, UnicodeDecodeError):
        return []
    return analyse_source(source, path=path)
