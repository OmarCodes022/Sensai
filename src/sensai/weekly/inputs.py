"""The weekly run's inputs (T45): brand, DMs, engagement figures and earlier posts, each read on its own.

A missing or broken file raises InputError for the outputs that need it; the others still run.
"""
import csv
import json
import os
from dataclasses import dataclass


class InputError(ValueError):
    """One input file is missing or cannot be used."""


@dataclass(frozen=True)
class Figures:
    start: str
    end: str
    source: str
    reached: int
    engaged: int
    rate: str  # "15.0%", or "n/a (zero reach)": computed here, never by the model


def _json(folder: str, name: str, key: str) -> list[dict]:
    path = os.path.join(folder, name)
    try:
        with open(path, encoding="utf-8") as f:
            items = json.load(f)[key]
    except FileNotFoundError:
        raise InputError(f"{name} is missing") from None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise InputError(f"{name} cannot be read: {exc}") from None
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise InputError(f"{name}: '{key}' must be a list of objects")
    return items


def brand_file(folder: str) -> str:
    """The folder's brand.json: the approved claims every output is checked against."""
    path = os.path.join(folder, "brand.json")
    _json(folder, "brand.json", "products")
    return path


def dms(folder: str) -> list[dict]:
    return _json(folder, "dms.json", "dms")


def earlier_posts(folder: str) -> list[str]:
    """Captions of last week's valid posts, as examples of the voice; invalid ones are never shown to the model."""
    try:
        posts = _json(folder, "posts.json", "posts")
    except InputError:
        return []
    return [p["caption"] for p in posts if p.get("valid") is True and isinstance(p.get("caption"), str)]


def figures(folder: str) -> Figures:
    """The weekly row of engagement.csv (its date is a "start/end" period)."""
    path = os.path.join(folder, "engagement.csv")
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = [row for row in csv.DictReader(f) if "/" in (row.get("date") or "")]
    except FileNotFoundError:
        raise InputError("engagement.csv is missing") from None
    except (OSError, csv.Error, UnicodeDecodeError) as exc:
        raise InputError(f"engagement.csv cannot be read: {exc}") from None
    if not rows:
        raise InputError("engagement.csv has no weekly row (a date like 2026-09-21/2026-09-27)")
    row = rows[-1]
    try:
        reached, engaged = int(row["accounts_reached"]), int(row["accounts_engaged"])
    except (KeyError, TypeError, ValueError):
        raise InputError("engagement.csv: the weekly row needs whole accounts_reached and accounts_engaged") from None
    if reached < 0 or engaged < 0 or engaged > reached:
        raise InputError(f"engagement.csv: {engaged} engaged out of {reached} reached is impossible")
    start, end = row["date"].split("/", 1)
    rate = f"{engaged * 100 / reached:.1f}%" if reached else "n/a (zero reach)"
    return Figures(start, end, row.get("source") or "engagement.csv", reached, engaged, rate)
