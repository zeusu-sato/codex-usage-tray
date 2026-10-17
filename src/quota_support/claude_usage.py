from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import re
from uuid import UUID
from quota_support.errors import QuotaError
from quota_support.codex_reply import credit_number


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate field")
        result[key] = value
    return result


def _validate_scope_salt(scope_salt):
    if scope_salt is not None and (not isinstance(scope_salt, bytes) or len(scope_salt) < 32):
        raise QuotaError("invalid_scope_salt")


def _scope_key(initialized, scope_salt=None):
    """HMAC only in-memory official account metadata with an app-generated salt.

    The local salt is not a provider credential. Unsalted callers can only use
    explicit UUID identities, never a guessable email hash.
    """
    _validate_scope_salt(scope_salt)
    account = initialized.get("account")
    if not isinstance(account, dict):
        return None
    if scope_salt is not None:
        email = account.get("email")
        if (not isinstance(email, str) or not 1 <= len(email) <= 320
                or not re.fullmatch(r"[^@\s\x00-\x1f\x7f]+@[^@\s\x00-\x1f\x7f]+", email)):
            return None
        identity = {"email": email}
        for field, maximum in (("organization", 1024), ("apiProvider", 64), ("tokenSource", 128)):
            value = account.get(field)
            if value is None:
                continue
            if (not isinstance(value, str) or not 1 <= len(value) <= maximum
                    or not value.strip() or any(ord(character) < 32 or ord(character) == 127 for character in value)):
                return None
            identity[field] = value
        canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        return hmac.new(scope_salt, b"claude-usage-account-v1\0" + canonical, hashlib.sha256).hexdigest()
    try:
        account_id = str(UUID(account["accountUuid"]))
        organization = account.get("organizationUuid")
        organization_id = str(UUID(organization)) if organization is not None else ""
    except (KeyError, ValueError, TypeError, AttributeError):
        return None
    return hashlib.sha256(("claude-usage-v1\0" + account_id + "\0" + organization_id).encode()).hexdigest()


def _usage_fields(data, initialized, scope_salt=None):
    # Deliberately discard behavioral data, account details, and model windows.
    if data.get("behaviors") is not None:
        raise QuotaError("protocol")
    limits = data.get("rate_limits")
    result = {"rate_limits_available": data.get("rate_limits_available"),
              "rate_limits": ({key: {field: value[field] for field in ("utilization", "resets_at")
                                     if field in value} if isinstance(value, dict) else None
                               for key, value in limits.items() if key in ("five_hour", "seven_day")}
                              if isinstance(limits, dict) else None)}
    if isinstance(limits, dict) and isinstance(limits.get("extra_usage"), dict):
        extra = limits["extra_usage"]
        result["rate_limits"]["extra_usage"] = {key: extra[key] for key in
            ("is_enabled", "monthly_limit", "used_credits", "currency") if key in extra}
    scope = _scope_key(initialized, scope_salt=scope_salt)
    if scope is not None:
        result["scope_key"] = scope
    return result


_ISO_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z")


def _reset_time(value):
    if value is None:
        return None
    if not isinstance(value, str) or not _ISO_TIMESTAMP.fullmatch(value):
        raise QuotaError("unsupported_response")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        timestamp = int(parsed.astimezone(timezone.utc).timestamp())
        if timestamp < 0:
            raise ValueError("Negative timestamp")
        return timestamp
    except (ValueError, OverflowError, OSError):
        raise QuotaError("unsupported_response") from None


def normalize(result):
    """Only the complete pair of global windows can report a current amount.

    Null reset times retain a known amount without inventing a refill or forecast.
    Expired timestamps remain expired so the shared cache renderer marks them stale.
    """
    if not isinstance(result, dict):
        raise QuotaError("unsupported_response")
    if result.get("rate_limits_available") is not True:
        raise QuotaError("account_unavailable")
    limits = result.get("rate_limits")
    if not isinstance(limits, dict):
        raise QuotaError("unsupported_response")
    windows = []
    for source, kind, duration in (("five_hour", "primary", 300), ("seven_day", "secondary", 10080)):
        if source not in limits or limits[source] is None:
            raise QuotaError("incomplete_windows")
        raw = limits[source]
        if not isinstance(raw, dict) or "resets_at" not in raw:
            raise QuotaError("unsupported_response")
        used = raw.get("utilization")
        if (isinstance(used, bool) or not isinstance(used, (int, float))
                or (isinstance(used, float) and not math.isfinite(used)) or used < 0):
            raise QuotaError("unsupported_response")
        windows.append({"kind": kind, "remaining_percent": max(0, 100 - used),
                        "duration_mins": duration, "resets_at": _reset_time(raw["resets_at"])})
    # Shared UI reserves blocked for an explicit non-quota restriction. Known
    # exhaustion remains numeric zero so it can be displayed as a red amount.
    credit = None
    extra = limits.get("extra_usage")
    if any(w["remaining_percent"] == 0 for w in windows) and isinstance(extra, dict) and extra.get("is_enabled") is True:
        limit = extra.get("monthly_limit")
        currency = extra.get("currency")
        currency = "USD" if currency is None else currency
        credit = {"kind": "claude_extra_usage",
                  "currency": currency if isinstance(currency, str) and re.fullmatch(r"[A-Z]{3}", currency) else None,
                  "monthly_limit": limit if credit_number(limit) else None,
                  "limit_known": "monthly_limit" in extra and (limit is None or credit_number(limit)),
                  "used_credits": extra.get("used_credits") if credit_number(extra.get("used_credits")) else None}
    return {"windows": windows, "blocked": False, "credit": credit}
