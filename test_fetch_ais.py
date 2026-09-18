from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fetch_ais import append_fix, parse_mt_timezone, parse_ship_page, AisFix
from validate_positions import validate_path

FIXTURE = """
<html><body>
<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "GeoCoordinates",
    "name": "PESK EBREL",
    "latitude": "33.490368",
    "longitude": "-16.947184"
}
</script>
Latest AIS information
Vessel's local time
2026-09-18 10:51 (UTC+0)
Speed
5.5 kn
Course
167 °
</body></html>
"""


class ParseShipPageTests(unittest.TestCase):
    def test_json_ld_and_visible_ais_fields(self) -> None:
        fix = parse_ship_page(FIXTURE)
        self.assertEqual(fix.observed_at, datetime(2026, 9, 18, 10, 51, tzinfo=timezone.utc))
        self.assertAlmostEqual(fix.latitude, 33.490368)
        self.assertAlmostEqual(fix.longitude, -16.947184)
        self.assertEqual(fix.speed_kn, 5.5)
        self.assertEqual(fix.course_deg, 167.0)

    def test_timezone_utc_plus_zero(self) -> None:
        self.assertEqual(parse_mt_timezone("UTC+0"), "+00:00")
        self.assertEqual(parse_mt_timezone("UTC+2"), "+02:00")
        self.assertEqual(parse_mt_timezone("UTC"), "+00:00")


class AppendFixTests(unittest.TestCase):
    def test_skips_same_or_older_timestamp(self) -> None:
        payload = (
            "observed_at,latitude,longitude,speed_kn,course_deg,alarms,note\n"
            "2026-09-18T10:51:00Z,33.490368,-16.947184,5.5,167,,AIS MarineTraffic\n"
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "positions.csv"
            path.write_text(payload, encoding="utf-8")
            added = append_fix(
                path,
                AisFix(
                    observed_at=datetime(2026, 9, 18, 10, 51, tzinfo=timezone.utc),
                    latitude=33.5,
                    longitude=-16.9,
                    speed_kn=5.5,
                    course_deg=167,
                ),
            )
            self.assertFalse(added)
            self.assertEqual(len(validate_path(path)), 1)

    def test_appends_newer_fix(self) -> None:
        payload = (
            "observed_at,latitude,longitude,speed_kn,course_deg,alarms,note\n"
            "2026-09-18T10:51:00Z,33.490368,-16.947184,5.5,167,,AIS MarineTraffic\n"
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "positions.csv"
            path.write_text(payload, encoding="utf-8")
            added = append_fix(
                path,
                AisFix(
                    observed_at=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc),
                    latitude=33.1,
                    longitude=-16.8,
                    speed_kn=6.0,
                    course_deg=170,
                ),
            )
            self.assertTrue(added)
            positions = validate_path(path)
            self.assertEqual(len(positions), 2)
            self.assertEqual(positions[-1].note, "AIS MarineTraffic")


if __name__ == "__main__":
    unittest.main()
