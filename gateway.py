"""兼容现有 systemd 的 gateway:app 启动入口。"""

from deploy.gateway import app

__all__ = ["app"]
