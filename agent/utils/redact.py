"""Redact PII in logs and exported JSON (HIPAA-aware logging)."""
import re


def redact_phone(phone: str) -> str:
    """Keep last 4 digits only when length allows."""
    p = re.sub(r"\D", "", phone or "")
    if len(p) <= 4:
        return "***" if p else ""
    return f"***{p[-4:]}"


def redact_name(name: str) -> str:
    """Initials only for logging."""
    n = (name or "").strip()
    if not n:
        return ""
    parts = n.split()
    return "".join(p[0].upper() for p in parts if p) + "."


def redact_for_log(text: str, max_len: int = 120) -> str:
    """Truncate long strings that might contain PII."""
    t = (text or "").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 3] + "..."
