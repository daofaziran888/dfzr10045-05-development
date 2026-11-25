"""通用接口契约；模块字段由领域服务持有，不再为每个模块复制一份模型类。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    size: int = 20


class ActionResult(BaseModel):
    ok: bool
    message: str
    entry: dict[str, Any] | None = None


class EntryPayload(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    remark: str | None = None


class ActionPayload(BaseModel):
    action: str
    remark: str | None = None


class FreshnessBatchItem(BaseModel):
    """单个来源批：业务期以来源批自报为准，迟到件归原观测期。"""

    来源批: str
    所属契约: str
    业务期: str
    件别: str = "原件"
    更正序号: int = 0
    承诺延迟: int = 0
    实际延迟: int = 0
    数据水位: str = ""
    到达性质: str | None = None


class FreshnessBatchPayload(BaseModel):
    """整组报送：一个报送回执携带多个来源批，fail_keys 注入部分失败。"""

    receipt_no: str
    batches: list[FreshnessBatchItem] = Field(default_factory=list)
    fail_keys: list[str] = Field(default_factory=list)


class SettleSlaPayload(BaseModel):
    """按关联观测批次重算等级目标结算样本，可限定业务期。"""

    periods: list[str] = Field(default_factory=list)
