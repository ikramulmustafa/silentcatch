"""Deliberately flawed example code for manually testing silentcatch.

Expected result: 2 swallowed (failures), 1 logged-only (warning).
"""

import logging

logger = logging.getLogger(__name__)


class PaymentError(Exception):
    pass


def charge_card(gateway, card, amount):
    # FAILURE: the charge can fail and the caller is told it succeeded.
    try:
        return gateway.charge(card, amount)
    except Exception:
        return {"status": "success", "amount": amount}


def verify_password(user, password, hasher):
    # FAILURE: any error during verification lets the user in.
    try:
        return hasher.verify(user.password_hash, password)
    except Exception:
        return True


def refund(gateway, transaction_id):
    # WARNING: the error is logged but never surfaces to the caller.
    try:
        gateway.refund(transaction_id)
    except Exception:
        logger.error("refund failed for %s", transaction_id)


def parse_amount(raw):
    # OK: a narrow exception is wrapped and re-raised.
    try:
        return int(raw)
    except ValueError as exc:
        raise PaymentError(f"invalid amount: {raw!r}") from exc


def warm_cache(cache):
    # SUPPRESSED: a cache warm-up failure is harmless and deliberate to ignore.
    try:
        cache.warm()
    except Exception:  # silentcatch: allow -- cache warm-up is best-effort
        pass
