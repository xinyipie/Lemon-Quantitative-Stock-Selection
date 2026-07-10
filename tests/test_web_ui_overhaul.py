#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全站前端重构的共享契约测试。"""

import unittest

from web_app.services.ui_service import (
    display_source_label,
    normalize_date_input,
    paginate_items,
)


class WebUiOverhaulTest(unittest.TestCase):
    def test_paginate_items_clamps_invalid_and_overflow_pages(self):
        items = [{"id": index} for index in range(105)]

        page_items, info = paginate_items(items, page=99, page_size=50)

        self.assertEqual([item["id"] for item in page_items], list(range(100, 105)))
        self.assertEqual(
            info,
            {
                "page": 3,
                "page_size": 50,
                "total": 105,
                "total_pages": 3,
                "start_index": 101,
                "end_index": 105,
            },
        )

    def test_paginate_items_normalizes_non_numeric_page(self):
        page_items, info = paginate_items([{"id": 1}], page="bad", page_size=50)

        self.assertEqual(page_items, [{"id": 1}])
        self.assertEqual(info["page"], 1)

    def test_ui_labels_and_date_normalization_are_user_facing(self):
        self.assertEqual(normalize_date_input("2026-07-09"), "20260709")
        self.assertEqual(normalize_date_input("20260709"), "20260709")
        self.assertEqual(display_source_label("fallback"), "规则解释")
        self.assertEqual(display_source_label("short_v9_final"), "v9 底层评分")


if __name__ == "__main__":
    unittest.main()
