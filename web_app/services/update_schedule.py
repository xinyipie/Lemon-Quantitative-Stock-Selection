"""展示已核验的服务器调度配置，不把计划执行时间当成任务成功。"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


def read_update_schedule(path, now=None):
    try:
        config = json.loads(Path(path).read_text(encoding='utf-8'))
        if not config.get('verified_at'):
            return []
        zone = ZoneInfo(config['timezone'])
        current = now or datetime.now(zone)
        current = current.replace(tzinfo=zone) if current.tzinfo is None else current.astimezone(zone)
        result = []
        for entry in config['entries']:
            next_run = None
            for offset in range(8):
                day = current + timedelta(days=offset)
                if day.weekday() not in entry['weekdays']:
                    continue
                candidate = day.replace(hour=entry['hour'], minute=entry['minute'], second=0, microsecond=0)
                if candidate > current:
                    next_run = candidate
                    break
            result.append({**entry, 'next_run': next_run.strftime('%Y-%m-%d %H:%M') if next_run else '',
                           'timezone': config['timezone'], 'verified_at': config['verified_at']})
        return sorted(result, key=lambda row: row['next_run'])
    except (OSError, ValueError, KeyError, TypeError):
        return []
