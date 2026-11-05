from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fetch_ais import append_fix
from fetch_konectis import parse_embed_page, NOTE
from fetch_ais import AisFix
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


class AppendKonectisTests(unittest.TestCase):
    def test_appends_newer_konectis_fix(self) -> None:
        payload = (
            "observed_at,latitude,longitude,speed_kn,course_deg,alarms,note\n"
            "2026-10-28T19:53:02Z,28.467751,-16.244101,0.6,339,,AIS MarineTraffic\n"
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "positions.csv"
            path.write_text(payload, encoding="utf-8")
            added = append_fix(
                path,
                parse_embed_page(FIXTURE),
                note=NOTE,
            )
            self.assertTrue(added)
            latest = validate_path(path)[-1]
            self.assertEqual(latest.note, NOTE)


if __name__ == "__main__":
    unittest.main()
