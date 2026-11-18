# silentcatch

Fails your build when a pull request introduces an exception handler that swallows failures.

```python
def verify_password(user, password):
    try:
        return hash_password(password) == user.password_hash
    except Exception:
        return True          # <- everyone gets in
```

Tests pass. Linters pass. Type checkers pass. The function returns a bool, as declared.

## Why this exists

Static analysis is good at the things that are visibly wrong. Swallowed exceptions are not visibly wrong. The code runs, returns a plausible value, and logs nothing. You find out weeks later, from a number that does not reconcile.

This has always been a problem. It got worse when code started being generated faster than it gets read, because a model asked to "handle the error" will reliably produce a handler that makes the error go away rather than one that surfaces it.

The fix is not more review. It is making the codebase refuse the pattern.

## What it flags

**Failures** (exit 1):

- A handler whose body is `pass`
- A handler that returns a fallback value without logging or re-raising
- A handler that does something unrelated and never records the error

**Warnings** (exit 0 unless `--strict`):

- A broad handler (`except Exception`, bare `except`) that logs but does not re-raise

The second category is deliberately a warning. Catching broadly and logging is sometimes correct, at a request boundary or a task runner. It is worth seeing, not worth blocking.

## What it does not flag

- Narrow handlers that log. `except ValueError: logger.warning(...)` is a considered decision.
- Anything that re-raises, bare or chained.
- Handlers reporting to Sentry and similar (`capture_exception`, `report`, `notify`).
- Anything marked `# silentcatch: allow`.

## Install

```bash
pip install silentcatch
```

## Use

```bash
# whole project
silentcatch .

# just one package
silentcatch src/

# only lines changed in this PR
silentcatch --base origin/main

# also fail on broad handlers that log but do not re-raise
silentcatch --strict
```

Exit code is 1 if anything failed, 0 otherwise.

## GitHub Action

```yaml
name: silentcatch

on: [pull_request]

jobs:
  silentcatch:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0          # needed for --base
      - uses: ikramulmustafa/silentcatch@v1
        with:
          base: origin/${{ github.base_ref }}
```

Findings appear as inline annotations on the diff.

`--base` matters on an existing codebase. Without it the first run surfaces every handler you have ever written, the check gets disabled, and nothing improves. Diff mode holds new code to the standard and leaves the backlog alone.

## Suppressing

Some handlers genuinely should swallow. Optional telemetry, best-effort cache warming, cleanup in a `finally` path.

```python
try:
    telemetry.send(event)
except Exception:  # silentcatch: allow
    pass
```

The comment goes on the `except` line or the line above it. Requiring an explicit marker is the point: the decision gets made once, in writing, where a reviewer can see it.

## Limitations

Worth knowing before you adopt it.

- **Python only.** The approach ports to other languages; this implementation does not.
- **Logger detection is heuristic.** It matches method names (`error`, `warning`, `exception`) against plausible receivers (`logger`, `log`, `self`). A custom logging wrapper with an unusual name will not be recognised, and you will get a false positive.
- **It cannot tell intent.** A handler that returns a safe default because that genuinely is the right behaviour looks identical to one that hides a bug. That is why the suppression comment exists rather than a cleverer rule.
- **Single-file analysis.** No cross-module awareness. If your handler calls a helper that logs, that is not detected.

The false positive rate is the thing to watch. A check that fires on correct code gets disabled, and a disabled check is worth less than no check.

## How it works

Parses each file with `ast`, walks every `ExceptHandler`, and inspects the body for evidence the failure was recorded: a `raise`, a logging call, or a reporting call. No evidence means the exception is being swallowed.

Roughly 200 lines. No dependencies beyond the standard library.

## Contributing

Issues and pull requests welcome. False positives are the most useful thing you can report: a real handler it flagged that it should not have, with the code.

## Licence

MIT
