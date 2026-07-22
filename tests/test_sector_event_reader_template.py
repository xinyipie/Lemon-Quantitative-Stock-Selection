import unittest
from pathlib import Path


class SectorEventReaderTemplateTest(unittest.TestCase):
    def test_reading_columns_use_all_events_by_direction(self):
        template = Path("web_app/templates/sectors.html").read_text(encoding="utf-8")

        self.assertIn('reading_positive_rows.append(event)', template)
        self.assertIn('reading_negative_rows.append(event)', template)
        self.assertIn('for event in reading_positive_rows[:8]', template)
        self.assertIn('for event in reading_negative_rows[:8]', template)
        self.assertNotIn('for event in catalyst_rows[:6]', template)
        self.assertNotIn('for event in risk_rows[:6]', template)


if __name__ == "__main__":
    unittest.main()
