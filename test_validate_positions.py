from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from validate_positions import (
    ValidationError,
    parse_coordinate,
    parse_observed_at,
    parse_optional_float,
    validate_path,
)

HEADER = "observed_at,latitude,longitude,speed_kn,course_deg,alarms,note\n"


class ParseCoordinateTests(unittest.TestCase):
    def test_decimal_latitude(self) -> None:
        self.assertAlmostEqual(parse_coordinate("36.278625", "latitude"), 36.278625)

    def test_dms_from_satellite_popup(self) -> None:
        lat = parse_coordinate("36°16'43.05 N", "latitude")
        lon = parse_coordinate("17°35'49.68 W", "longitude")
        self.assertAlmostEqual(lat, 36.278625, places=6)
        self.assertAlmostEqual(lon, -17.597133, places=6)

    def test_dms_with_seconds_quote(self) -> None:
        self.assertAlmostEqual(
            parse_coordinate("""36°16'43.05" N""", "latitude"),
            36.278625,
            places=6,
        )

    def test_leading_hemisphere(self) -> None:
        self.assertAlmostEqual(parse_coordinate("S 36 16 43.05", "latitude"), -36.278625, places=6)

    def test_signed_longitude(self) -> None:
        self.assertAlmostEqual(parse_coordinate("-17.597133", "longitude"), -17.597133)

    def test_rejects_wrong_hemisphere(self) -> None:
        with self.assertRaises(ValidationError):
            parse_coordinate("36°16'43.05 W", "latitude")

    def test_rejects_out_of_range(self) -> None:
        with self.assertRaises(ValidationError):
            parse_coordinate("91", "latitude")


class ParseTimestampTests(unittest.TestCase):
    def test_iso_z(self) -> None:
        value = parse_observed_at("2026-09-17T09:31:44Z")
        self.assertEqual(value, datetime(2026, 9, 17, 9, 31, 44, tzinfo=timezone.utc))

    def test_space_separated_utc(self) -> None:
        value = parse_observed_at("2026-09-17 09:31:44 UTC")
        self.assertEqual(value, datetime(2026, 9, 17, 9, 31, 44, tzinfo=timezone.utc))


class ParseOptionalFloatTests(unittest.TestCase):
    def test_speed_with_unit(self) -> None:
        self.assertEqual(parse_optional_float("6,48 NM", "speed_kn", 0, 80), 6.48)

    def test_course_with_degree(self) -> None:
        self.assertEqual(parse_optional_float("174°", "course_deg", 0, 360), 174.0)

    def test_empty(self) -> None:
        self.assertIsNone(parse_optional_float("", "speed_kn", 0, 80))


class CsvTests(unittest.TestCase):
    def test_repo_csv_is_valid(self) -> None:
        positions = validate_path(Path("docs/positions.csv"))
        self.assertGreaterEqual(len(positions), 1)
        latest = positions[-1]
        self.assertAlmostEqual(latest.latitude, 32.679115, places=5)
        self.assertAlmostEqual(latest.longitude, -16.677433, places=5)

    def test_duplicate_timestamp_is_rejected(self) -> None:
        payload = HEADER + (
            "2026-09-17T09:31:44Z,36.2,-17.5,6.4,174,,\n"
            "2026-09-17 09:31:44 UTC,36.3,-17.6,5.1,180,,\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as handle:
            handle.write(payload)
            path = Path(handle.name)
        try:
            with self.assertRaises(ValidationError):
                validate_path(path)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
