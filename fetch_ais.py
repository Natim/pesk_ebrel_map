#!/usr/bin/env python3
"""Fetch the latest AIS fix from the public MarineTraffic ship page JSON-LD."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from validate_positions import (
    REQUIRED_COLUMNS,
    ValidationError,
    parse_observed_at,
    parse_optional_float,
    validate_path,
)

DEFAULT_URL = "https://www.marinetraffic.com/en/ais/details/ships/shipid:9909327"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
NOTE = "AIS MarineTraffic"

JSONLD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>\s*(.*?)\s*</script>',
    re.DOTALL | re.IGNORECASE,
)
LOCAL_TIME_RE = re.compile(
    r"Vessel's local time\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*\((UTC[^)]+)\)",
    re.IGNORECASE,
)
SPEED_RE = re.compile(r"\bSpeed\s+([\d.,]+)\s*kn\b", re.IGNORECASE)
COURSE_RE = re.compile(r"\bCourse\s+([\d.,]+)\s*°", re.IGNORECASE)
UTC_OFFSET_RE = re.compile(r"^UTC(?:\s*([+-])\s*(\d{1,2}))?$", re.IGNORECASE)


@dataclass(frozen=True)
class AisFix:
    observed_at: datetime
    latitude: float
    longitude: float
    speed_kn: float | None
    course_deg: float | None


class FetchError(RuntimeError):
    pass


def fetch_html(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:400]
        if exc.code in {403, 429, 503} or "cloudflare" in body.lower() or "attention required" in body.lower():
            raise FetchError(
                f"MarineTraffic blocked the request (HTTP {exc.code}). "
                "GitHub Actions IPs are often filtered; run the workflow by hand or keep updating the CSV."
            ) from exc
        raise FetchError(f"MarineTraffic HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"cannot reach MarineTraffic: {exc}") from exc
    return raw.decode(charset, errors="replace")


def _as_objects(payload: object) -> list[dict]:
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def parse_geo_ld(html: str) -> tuple[float, float]:
    for match in JSONLD_RE.finditer(html):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        for item in _as_objects(payload):
            types = item.get("@type")
            type_names = types if isinstance(types, list) else [types]
            if "GeoCoordinates" not in type_names:
                continue
            try:
                latitude = float(str(item["latitude"]).strip())
                longitude = float(str(item["longitude"]).strip())
            except (KeyError, TypeError, ValueError) as exc:
                raise FetchError(f"GeoCoordinates JSON-LD is incomplete: {item!r}") from exc
            if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                raise FetchError(f"GeoCoordinates out of range: {latitude}, {longitude}")
            return latitude, longitude
    raise FetchError("no schema.org GeoCoordinates JSON-LD on the ship page")


def parse_mt_timezone(label: str) -> str:
    match = UTC_OFFSET_RE.fullmatch(label.strip())
    if match is None:
        raise FetchError(f"unreadable timezone: {label!r}")
    sign, hours = match.group(1), match.group(2)
    if not hours:
        return "+00:00"
    return f"{sign}{int(hours):02d}:00"


def parse_visible_ais(html: str) -> tuple[datetime, float | None, float | None]:
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text)

    time_match = LOCAL_TIME_RE.search(text)
    if time_match is None:
        raise FetchError("could not find Vessel's local time on the ship page")
    stamp = time_match.group(1)
    offset = parse_mt_timezone(time_match.group(2))
    observed_at = parse_observed_at(f"{stamp}:00{offset}")

    speed_match = SPEED_RE.search(text)
    course_match = COURSE_RE.search(text)
    speed_kn = (
        parse_optional_float(speed_match.group(1), "speed_kn", 0, 80) if speed_match else None
    )
    course_deg = (
        parse_optional_float(course_match.group(1), "course_deg", 0, 360) if course_match else None
    )
    return observed_at, speed_kn, course_deg


def parse_ship_page(html: str) -> AisFix:
    lowered = html.lower()
    if "cloudflare" in lowered and (
        "attention required" in lowered or "sorry, you have been blocked" in lowered
    ):
        raise FetchError("MarineTraffic returned a Cloudflare challenge page")
    if "geocoordinates" not in lowered and "pesk ebrel" not in lowered:
        raise FetchError(
            "MarineTraffic did not return the ship page (bot wall or homepage). "
            "Hourly GitHub Actions IPs are often blocked; update docs/positions.csv by hand."
        )
    latitude, longitude = parse_geo_ld(html)
    observed_at, speed_kn, course_deg = parse_visible_ais(html)
    return AisFix(
        observed_at=observed_at,
        latitude=latitude,
        longitude=longitude,
        speed_kn=speed_kn,
        course_deg=course_deg,
    )


def format_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_optional(value: float | None) -> str:
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def append_fix(csv_path: Path, fix: AisFix) -> bool:
    positions = validate_path(csv_path)
    latest = positions[-1]
    if fix.observed_at <= latest.observed_at:
        print(
            f"No new AIS report (latest CSV {format_iso(latest.observed_at)}, "
            f"page {format_iso(fix.observed_at)})"
        )
        return False

    row = {
        "observed_at": format_iso(fix.observed_at),
        "latitude": f"{fix.latitude:.6f}".rstrip("0").rstrip("."),
        "longitude": f"{fix.longitude:.6f}".rstrip("0").rstrip("."),
        "speed_kn": format_optional(fix.speed_kn),
        "course_deg": format_optional(fix.course_deg),
        "alarms": "",
        "note": NOTE,
    }
    with csv_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS, lineterminator="\n")
        writer.writerow(row)
    validate_path(csv_path)
    print(
        f"Appended {row['observed_at']} at {row['latitude']}, {row['longitude']} "
        f"{row['speed_kn']} kn {row['course_deg']}°"
    )
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=Path("docs/positions.csv"))
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--html", type=Path, help="Parse a saved HTML file instead of fetching")
    args = parser.parse_args(argv)
    try:
        html = args.html.read_text(encoding="utf-8") if args.html else fetch_html(args.url)
        fix = parse_ship_page(html)
        append_fix(args.csv, fix)
    except (FetchError, ValidationError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
