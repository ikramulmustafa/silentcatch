from silentcatch.detector import Verdict, analyse_source


def verdicts(src):
    return [f.verdict for f in analyse_source(src, "t.py")]


def test_bare_pass_is_silent():
    assert verdicts("""
try:
    risky()
except Exception:
    pass
""") == [Verdict.SILENT]


def test_return_fallback_is_silent():
    assert verdicts("""
def check(user, password):
    try:
        return verify(password, user.hash)
    except Exception:
        return True
""") == [Verdict.SILENT]


def test_reraise_is_ok():
    assert verdicts("""
try:
    risky()
except ValueError:
    raise
""") == []


def test_raise_new_is_ok():
    assert verdicts("""
try:
    risky()
except ValueError as e:
    raise RuntimeError("failed") from e
""") == []


def test_narrow_handler_with_log_is_ok():
    assert verdicts("""
try:
    parse(x)
except ValueError:
    logger.warning("bad input")
""") == []


def test_broad_handler_with_log_is_warning():
    assert verdicts("""
try:
    parse(x)
except Exception:
    logger.error("something went wrong")
""") == [Verdict.LOGGED_ONLY]


def test_bare_except_with_log_is_warning():
    assert verdicts("""
try:
    parse(x)
except:
    log.error("oops")
""") == [Verdict.LOGGED_ONLY]


def test_suppression_comment_on_handler_line():
    assert verdicts("""
try:
    optional()
except Exception:  # silentcatch: allow
    pass
""") == []


def test_suppression_comment_above():
    assert verdicts("""
try:
    optional()
# silentcatch: allow
except Exception:
    pass
""") == []


def test_non_logger_error_method_does_not_count():
    assert verdicts("""
try:
    send()
except Exception:
    response.error()
""") == [Verdict.SILENT]


def test_sentry_capture_counts_as_reporting():
    assert verdicts("""
try:
    send()
except Exception:
    capture_exception()
""") == [Verdict.LOGGED_ONLY]


def test_nested_handlers_both_seen():
    result = verdicts("""
try:
    a()
except Exception:
    try:
        b()
    except Exception:
        pass
""")
    assert result == [Verdict.SILENT, Verdict.SILENT]


def test_syntax_error_returns_nothing():
    assert analyse_source("def broken(:", "t.py") == []


def test_narrow_handler_silent_still_flagged():
    assert verdicts("""
try:
    parse(x)
except ValueError:
    pass
""") == [Verdict.SILENT]


def test_finding_carries_location():
    findings = analyse_source("""
try:
    risky()
except Exception:
    pass
""", "app/service.py")
    assert findings[0].path == "app/service.py"
    assert findings[0].line == 4
    assert findings[0].is_failure is True
