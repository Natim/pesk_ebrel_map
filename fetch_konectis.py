#!/usr/bin/env python3
"""Fetch the latest GPS fix from the public Konectis embed dataPreload JSON."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from fetch_ais import (
    AisFix,
    FetchError,
    append_fix,
    fetch_html,
    format_iso,
    update_last_fix,
)
from validate_positions import ValidationError, parse_observed_at, parse_optional_float, validate_path

DEFAULT_URL = "https://www.konectis.com/embed/12684aeeab22233e7323c2b0f5197001"
NOTE = "GPS Konectis"
# ~0.001° ≈ 100 m at this latitude — treat as the same berth.
SAME_POSITION_DEG = 0.001

DATA_PRELOAD_RE = re.compile(
    r"dataPreload\s*=\s*(\{.*?\})\s*;\s*l10nPreload",
    re.DOTALL,
)


def parse_heading(value: object) -> float | None:
    if value is None:
        return None
    try:
        heading = float(str(value).strip())
    except ValueError:
        return None
    if heading < 0:
        return None
    return parse_optional_float(str(heading), "course_deg", 0, 360)


def parse_speed_kn(value: object) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        speed = float(str(value).strip())
    except ValueError as exc:
        raise FetchError(f"unreadable speed: {value!r}") from exc
    return parse_optional_float(str(speed), "speed_kn", 0, 80)


def format_alarms(raw: object) -> str:
    if not isinstance(raw, list) or not raw:
        return ""
    names: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            for key in ("title", "name", "description", "alarm"):
                label = item.get(key)
                if isinstance(label, str) and label.strip():
                    names.append(label.strip())
                    break
            else:
                names.append(str(item))
        elif isinstance(item, str) and item.strip():
            names.append(item.strip())
    return "; ".join(names)


def parse_embed_page(html: str) -> AisFix:
    match = DATA_PRELOAD_RE.search(html)
    if match is None:
        raise FetchError("no dataPreload JSON on the Konectis embed page")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise FetchError("dataPreload is not valid JSON") from exc

    assets = payload.get("assets")
    if not isinstance(assets, list) or not assets:
        raise FetchError("dataPreload has no assets")

    first = assets[0]
    if not isinstance(first, dict):
        raise FetchError("dataPreload asset is not an object")
    last = first.get("LastPosition")
    if not isinstance(last, dict):
        raise FetchError("Konectis embed has no LastPosition")

    try:
        latitude = float(str(last["latitude"]).strip())
        longitude = float(str(last["longitude"]).strip())
    except (KeyError, TypeError, ValueError) as exc:
        raise FetchError(f"LastPosition coordinates incomplete: {last!r}") from exc
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise FetchError(f"LastPosition out of range: {latitude}, {longitude}")

    stamp = last.get("received_datestamp_utc") or last.get("received_datestamp")
    if not isinstance(stamp, str) or not stamp.strip():
        raise FetchError("LastPosition has no received_datestamp_utc")
    observed_at = parse_observed_at(stamp.strip())

    speed_kn = parse_speed_kn(last.get("speed"))
    course_deg = parse_heading(last.get("heading"))
    alarms = format_alarms(last.get("Alarms"))

    return AisFix(
        observed_at=observed_at,
        latitude=latitude,
        longitude=longitude,
        speed_kn=speed_kn,
        course_deg=course_deg,
        alarms=alarms,
    )


def same_position(
    lat_a: float,
    lon_a: float,
    lat_b: float,
    lon_b: float,
    *,
    threshold_deg: float = SAME_POSITION_DEG,
) -> bool:
    return abs(lat_a - lat_b) <= threshold_deg and abs(lon_a - lon_b) <= threshold_deg


def apply_konectis_fix(csv_path: Path, fix: AisFix) -> bool:
    """Append at a new place, or refresh the lone Konectis pin when still at berth."""
    positions = validate_path(csv_path)
    latest = positions[-1]
    if fix.observed_at <= latest.observed_at:
        print(
            f"No new position (latest CSV {format_iso(latest.observed_at)}, "
            f"fetched {format_iso(fix.observed_at)})"
        )
        return False

    if same_position(fix.latitude, fix.longitude, latest.latitude, latest.longitude):
        if latest.note == NOTE:
            return update_last_fix(csv_path, fix, note=NOTE)
        return append_fix(csv_path, fix, note=NOTE)

    return append_fix(csv_path, fix, note=NOTE)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=Path("docs/positions.csv"))
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--html", type=Path, help="Parse a saved HTML file instead of fetching")
    args = parser.parse_args(argv)
    try:
        html = args.html.read_text(encoding="utf-8") if args.html else fetch_html(args.url)
        fix = parse_embed_page(html)
        apply_konectis_fix(args.csv, fix)
    except (FetchError, ValidationError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
