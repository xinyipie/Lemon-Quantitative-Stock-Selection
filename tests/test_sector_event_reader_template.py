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

    def test_reader_css_uses_equal_height_independent_scrollers(self):
        css = Path("web_app/static/app.css").read_text(encoding="utf-8")

        self.assertIn("MARKET RADAR SPLIT SCROLLER 20260722", css)
        self.assertIn("height: min(680px, calc(100vh - 150px));", css)
        self.assertIn("overflow-y: auto;", css)
        self.assertIn("overscroll-behavior: contain;", css)


if __name__ == "__main__":
    unittest.main()
