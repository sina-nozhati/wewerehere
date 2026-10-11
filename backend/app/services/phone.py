import re

_PHONE_RE = re.compile(r"^09\d{9}$")
_DIGIT_TRANSLATION = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_digits(raw: str) -> str:
    return str(raw or "").translate(_DIGIT_TRANSLATION)


def normalize_phone(raw: str) -> str:
    return re.sub(r"\s", "", normalize_digits(raw))


def valid_phone(phone: str) -> bool:
    return bool(_PHONE_RE.match(phone))


def normalize_serial(raw: str) -> str:
    """Return only entered digits; unlike zfill, blank input stays blank."""
    return re.sub(r"\D", "", normalize_digits(raw))
