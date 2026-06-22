import json
import tempfile
import unittest
from pathlib import Path

from research.official_strategy_health_check import (
    build_official_strategy_health_check,
    write_official_strategy_health_check_report,
)


class OfficialStrategyHealthCheckTest(unittest.TestCase):
    def _write_json(self, root: Path, name: str, payload: dict) -> None:
        target = root / "reports" / "research" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_build_health_check_keeps_short_live_and_routes_longterm_to_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_json(
                root,
                "dragon_boat_layer_quality.json",
                {
                    "short": {
                        "layers": {
                            "top3": {"classification": "quality_edge", "avg_edge_vs_all": 0.16},
                            "all": {"classification": "benchmark"},
                        }
                    },
                    "longterm": {
                        "layers": {
                            "top3": {"classification": "negative_edge", "avg_edge_vs_all": -1.2},
                            "top10": {"classification": "mixed", "avg_edge_vs_all": 0.05},
                        }
                    },
                },
            )
            self._write_json(
                root,
                "dragon_boat_candidate_simulation.json",
                {
                    "short": {
                        "candidates": {
                            "short_v9_quality_floor_top3": {
                                "classification": "mixed",
                                "overall": {"edge_vs_baseline": 0.1},
                            }
                        }
                    },
                    "longterm": {
                        "candidates": {
                            "long_v18_quality_floor_top10": {
                                "classification": "promising_for_validation",
                                "overall": {"edge_vs_baseline": 2.7},
                            }
                        }
                    },
                },
            )

            result = build_official_strategy_health_check(root=root)

            self.assertEqual(result["short"]["action"], "keep_live_baseline")
            self.assertEqual(result["longterm"]["action"], "validate_research_candidate")
            self.assertIn("long_v18_quality_floor_top10", result["longterm"]["candidate"])
            self.assertFalse(result["live_defaults_changed"])

    def test_write_health_check_report_outputs_markdown_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_json(root, "dragon_boat_layer_quality.json", {"short": {}, "longterm": {}})
            self._write_json(root, "dragon_boat_candidate_simulation.json", {"short": {}, "longterm": {}})
            output = root / "reports" / "research" / "health.md"

            write_official_strategy_health_check_report(root=root, output=output)

            self.assertTrue(output.exists())
            self.assertTrue(output.with_suffix(".json").exists())
            self.assertIn("定板策略健康检查", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
