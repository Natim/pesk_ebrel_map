#!/usr/bin/env python3
"""Validate docs/positions.csv — the satellite track of Pesk Ebrel."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_COLUMNS = (
    "observed_at",
    "latitude",
    "longitude",
    "speed_kn",
    "course_deg",
    "alarms",
    "note",
)

COORD_RE = re.compile(
    r"""
    ^\s*
    (?P<hem_pre>[NSEW])?\s*
    (?P<sign>-)?
    (?P<deg>\d+(?:[.,]\d+)?)
    (?:
        [°d\s]+
        (?P<min>\d+(?:[.,]\d+)?)
        (?:
            \s*['′m]?\s*
            (?P<sec>\d+(?:[.,]\d+)?)
            \s*["″s]?
        )?
        \s*[°d]?
    )?
    \s*(?P<hem_post>[NSEW])?
    \s*$
    """,
    re.VERBOSE | re.IGNORECASE,
)

DATETIME_RE = re.compile(
    r"""
    ^\s*
    (?P<date>\d{4}-\d{2}-\d{2})
    [ T]
    (?P<time>\d{2}:\d{2}(?::\d{2})?)
    (?P<frac>\.\d+)?
    \s*(?P<tz>Z|UTC|[+-]\d{2}:?\d{2})?
    \s*$
    """,
    re.VERBOSE | re.IGNORECASE,
)


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Position:
    observed_at: datetime
    latitude: float
    longitude: float
    speed_kn: float | None
    course_deg: float | None
    alarms: str
    note: str
    raw: dict[str, str]


def parse_number(value: str) -> float:
    return float(value.replace(",", ".").strip())


def parse_coordinate(text: str, axis: str) -> float:
    raw = (text or "").strip()
    if not raw:
        raise ValidationError(f"{axis} is empty")

    match = COORD_RE.fullmatch(raw)
    if match is None:
        raise ValidationError(f"unreadable {axis}: {text!r}")

    deg = parse_number(match.group("deg"))
    minutes = parse_number(match.group("min")) if match.group("min") else 0.0
    seconds = parse_number(match.group("sec")) if match.group("sec") else 0.0
    if minutes >= 60 or seconds >= 60:
        raise ValidationError(f"invalid DMS minutes/seconds in {axis}: {text!r}")

    magnitude = abs(deg) + minutes / 60.0 + seconds / 3600.0
    if match.group("sign"):
        magnitude *= -1

    hem_pre = (match.group("hem_pre") or "").upper()
    hem_post = (match.group("hem_post") or "").upper()
    if hem_pre and hem_post:
        raise ValidationError(f"two hemispheres in {axis}: {text!r}")
    hemisphere = hem_pre or hem_post

    if hemisphere:
        if axis == "latitude" and hemisphere not in "NS":
            raise ValidationError(f"latitude needs N/S, got {text!r}")
        if axis == "longitude" and hemisphere not in "EW":
            raise ValidationError(f"longitude needs E/W, got {text!r}")
        if hemisphere in "SW":
            magnitude = -abs(magnitude)
        else:
            magnitude = abs(magnitude)

    if axis == "latitude" and not -90 <= magnitude <= 90:
        raise ValidationError(f"latitude out of range: {magnitude}")
    if axis == "longitude" and not -180 <= magnitude <= 180:
        raise ValidationError(f"longitude out of range: {magnitude}")
    return magnitude


def parse_observed_at(text: str) -> datetime:
    raw = (text or "").strip()
    match = DATETIME_RE.fullmatch(raw)
    if match is None:
        raise ValidationError(f"unreadable timestamp: {text!r}")

    date = match.group("date")
    time = match.group("time")
    if len(time) == 5:
        time += ":00"
    frac = match.group("frac") or ""
    tz = (match.group("tz") or "Z").upper()
    if tz == "UTC":
        tz = "Z"
    elif tz != "Z" and ":" not in tz:
        tz = f"{tz[:3]}:{tz[3:]}"

    iso = f"{date}T{time}{frac}{tz}"
    try:
        value = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"unreadable timestamp: {text!r}") from exc
    return value.astimezone(timezone.utc)


def parse_optional_float(text: str, label: str, minimum: float, maximum: float) -> float | None:
    raw = (text or "").strip()
    if not raw:
        return None
    cleaned = re.sub(r"(?i)\s*(kn|nds?|kt|n\.?m\.?|nm|°|deg)?\s*$", "", raw)
    try:
        value = parse_number(cleaned)
    except ValueError as exc:
        raise ValidationError(f"unreadable {label}: {text!r}") from exc
    if not minimum <= value <= maximum:
        raise ValidationError(f"{label} out of range: {value}")
    return value


def load_positions(path: Path) -> list[Position]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationError(f"cannot read {path}: {exc}") from exc

    if text.startswith("\ufeff"):
        text = text[1:]

    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None:
        raise ValidationError("CSV has no header")

    columns = [name.strip() for name in reader.fieldnames]
    missing = [name for name in REQUIRED_COLUMNS if name not in columns]
    if missing:
        raise ValidationError(f"missing columns: {', '.join(missing)}")

    positions: list[Position] = []
    seen: dict[datetime, int] = {}
    for index, row in enumerate(reader, start=2):
        if row is None:
            continue
        cells = {key: (value or "").strip() for key, value in row.items() if key}
        if all(not value for value in cells.values()):
            continue
        try:
            observed_at = parse_observed_at(cells.get("observed_at", ""))
            position = Position(
                observed_at=observed_at,
                latitude=parse_coordinate(cells.get("latitude", ""), "latitude"),
                longitude=parse_coordinate(cells.get("longitude", ""), "longitude"),
                speed_kn=parse_optional_float(cells.get("speed_kn", ""), "speed_kn", 0, 80),
                course_deg=parse_optional_float(cells.get("course_deg", ""), "course_deg", 0, 360),
                alarms=cells.get("alarms", ""),
                note=cells.get("note", ""),
                raw=cells,
            )
        except ValidationError as exc:
            raise ValidationError(f"{path}:{index}: {exc}") from exc

        previous = seen.get(position.observed_at)
        if previous is not None:
            raise ValidationError(
                f"{path}:{index}: duplicate timestamp {cells['observed_at']!r} (also line {previous})"
            )
        seen[position.observed_at] = index
        positions.append(position)

    if not positions:
        raise ValidationError(f"{path}: no position rows")
    return positions


def validate_path(path: Path) -> list[Position]:
    positions = load_positions(path)
    positions.sort(key=lambda item: item.observed_at)
    return positions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "csv_path",
        nargs="?",
        default="docs/positions.csv",
        type=Path,
        help="CSV to validate (default: docs/positions.csv)",
    )
    args = parser.parse_args(argv)
    try:
        positions = validate_path(args.csv_path)
    except ValidationError as exc:
        print(exc, file=sys.stderr)
        return 1
    latest = positions[-1]
    print(
        f"{args.csv_path}: {len(positions)} position(s), "
        f"latest {latest.observed_at.strftime('%Y-%m-%d %H:%M:%SZ')} "
        f"at {latest.latitude:.6f}, {latest.longitude:.6f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
