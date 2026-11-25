"""新鲜度来源批整组报送路由：组报送、回执重试查询、窗口读数与 SLO 重算结算。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import FreshnessBatchPayload, SettleSlaPayload
from app.services.freshness_batch import (
    BATCH_MODULE,
    READING_MODULE,
    FreshnessBatchService,
)
from app.store import store

router = APIRouter(prefix="/api/freshness", tags=["新鲜度整组报送"])


def _service() -> FreshnessBatchService:
    return FreshnessBatchService()


@router.post("/batch-submissions")
def submit_batches(payload: FreshnessBatchPayload) -> dict:
    """一次上报多个来源批：观测读数与迟到更正批量写入各自业务期。"""
    if not payload.batches:
        raise HTTPException(status_code=422, detail="报送来源批不能为空")
    batches = [item.model_dump() for item in payload.batches]
    return _service().submit_batches(payload.receipt_no, batches, payload.fail_keys)


@router.get("/batch-submissions/{receipt_no}")
def get_receipt(receipt_no: str) -> dict:
    """持报送回执查看已确认与尚未确认的来源批。"""
    result = _service().get_receipt(receipt_no)
    if result is None:
        raise HTTPException(status_code=404, detail=f"报送回执 {receipt_no} 不存在")
    return result


@router.get("/window-readings")
def list_window_readings(contract_id: str | None = None) -> dict:
    """查询窗口读数数据集：原件与补送件按更正序号合并后的现行读数。"""
    items = _service().list_window_readings(contract_id)
    return {"items": items, "total": len(items)}


@router.get("/source-batches")
def list_source_batches(receipt_no: str | None = None) -> dict:
    """查询来源批受理记录，可按报送回执过滤。"""
    items = _service().list_source_batches(receipt_no)
    return {"items": items, "total": len(items)}


@router.post("/contracts/{contract_id}/settle-sla")
def settle_sla(contract_id: str, payload: SettleSlaPayload) -> dict:
    """用关联观测批次重算契约名下等级目标的结算样本。"""
    return _service().settle_sla(contract_id, payload.periods or None)


@router.get("/tables/overview")
def freshness_tables_overview() -> dict:
    """整组报送相关内存表水位，供排查与页面展示。"""
    return {
        "source_batches": len(store.rows(BATCH_MODULE)),
        "window_readings": len(store.rows(READING_MODULE)),
        "receipts": len(store.rows("freshness_receipt")),
    }
