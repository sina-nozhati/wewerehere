"""Jalali schedule strings aligned with assets/wwh-datetime.js (Tehran TZ)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")

ORDINALS = [
    "",
    "اول",
    "دوم",
    "سوم",
    "چهارم",
    "پنجم",
    "ششم",
    "هفتم",
    "هشتم",
    "نهم",
    "دهم",
    "یازدهم",
    "دوازدهم",
    "سیزدهم",
    "چهاردهم",
    "پانزدهم",
    "شانزدهم",
    "هفدهم",
    "هجدهم",
    "نوزدهم",
    "بیستم",
    "بیست‌و‌یکم",
    "بیست‌و‌دوم",
    "بیست‌و‌سوم",
    "بیست‌و‌چهارم",
    "بیست‌و‌پنجم",
    "بیست‌و‌ششم",
    "بیست‌و‌هفتم",
    "بیست‌و‌هشتم",
    "بیست‌و‌نهم",
    "سی‌ام",
    "سی‌و‌یکم",
]

PERSIAN_MONTHS = (
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
)

MONTHS_LATIN = (
    "Farvardin",
    "Ordibehesht",
    "Khordad",
    "Tir",
    "Mordad",
    "Shahrivar",
    "Mehr",
    "Aban",
    "Azar",
    "Dey",
    "Bahman",
    "Esfand",
)

_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC_SCRIPT = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")
_LATIN = re.compile(r"[A-Za-z]")


def to_persian_digits(value: str | int) -> str:
    return "".join(_PERSIAN_DIGITS[int(c)] if c.isdigit() else c for c in str(value))


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """Convert Gregorian date to Jalali (jy, jm, jd)."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    if gm > 2:
        gy2 = gy + 1
    else:
        gy2 = gy
    days = (
        365 * gy
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        - 80
        + gd
        + g_d_m[gm - 1]
    )
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy + 1600 if jy > 979 else jy + 621, jm, jd


def ordinal_day_fa(day: int) -> str:
    if 1 <= day < len(ORDINALS):
        return ORDINALS[day]
    return to_persian_digits(day)


def ticket_locale(venue: str = "", city: str = "") -> str:
    """fa = Persian date + Persian digits on time; en = Latin digits + Latin month label."""
    blob = f"{venue} {city}".strip()
    if not blob:
        return "fa"
    latin = len(_LATIN.findall(blob))
    arabic = len(_ARABIC_SCRIPT.findall(blob))
    if latin >= 4 and latin > arabic:
        return "en"
    return "fa"


@dataclass(frozen=True)
class HeroSchedule:
    tagline: str
    time_hm: str
    locale: str = "fa"


def format_hero_schedule(
    event_at: datetime | None,
    *,
    venue: str = "",
    city: str = "",
) -> HeroSchedule:
    if event_at is None:
        return HeroSchedule(tagline="", time_hm="", locale="fa")
    if event_at.tzinfo is None:
        event_at = event_at.replace(tzinfo=timezone.utc)
    local = event_at.astimezone(TEHRAN)
    _, jm, jd = gregorian_to_jalali(local.year, local.month, local.day)
    month_fa = PERSIAN_MONTHS[jm - 1] if 1 <= jm <= 12 else ""
    month_en = MONTHS_LATIN[jm - 1] if 1 <= jm <= 12 else ""
    blob = f"{venue} {city}".strip()
    has_latin = bool(_LATIN.search(blob))
    has_arabic = bool(_ARABIC_SCRIPT.search(blob))
    loc = ticket_locale(venue, city)
    time_ascii = has_latin or loc == "en"
    time_hm = (
        f"{local.hour:02d}:{local.minute:02d}"
        if time_ascii
        else to_persian_digits(f"{local.hour:02d}:{local.minute:02d}")
    )

    if loc == "en" and not has_arabic:
        tagline = f"{jd} {month_en}".strip() if month_en else str(jd)
    else:
        ordinal = ordinal_day_fa(jd)
        tagline = f"{ordinal} {month_fa}".strip() if month_fa else ordinal

    return HeroSchedule(tagline=tagline, time_hm=time_hm, locale=loc)


def venue_display_line(venue: str, city: str = "", host_venue: str = "") -> str:
    for part in (venue, host_venue, city):
        p = (part or "").strip()
        if p:
            return p
    return ""


def ticket_city_line(city: str = "") -> str:
    c = (city or "").strip()
    if not c:
        return ""
    return f"Live in {c}"
