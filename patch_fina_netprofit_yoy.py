"""
补丁脚本：给现有 fina_indicator.parquet 追加 netprofit_yoy 列
=================================================================
原理：
  1. 读取现有 fina_indicator.parquet，取出已有的 (ts_code, end_date) 组合
  2. 按 ts_code 分批从 Tushare 只拉 netprofit_yoy 字段
  3. 按 (ts_code, end_date) 左连接合并到原表
  4. 覆盖保存（不改变其他列，不重新拉全量）

用法：
  cd E:\\代码项目\\stock
  python patch_fina_netprofit_yoy.py
"""

import os
import sys
import time
import logging

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

# ── 日志 ──
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger("patch")

# ── 常量 ──
CACHE_DIR  = os.path.join("data", "cache")
FINA_PATH  = os.path.join(CACHE_DIR, "fina_indicator.parquet")
BATCH_SIZE = 100   # 每批100只，单次请求更大，减少总请求次数
SLEEP_SEC  = 0.6   # 批间等待（避免频控）


def init_tushare():
    import tushare as ts
    ts.set_token(config.TUSHARE_CONFIG["token"])
    pro = ts.pro_api(timeout=config.TUSHARE_CONFIG["timeout"])
    pro._DataApi__http_url = 'http://111.170.34.57:8010/'
    return pro


def main():
    # ── 1. 读现有 parquet ──
    if not os.path.exists(FINA_PATH):
        logger.error(f"文件不存在：{FINA_PATH}，请先运行 data_downloader.py")
        sys.exit(1)

    df_orig = pd.read_parquet(FINA_PATH)
    logger.info(f"现有 fina_indicator：{len(df_orig)} 行，列：{df_orig.columns.tolist()}")

    if 'netprofit_yoy' in df_orig.columns:
        non_null = df_orig['netprofit_yoy'].notna().sum()
        logger.info(f"netprofit_yoy 已存在（非空{non_null}行），无需补丁。退出。")
        sys.exit(0)

    # ── 2. 确定需要查询的股票列表 ──
    ts_codes = df_orig['ts_code'].unique().tolist()
    logger.info(f"需要补充 netprofit_yoy 的股票数：{len(ts_codes)}")

    pro = init_tushare()

    # ── 3. 分批拉取 netprofit_yoy ──
    # 拉取字段：ts_code + end_date（用于匹配） + netprofit_yoy
    # 多拉几期确保覆盖 fina_indicator 里所有 end_date
    all_dfs = []
    total_batches = (len(ts_codes) + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, len(ts_codes), BATCH_SIZE):
        batch = ts_codes[i : i + BATCH_SIZE]
        batch_no = i // BATCH_SIZE + 1
        logger.info(f"  批次 {batch_no}/{total_batches}（{len(batch)} 只）...")

        for attempt in range(3):
            try:
                df = pro.fina_indicator(
                    ts_code=",".join(batch),
                    fields='ts_code,end_date,netprofit_yoy'
                )
                if df is not None and not df.empty:
                    all_dfs.append(df)
                break
            except Exception as e:
                wait = (attempt + 1) * 5
                logger.warning(f"    第{attempt+1}次失败：{e}，{wait}秒后重试")
                time.sleep(wait)

        time.sleep(SLEEP_SEC)

    if not all_dfs:
        logger.error("所有批次均失败，退出。")
        sys.exit(1)

    df_yoy = pd.concat(all_dfs, ignore_index=True)
    # 去重：同一 (ts_code, end_date) 只保留一条
    df_yoy = df_yoy.drop_duplicates(subset=['ts_code', 'end_date'])
    logger.info(f"拉取完成：{len(df_yoy)} 行 netprofit_yoy 数据")

    # ── 4. 按 (ts_code, end_date) 左连接合并 ──
    # 确保两列类型一致（str），避免 merge key 类型不匹配
    df_orig['end_date'] = df_orig['end_date'].astype(str)
    df_yoy['end_date']  = df_yoy['end_date'].astype(str)
    df_orig['ts_code']  = df_orig['ts_code'].astype(str)
    df_yoy['ts_code']   = df_yoy['ts_code'].astype(str)

    df_merged = df_orig.merge(
        df_yoy[['ts_code', 'end_date', 'netprofit_yoy']],
        on=['ts_code', 'end_date'],
        how='left'
    )

    filled = df_merged['netprofit_yoy'].notna().sum()
    total  = len(df_merged)
    logger.info(f"合并完成：{filled}/{total} 行有 netprofit_yoy 数据（{filled/total*100:.1f}%）")

    # ── 5. 覆盖保存 ──
    df_merged.to_parquet(FINA_PATH, index=False, engine='pyarrow', compression='snappy')
    logger.info(f"✅ 已保存到 {FINA_PATH}")
    logger.info(f"   最终列：{df_merged.columns.tolist()}")


if __name__ == '__main__':
    main()
