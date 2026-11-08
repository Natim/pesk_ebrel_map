from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fetch_ais import AisFix
from fetch_konectis import NOTE, apply_konectis_fix, parse_embed_page, same_position
from validate_positions import validate_path

FIXTURE = """
<html><body>
<script>
dataPreload = {"assets":[{"Asset":{"name":"PeskEbrel"},"LastPosition":{
  "latitude":"28.467711",
  "longitude":"-16.244166",
  "heading":"180",
  "speed":"0.0",
  "received_datestamp_utc":"2026-11-05 00:40:50",
  "Alarms":[]
}}]};
l10nPreload = {};
</script>
</body></html>
"""


class ParseEmbedTests(unittest.TestCase):
    def test_last_position(self) -> None:
        fix = parse_embed_page(FIXTURE)
        self.assertEqual(fix.observed_at, datetime(2026, 11, 5, 0, 40, 50, tzinfo=timezone.utc))
        self.assertAlmostEqual(fix.latitude, 28.467711)
        self.assertAlmostEqual(fix.longitude, -16.244166)
        self.assertEqual(fix.speed_kn, 0.0)
        self.assertEqual(fix.course_deg, 180.0)
        self.assertEqual(fix.alarms, "")

    def test_invalid_heading_is_ignored(self) -> None:
        html = FIXTURE.replace('"heading":"180"', '"heading":"-2"')
        fix = parse_embed_page(html)
        self.assertIsNone(fix.course_deg)

    def test_missing_last_position(self) -> None:
        html = """
        <html><body><script>
        dataPreload = {"assets":[{"Asset":{"name":"PeskEbrel"}}]};
        l10nPreload = {};
        </script></body></html>
        """
        with self.assertRaisesRegex(Exception, "LastPosition"):
            parse_embed_page(html)

    def test_same_position_threshold(self) -> None:
        self.assertTrue(same_position(28.467711, -16.244166, 28.467679, -16.244166))
        self.assertFalse(same_position(28.467711, -16.244166, 28.46, -16.244166))


class ApplyKonectisTests(unittest.TestCase):
    def test_appends_first_konectis_after_ais_at_berth(self) -> None:
        payload = (
            "observed_at,latitude,longitude,speed_kn,course_deg,alarms,note\n"
            "2026-10-28T19:53:02Z,28.467751,-16.244101,0.6,339,,AIS MarineTraffic\n"
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "positions.csv"
            path.write_text(payload, encoding="utf-8")
            changed = apply_konectis_fix(path, parse_embed_page(FIXTURE))
            self.assertTrue(changed)
            positions = validate_path(path)
            self.assertEqual(len(positions), 2)
            self.assertEqual(positions[-1].note, NOTE)

    def test_updates_konectis_row_when_still_at_berth(self) -> None:
        payload = (
            "observed_at,latitude,longitude,speed_kn,course_deg,alarms,note\n"
            "2026-10-28T19:53:02Z,28.467751,-16.244101,0.6,339,,AIS MarineTraffic\n"
            "2026-11-05T00:40:50Z,28.467711,-16.244166,0,180,,GPS Konectis\n"
        )
        newer = parse_embed_page(
            FIXTURE.replace(
                '"received_datestamp_utc":"2026-11-05 00:40:50"',
                '"received_datestamp_utc":"2026-11-08 01:03:32"',
            )
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "positions.csv"
            path.write_text(payload, encoding="utf-8")
            changed = apply_konectis_fix(path, newer)
            self.assertTrue(changed)
            positions = validate_path(path)
            self.assertEqual(len(positions), 2)
            self.assertEqual(positions[-1].observed_at, newer.observed_at)

    def test_appends_when_boat_moved(self) -> None:
        payload = (
            "observed_at,latitude,longitude,speed_kn,course_deg,alarms,note\n"
            "2026-10-28T19:53:02Z,28.467751,-16.244101,0.6,339,,GPS Konectis\n"
        )
        moved = AisFix(
            observed_at=datetime(2026, 11, 9, 8, 0, tzinfo=timezone.utc),
            latitude=28.0,
            longitude=-16.6,
            speed_kn=5.0,
            course_deg=200,
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "positions.csv"
            path.write_text(payload, encoding="utf-8")
            changed = apply_konectis_fix(path, moved)
            self.assertTrue(changed)
            self.assertEqual(len(validate_path(path)), 2)


if __name__ == "__main__":
    unittest.main()
