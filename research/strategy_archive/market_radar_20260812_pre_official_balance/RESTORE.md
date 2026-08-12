# 恢复说明

## 推荐恢复方式

仅当需要完整回到 2026-08-12 18:13:36 之前的市场雷达行为时，恢复 `code/` 中对应文件。

恢复顺序：

1. 备份线上当前 7 个文件。
2. 上传本快照 `code/` 中的文件到服务器临时目录。
3. 使用线上虚拟环境执行 `python -m py_compile`。
4. 替换 `/opt/stock/` 下对应文件。
5. 重启 `stock-web`，确认服务为 `active`。
6. 重新执行 `daily_web_update.py --mode radar` 生成市场雷达缓存。

不要只恢复新闻抓取文件而保留新版时效和证据包，否则会形成混合版本。至少应成组恢复：

- `news_source_provider.py`
- `market_context_snapshot.py`
- `market_radar/freshness.py`
- `market_radar/evidence_pack.py`
- `web_app/services/sector_service.py`

`official_information_provider.py` 在上一版中已存在，但官方来源适配尚未采用后续的完整规则。

