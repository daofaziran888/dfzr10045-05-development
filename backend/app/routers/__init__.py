"""业务路由汇总：整组报送等专用路由先注册，通用模块资源路由兜底。"""
from __future__ import annotations

from app.routers import freshness_batch, resource

ROUTERS = [freshness_batch, resource]
