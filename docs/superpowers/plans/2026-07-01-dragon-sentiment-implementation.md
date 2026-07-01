# Dragon Sentiment Observation Pool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a post-market dragon sentiment module that summarizes market themes, labels leader lifecycle stages, and adds explainable dragon-sentiment fields to short signal records.

**Architecture:** Extend the existing read-only dragon service first, keeping `build_dragon_observation()` as the page entrypoint and preserving old `buckets` compatibility. Then update the dragon page to consume richer output. Finally add a low-weight short-pool enrichment path that writes `dragon_*` fields into existing `factor_json` without changing SQLite schema.

**Tech Stack:** Python, pandas, FastAPI/Jinja templates, unittest, existing parquet research data under `data_research/limit_pool`.

---

## File Structure

- Modify `web_app/services/dragon_service.py`: own all theme aggregation, emotion snapshot, lifecycle tagging, and short-signal adjustment helpers.
- Modify `web_app/templates/dragon_leaders.html`: render emotion summary, theme radar, lifecycle groups, and keep legacy board fallback.
- Modify `main.py`: call the dragon helper after `select_stock_pool()` and persist the added fields through existing signal records.
- Modify `tests/test_dragon_web.py`: cover service output and page rendering.
- Add `tests/test_dragon_short_link.py`: cover short-pool enrichment without relying on live Tushare data.

---

### Task 1: Dragon Service Model

**Files:**
- Modify: `web_app/services/dragon_service.py`
- Test: `tests/test_dragon_web.py`

- [ ] **Step 1: Add failing service tests**

Add tests that build a small limit-pool parquet and assert the new structure exists:

```python
def test_dragon_service_builds_emotion_snapshot_and_theme_radar(self):
    with tempfile.TemporaryDirectory() as tmpdir:
        limit_dir = Path(tmpdir)
        frame = pd.DataFrame([
            {"trade_date": "20260630", "source": "zt_pool", "ts_code": "000001.SZ", "name": "先锋科技", "pct_chg": 10.0, "amount": 1200000, "turnover_rate": 6.0, "seal_amount": 50000, "first_limit_time": "0935", "open_count": 0, "limit_days": 1, "limit_up_reason": "机器人", "industry": "机械设备", "concept": "机器人"},
            {"trade_date": "20260630", "source": "zt_pool", "ts_code": "000002.SZ", "name": "确认股份", "pct_chg": 10.0, "amount": 900000, "turnover_rate": 12.0, "seal_amount": 30000, "first_limit_time": "1010", "open_count": 1, "limit_days": 2, "limit_up_reason": "机器人", "industry": "机械设备", "concept": "机器人"},
            {"trade_date": "20260630", "source": "strong_pool", "ts_code": "000003.SZ", "name": "补涨制造", "pct_chg": 8.2, "amount": 700000, "turnover_rate": 7.0, "seal_amount": 0, "first_limit_time": "", "open_count": 0, "limit_days": 1, "limit_up_reason": "机器人", "industry": "机械设备", "concept": "机器人"},
            {"trade_date": "20260630", "source": "zbgc_pool", "ts_code": "000004.SZ", "name": "脆弱高标", "pct_chg": 6.5, "amount": 600000, "turnover_rate": 28.0, "seal_amount": 0, "first_limit_time": "1430", "open_count": 7, "limit_days": 4, "limit_up_reason": "机器人", "industry": "机械设备", "concept": "机器人"},
        ])
        frame.to_parquet(limit_dir / "20260630.parquet", index=False)

        payload = build_dragon_observation(limit_dir=limit_dir)

    self.assertIn("emotion_snapshot", payload)
    self.assertIn(payload["emotion_snapshot"]["emotion_phase"], {"启动", "发酵", "高潮", "分歧", "修复", "退潮"})
    self.assertGreaterEqual(len(payload["themes"]), 1)
    self.assertEqual(payload["themes"][0]["theme_name"], "机器人")
    self.assertIn("lifecycle_groups", payload)
    self.assertTrue(any(item["lifecycle"] in {"首板高质量", "二板确认", "主线补涨"} for item in payload["lifecycle_groups"]["early_opportunity"]))
```

- [ ] **Step 2: Run the test and verify failure**

Run:

```bash
python -m unittest tests.test_dragon_web -q
```

Expected: fails because `emotion_snapshot`, `themes`, or `lifecycle_groups` are not present.

- [ ] **Step 3: Implement theme aggregation and lifecycle helpers**

Add focused helpers in `dragon_service.py`:

```python
def _theme_key(row: pd.Series) -> str:
    for key in ("concept", "limit_up_reason", "industry"):
        text = str(row.get(key) or "").strip()
        if text:
            return text.split("，")[0].split(",")[0].split(";")[0].split("；")[0]
    return "未分组"


def _build_theme_radar(work: pd.DataFrame) -> list[dict]:
    if work.empty:
        return []
    rows = []
    for theme_name, grp in work.groupby("theme_name"):
        limit_up = grp[grp["source"].astype(str).str.contains("zt_pool|previous_pool", na=False)]
        strong = grp[grp["source"].astype(str).str.contains("strong_pool", na=False)]
        fragile = grp[grp["late_or_fragile"]]
        board_2 = int((grp["limit_days"] == 2).sum())
        board_3_plus = int((grp["limit_days"] >= 3).sum())
        early = int(grp["early_seal"].sum())
        low_turnover = int(grp["low_turnover"].sum())
        leader_rows = grp.sort_values(["limit_days", "score", "amount"], ascending=[False, False, False]).head(3)
        heat = min(len(limit_up) * 12 + len(strong) * 5, 40)
        ladder = min(board_2 * 12 + board_3_plus * 18 + (10 if len(limit_up) >= 3 else 0), 30)
        leader = min(early * 4 + low_turnover * 5 + board_3_plus * 8, 20)
        fragility = min(len(fragile) * 8, 25)
        theme_score = max(0, min(100, heat + ladder + leader - fragility))
        rows.append({
            "theme_name": str(theme_name),
            "primary_industry": _mode_text(grp.get("industry")),
            "stock_count": int(len(grp)),
            "limit_up_count": int(len(limit_up)),
            "strong_count": int(len(strong)),
            "board_2_count": board_2,
            "board_3_plus_count": board_3_plus,
            "early_seal_count": early,
            "low_turnover_count": low_turnover,
            "fragile_count": int(len(fragile)),
            "theme_score": round(float(theme_score), 1),
            "theme_state": _theme_state(theme_score, len(limit_up), board_2, board_3_plus, len(fragile)),
            "leader_codes": [_decorate_item(row) for row in leader_rows.to_dict("records")],
            "risk_notes": _theme_risk_notes(len(fragile), board_3_plus, theme_score),
        })
    return sorted(rows, key=lambda item: item["theme_score"], reverse=True)
```

Also add `_mode_text`, `_theme_state`, `_theme_risk_notes`, `_lifecycle_label`, `_observation_action`, `_build_emotion_snapshot`, and `_build_lifecycle_groups`.

- [ ] **Step 4: Extend `build_dragon_observation()` output**

After `_score_observation_candidates(frame)`, attach:

```python
themes = _build_theme_radar(scored)
emotion = _build_emotion_snapshot(scored, themes)
lifecycle_groups = _build_lifecycle_groups(scored)
```

Return these keys while keeping existing `summary`, `buckets`, and `study`.

- [ ] **Step 5: Run service tests**

Run:

```bash
python -m unittest tests.test_dragon_web -q
```

Expected: all dragon tests pass.

---

### Task 2: Dragon Page Rendering

**Files:**
- Modify: `web_app/templates/dragon_leaders.html`
- Test: `tests/test_dragon_web.py`

- [ ] **Step 1: Add failing page rendering assertions**

Extend the existing page payload test with:

```python
payload["emotion_snapshot"] = {
    "emotion_phase": "发酵",
    "mainline_state": "强主线",
    "risk_state": "正常",
    "next_day_bias": "看核心，找低位补涨",
    "summary_text": "机器人方向形成主线，短线候选优先看同题材低位扩散。",
}
payload["themes"] = [{
    "theme_name": "机器人",
    "theme_state": "主线确认",
    "theme_score": 82.0,
    "limit_up_count": 3,
    "strong_count": 1,
    "board_2_count": 1,
    "board_3_plus_count": 0,
    "fragile_count": 0,
    "leader_codes": [{"name": "先锋科技", "ts_code": "000001.SZ", "score": 88, "lifecycle": "首板高质量", "action": "重点盯核心分歧", "badges": []}],
    "risk_notes": [],
}]
payload["lifecycle_groups"] = {
    "early_opportunity": [{"name": "先锋科技", "ts_code": "000001.SZ", "lifecycle": "首板高质量", "action": "重点盯核心分歧", "score": 88, "badges": []}],
    "emotion_anchor": [],
    "risk_sample": [],
}
self.assertIn("盘后情绪", response.text)
self.assertIn("机器人", response.text)
self.assertIn("首板高质量", response.text)
```

- [ ] **Step 2: Run page test and verify failure**

Run:

```bash
python -m unittest tests.test_dragon_web -q
```

Expected: fails because the new labels are not rendered.

- [ ] **Step 3: Update template**

Add sections above the old bucket columns:

```html
<section class="panel">
  <h2>盘后情绪</h2>
  <div class="metric-grid dragon-metrics">
    <div><span>情绪阶段</span><strong>{{ observation.emotion_snapshot.emotion_phase }}</strong></div>
    <div><span>主线状态</span><strong>{{ observation.emotion_snapshot.mainline_state }}</strong></div>
    <div><span>风险状态</span><strong>{{ observation.emotion_snapshot.risk_state }}</strong></div>
    <div><span>明日偏向</span><strong>{{ observation.emotion_snapshot.next_day_bias }}</strong></div>
  </div>
  <p>{{ observation.emotion_snapshot.summary_text }}</p>
</section>
```

Add a `主题雷达` section looping over `observation.themes`, and a `生命周期观察` section looping over `observation.lifecycle_groups`.

- [ ] **Step 4: Run page tests**

Run:

```bash
python -m unittest tests.test_dragon_web tests.test_web_app -q
```

Expected: all tests pass.

---

### Task 3: Short Pool Dragon Link

**Files:**
- Modify: `web_app/services/dragon_service.py`
- Modify: `main.py`
- Test: `tests/test_dragon_short_link.py`

- [ ] **Step 1: Add failing short-link tests**

Create `tests/test_dragon_short_link.py`:

```python
import unittest

import pandas as pd

from web_app.services.dragon_service import enrich_short_pool_with_dragon_sentiment


class DragonShortLinkTest(unittest.TestCase):
    def test_enrich_short_pool_adds_explainable_adjustment(self):
        pool = pd.DataFrame([{
            "code": "000001",
            "name": "低位制造",
            "industry": "机械设备",
            "score": 60.0,
        }])
        observation = {
            "themes": [{
                "theme_name": "机器人",
                "primary_industry": "机械设备",
                "theme_state": "主线确认",
                "theme_score": 82.0,
                "risk_notes": [],
            }]
        }

        enriched = enrich_short_pool_with_dragon_sentiment(pool, observation)

        self.assertGreater(enriched.iloc[0]["score"], 60.0)
        self.assertEqual(enriched.iloc[0]["dragon_theme_state"], "主线确认")
        self.assertIn("主线共振", enriched.iloc[0]["dragon_reason"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
python -m unittest tests.test_dragon_short_link -q
```

Expected: import or attribute failure because helper does not exist.

- [ ] **Step 3: Implement enrichment helper**

In `dragon_service.py`, add:

```python
def enrich_short_pool_with_dragon_sentiment(pool: pd.DataFrame, observation: dict | None) -> pd.DataFrame:
    if pool is None or pool.empty or not observation:
        return pool
    themes = observation.get("themes") or []
    if not themes:
        return pool
    theme_by_industry = {}
    for theme in themes:
        industry = str(theme.get("primary_industry") or "").strip()
        if industry and industry not in theme_by_industry:
            theme_by_industry[industry] = theme
    result = pool.copy()
    adjustments = []
    states = []
    reasons = []
    risks = []
    for _, row in result.iterrows():
        theme = theme_by_industry.get(str(row.get("industry") or "").strip())
        adjustment, reason, risk = _short_dragon_adjustment(theme)
        adjustments.append(adjustment)
        states.append(str(theme.get("theme_state") or "") if theme else "")
        reasons.append(reason)
        risks.append(risk)
    result["dragon_adjustment"] = adjustments
    result["dragon_theme_state"] = states
    result["dragon_reason"] = reasons
    result["dragon_risk"] = risks
    result["score"] = (pd.to_numeric(result["score"], errors="coerce").fillna(0) + result["dragon_adjustment"]).round(2)
    return result
```

Add `_short_dragon_adjustment(theme)` with bounded adjustments from `-8` to `+6`.

- [ ] **Step 4: Wire helper into `main.py`**

Import:

```python
from web_app.services.dragon_service import build_dragon_observation, enrich_short_pool_with_dragon_sentiment
```

After `select_stock_pool(...)` and before persistence/AI display:

```python
try:
    dragon_observation = build_dragon_observation(end_date=actual_date)
    stock_pool = enrich_short_pool_with_dragon_sentiment(stock_pool, dragon_observation)
except Exception as exc:
    logger.debug(f"龙头情绪联动降级：{exc}")
```

Only run this when `stock_pool` is not empty.

- [ ] **Step 5: Run focused tests**

Run:

```bash
python -m unittest tests.test_dragon_short_link tests.test_dragon_web tests.test_web_app -q
```

Expected: all pass.

---

### Task 4: Verification and Regression

**Files:**
- No new code unless tests expose a bug.

- [ ] **Step 1: Run update and web service tests**

Run:

```bash
python -m unittest tests.test_update_service tests.test_daily_web_update tests.test_dragon_web tests.test_dragon_short_link tests.test_web_app -q
```

Expected: all pass.

- [ ] **Step 2: Smoke-build a dragon observation from current data**

Run:

```bash
python -c "from web_app.services.dragon_service import build_dragon_observation; p=build_dragon_observation(); print(p['trade_date'], p['emotion_snapshot']['emotion_phase'], len(p['themes']))"
```

Expected: prints latest available date, a valid emotion phase, and a theme count.

- [ ] **Step 3: Review diff**

Run:

```bash
git diff -- web_app/services/dragon_service.py web_app/templates/dragon_leaders.html main.py tests/test_dragon_web.py tests/test_dragon_short_link.py
```

Expected: changes are limited to the dragon sentiment feature and tests.

- [ ] **Step 4: Commit implementation**

Run:

```bash
git add web_app/services/dragon_service.py web_app/templates/dragon_leaders.html main.py tests/test_dragon_web.py tests/test_dragon_short_link.py docs/superpowers/plans/2026-07-01-dragon-sentiment-implementation.md
git commit -m "feat: add dragon sentiment observation pool"
```
