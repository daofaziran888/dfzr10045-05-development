"""来源批整组报送领域服务：一次上报多个来源批，把观测读数与迟到更正写入各自业务期。

业务规则：
- 每个来源批带报送批次键（来源+业务期+件别），按报送回执幂等受理，持同一回执重试不重复入账；
- 原件与补送件若带同一更正序号，合起来仍是一笔窗口读数；新的更正序号才产生新版本读数；
- 迟到读数归回原观测期，先到的读数继续留在先到的业务期，业务期以来源批自报为准；
- 补报时若窗口读数已接受更新（更大）的更正序号，旧序号的新值不覆盖现行读数，
  现行值继续供服务等级目标结算使用；
- 组内可注入部分失败，失败的来源批不产生窗口读数，重试时仅补受理尚未确认的来源批；
- 等级目标按窗口读数数据集重算结算样本，并回传尚未确认的来源批。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.freshness_track import FreshnessTrackService
from app.services.sla_target import SlaTargetService
from app.store import store

BATCH_MODULE = "source_batch"
READING_MODULE = "window_reading"
RECEIPT_MODULE = "freshness_receipt"


class FreshnessBatchService:
    """来源批整组报送与窗口读数合并、SLO 重算结算的领域服务。"""

    def __init__(self) -> None:
        self.freshness = FreshnessTrackService()
        self.sla = SlaTargetService()

    # ------------------------------------------------------------------
    # 组报送
    # ------------------------------------------------------------------
    def submit_batches(
        self,
        receipt_no: str,
        batches: list[dict[str, Any]],
        fail_keys: list[str] | None = None,
    ) -> dict[str, Any]:
        """按报送回执整组受理来源批，返回逐批受理结果与回执汇总。

        同一 receipt_no 重放为幂等重试：已受理的来源批直接复用既有结果，
        仅处理此前失败或未出现的来源批；fail_keys 只在首次受理时生效。
        """
        fail_keys = list(fail_keys or [])
        receipt = self._find_receipt(receipt_no)
        is_retry = receipt is not None
        active_fail_keys = [] if is_retry else fail_keys

        batch_results: list[dict[str, Any]] = []
        accepted_keys: list[str] = []
        failed: list[dict[str, str]] = []
        stale: list[dict[str, Any]] = []
        merged_readings: list[dict[str, Any]] = []

        for payload in batches:
            key = self.batch_key(payload)
            prior = self._find_batch(receipt_no, key)
            # 重试时已确认的来源批不再重复处理；此前失败的批次重新受理。
            if is_retry and prior is not None and prior.get("status") in (
                "accepted", "stale", "duplicate"
            ):
                batch_results.append({
                    "batch_key": key,
                    "status": "duplicate",
                    "message": "来源批已在本回执确认，幂等跳过",
                    "batch": prior,
                })
                accepted_keys.append(key)
                continue

            if key in active_fail_keys:
                failure = {
                    "batch_key": key,
                    "status": "failed",
                    "message": "来源批受理失败：部分失败，待持回执重试",
                }
                batch_results.append(failure)
                failed.append({"batch_key": key, "message": failure["message"]})
                self._upsert_batch({
                    "receipt_no": receipt_no,
                    "batch_key": key,
                    "status": "failed",
                    "来源批": str(payload.get("来源批", "")),
                    "所属契约": str(payload.get("所属契约", "")),
                    "业务期": str(payload.get("业务期", "")),
                    "件别": str(payload.get("件别", "原件")),
                    "更正序号": int(payload.get("更正序号", 0) or 0),
                    "承诺延迟": int(payload.get("承诺延迟", 0) or 0),
                    "实际延迟": int(payload.get("实际延迟", 0) or 0),
                    "数据水位": str(payload.get("数据水位", "")),
                    "到达性质": str(payload.get("到达性质", "") or ""),
                })
                continue

            batch, reading, superseded = self._accept_batch(receipt_no, key, payload)
            batch_results.append({
                "batch_key": key,
                "status": "stale" if superseded else "accepted",
                "message": (
                    "窗口读数已接受更新序号，旧序号新值不覆盖，现行值继续供结算"
                    if superseded else "来源批已确认并写入业务期窗口读数"
                ),
                "batch": batch,
                "window_reading": reading,
            })
            accepted_keys.append(key)
            if superseded:
                stale.append({
                    "batch_key": key,
                    "window_key": self.window_key(payload),
                    "accepted_seq": reading.get("更正序号"),
                    "incoming_seq": batch.get("更正序号"),
                })
            if reading and not any(r.get("读数编号") == reading.get("读数编号") for r in merged_readings):
                merged_readings.append(reading)

        summary = self._persist_receipt(
            receipt_no=receipt_no,
            is_retry=is_retry,
            accepted_keys=accepted_keys,
            failed=failed,
        )
        return {
            "receipt_no": receipt_no,
            "attempt": "retry" if is_retry else "first",
            "batch_count": len(batches),
            "accepted_count": len(accepted_keys),
            "failed_count": len(failed),
            "stale_count": len(stale),
            "accepted_keys": accepted_keys,
            "failed": failed,
            "stale": stale,
            "batch_results": batch_results,
            "window_readings": merged_readings,
            "receipt": summary,
        }

    # ------------------------------------------------------------------
    # 回执查询与窗口读数
    # ------------------------------------------------------------------
    def get_receipt(self, receipt_no: str) -> dict[str, Any] | None:
        """查询报送回执的受理进度，含已确认与未确认来源批清单。"""
        receipt = self._find_receipt(receipt_no)
        if receipt is None:
            return None
        batches = [b for b in store.rows(BATCH_MODULE) if b.get("receipt_no") == receipt_no]
        confirmed = [b["batch_key"] for b in batches if b.get("status") in ("accepted", "stale", "duplicate")]
        unconfirmed = [
            {"batch_key": b["batch_key"], "status": b.get("status"), "message": "来源批尚未确认，需重试"}
            for b in batches if b.get("status") == "failed"
        ]
        return {
            "receipt_no": receipt_no,
            "confirmed_keys": confirmed,
            "unconfirmed": unconfirmed,
            "confirmed_count": len(confirmed),
            "unconfirmed_count": len(unconfirmed),
            "batch_records": batches,
        }

    def list_window_readings(self, contract_id: str | None = None) -> list[dict[str, Any]]:
        """查询窗口读数数据集，可按契约过滤。"""
        rows = store.rows(READING_MODULE)
        if contract_id:
            return [r for r in rows if r.get("所属契约") == contract_id]
        return list(rows)

    def list_source_batches(self, receipt_no: str | None = None) -> list[dict[str, Any]]:
        """查询来源批受理记录，可按报送回执过滤。"""
        rows = store.rows(BATCH_MODULE)
        if receipt_no:
            return [r for r in rows if r.get("receipt_no") == receipt_no]
        return list(rows)

    # ------------------------------------------------------------------
    # SLO 按窗口读数重算结算
    # ------------------------------------------------------------------
    def settle_sla(self, contract_id: str, periods: list[str] | None = None) -> dict[str, Any]:
        """用契约关联的观测批次（窗口读数）重算两个等级目标的结算样本。

        样本取契约名下各业务期现行窗口读数；迟到读数已归原观测期，
        先到读数仍留在先到业务期。同时回传尚未确认的来源批。
        """
        readings = self.list_window_readings(contract_id)
        if periods:
            wanted = set(periods)
            readings = [r for r in readings if r.get("业务期") in wanted]

        samples = [self._to_sample(reading) for reading in readings]
        targets = self.sla.get_targets_for_contract(contract_id)
        settlements: list[dict[str, Any]] = []
        for target in targets:
            target_id = int(target.get("id", 0))
            result = self.sla.settle(target_id, samples)
            settlements.append({
                "target_id": target.get("目标编号"),
                "target_type": target.get("目标类型"),
                "threshold": result.get("threshold"),
                "achievement": result.get("achievement"),
                "breached": result.get("breached"),
                "sample_size": len(samples),
                "samples": samples,
            })

        unconfirmed = self._unconfirmed_batches_for_contract(contract_id)
        return {
            "contract_id": contract_id,
            "periods": sorted({r.get("业务期") for r in readings}),
            "settlements": settlements,
            "samples_used": samples,
            "unconfirmed_batches": unconfirmed,
            "unconfirmed_count": len(unconfirmed),
        }

    # ------------------------------------------------------------------
    # 内部：受理与合并
    # ------------------------------------------------------------------
    def _upsert_batch(self, values: dict[str, Any]) -> dict[str, Any]:
        """按回执+来源批键写入或更新受理记录，重试不产生重复行。"""
        rows = store.rows(BATCH_MODULE)
        existing = next(
            (
                b for b in rows
                if b.get("receipt_no") == values["receipt_no"]
                and b.get("batch_key") == values["batch_key"]
            ),
            None,
        )
        if existing is not None:
            existing.update(values)
            return existing
        record = {
            "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
            "来源批键": values["batch_key"],
            "receipt_no": values["receipt_no"],
            "batch_key": values["batch_key"],
            "来源批": values.get("来源批", ""),
            "所属契约": values.get("所属契约", ""),
            "业务期": values.get("业务期", ""),
            "件别": values.get("件别", "原件"),
            "更正序号": values.get("更正序号", 0),
            "承诺延迟": values.get("承诺延迟", 0),
            "实际延迟": values.get("实际延迟", 0),
            "数据水位": values.get("数据水位", ""),
            "到达性质": values.get("到达性质", ""),
            "受理时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pending": values.get("status") == "failed",
            "abnormal": values.get("status") == "failed",
        }
        record.update(values)
        rows.append(record)
        return record

    def _accept_batch(
        self,
        receipt_no: str,
        key: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], bool]:
        rows = store.rows(BATCH_MODULE)
        prior = self._find_batch(receipt_no, key)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        correction_seq = int(payload.get("更正序号", 0) or 0)
        period = str(payload.get("业务期", ""))
        arrival = str(payload.get("到达性质", "") or self._infer_arrival(period, now))

        batch = prior or {"id": max((int(r.get("id", 0)) for r in rows), default=0) + 1}
        batch.update({
            "来源批键": key,
            "receipt_no": receipt_no,
            "batch_key": key,
            "来源批": str(payload.get("来源批", "")),
            "所属契约": str(payload.get("所属契约", "")),
            "业务期": period,
            "件别": str(payload.get("件别", "原件")),
            "更正序号": correction_seq,
            "承诺延迟": int(payload.get("承诺延迟", 0) or 0),
            "实际延迟": int(payload.get("实际延迟", 0) or 0),
            "数据水位": str(payload.get("数据水位", "")),
            "到达性质": arrival,
            "受理时间": now,
            "status": "accepted",
            "pending": False,
            "abnormal": False,
        })
        if prior is None:
            rows.append(batch)

        reading, superseded = self._merge_window_reading(batch)
        if superseded:
            batch["status"] = "stale"
        return batch, reading, superseded

    def _merge_window_reading(self, batch: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """把来源批合并进对应业务期的窗口读数，返回(现行读数, 是否被更新序号压制)。"""
        rows = store.rows(READING_MODULE)
        window_key = self._window_key_of(batch)
        existing = next((r for r in rows if r.get("窗口键") == window_key), None)
        incoming_seq = int(batch.get("更正序号", 0) or 0)

        if existing is not None and int(existing.get("更正序号", 0) or 0) > incoming_seq:
            # 窗口读数已接受更新序号：旧序号补报不覆盖，现行值继续供结算。
            existing.setdefault("合并来源批", []).append(batch["batch_key"])
            existing["迟到件数"] = int(existing.get("迟到件数", 0)) + (
                1 if batch.get("到达性质") == "迟到" else 0
            )
            return existing, True

        if existing is None:
            reading_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
            promised = int(batch.get("承诺延迟", 0) or 0)
            actual = int(batch.get("实际延迟", 0) or 0)
            status = self.freshness.classify_lag(promised, actual)
            reading = {
                "id": reading_id,
                "读数编号": f"WIN-{reading_id:04d}",
                "窗口键": window_key,
                "所属契约": batch.get("所属契约", ""),
                "业务期": batch.get("业务期", ""),
                "来源标识": batch.get("来源批", ""),
                "承诺延迟": promised,
                "实际延迟": actual,
                "数据水位": batch.get("数据水位", ""),
                "更正序号": incoming_seq,
                "到达性质": batch.get("到达性质", ""),
                "合并来源批": [batch["batch_key"]],
                "迟到件数": 1 if batch.get("到达性质") == "迟到" else 0,
                "最近回执": batch.get("receipt_no", ""),
                "更新时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": status,
                "pending": status != "达标",
                "abnormal": status != "达标",
            }
            rows.append(reading)
        else:
            reading = existing
            reading["更正序号"] = incoming_seq
            reading["承诺延迟"] = int(batch.get("承诺延迟", 0) or 0)
            reading["实际延迟"] = int(batch.get("实际延迟", 0) or 0)
            reading["数据水位"] = batch.get("数据水位", "") or reading.get("数据水位", "")
            reading["合并来源批"] = list(reading.get("合并来源批", [])) + [batch["batch_key"]]
            reading["迟到件数"] = int(reading.get("迟到件数", 0)) + (
                1 if batch.get("到达性质") == "迟到" else 0
            )
            reading["最近回执"] = batch.get("receipt_no", "")
            reading["更新时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            status = self.freshness.classify_lag(reading["承诺延迟"], reading["实际延迟"])
            reading["status"] = status
            reading["pending"] = status != "达标"
            reading["abnormal"] = status != "达标"

        # 与既有新鲜度链路保持一致的副作用：滞后缩短结果集快照有效期。
        if reading["status"] != "达标":
            from app.services.result_set import ResultSetService
            ResultSetService().shorten_validity(
                str(reading["所属契约"]), int(reading["实际延迟"])
            )
        return reading, False

    def _to_sample(self, reading: dict[str, Any]) -> dict[str, Any]:
        actual = int(reading.get("实际延迟", 0) or 0)
        promised = int(reading.get("承诺延迟", 0) or 0)
        lagging = actual > promised
        return {
            "reading_id": reading.get("读数编号"),
            "window_key": reading.get("窗口键"),
            "period": reading.get("业务期"),
            "source": reading.get("来源标识"),
            "correction_seq": reading.get("更正序号"),
            "arrival": reading.get("到达性质"),
            "promised_minutes": promised,
            "actual_minutes": actual,
            "lagging": lagging,
            "success": reading.get("status") != "追踪中断",
            "status": reading.get("status"),
        }

    def _unconfirmed_batches_for_contract(self, contract_id: str) -> list[dict[str, Any]]:
        return [
            {
                "batch_key": b.get("batch_key"),
                "receipt_no": b.get("receipt_no"),
                "status": b.get("status"),
                "message": "来源批尚未确认，需持回执重试",
            }
            for b in store.rows(BATCH_MODULE)
            if b.get("所属契约") == contract_id and b.get("status") == "failed"
        ]

    def _persist_receipt(
        self,
        receipt_no: str,
        is_retry: bool,
        accepted_keys: list[str],
        failed: list[dict[str, str]],
    ) -> dict[str, Any]:
        rows = store.rows(RECEIPT_MODULE)
        receipt = next((r for r in rows if r.get("回执编号") == receipt_no), None)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if receipt is None:
            receipt = {
                "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
                "回执编号": receipt_no,
                "首次报送": now,
                "最近报送": now,
                "尝试次数": 1,
                "已确认键": [],
                "失败键": [],
                "status": "部分受理",
                "pending": True,
                "abnormal": bool(failed),
            }
            rows.append(receipt)
        else:
            receipt["最近报送"] = now
            receipt["尝试次数"] = int(receipt.get("尝试次数", 1)) + 1

        confirmed = set(receipt.get("已确认键", [])) | set(accepted_keys)
        receipt["已确认键"] = sorted(confirmed)
        receipt["失败键"] = [f["batch_key"] for f in failed]
        receipt["pending"] = bool(failed)
        receipt["abnormal"] = bool(failed)
        receipt["status"] = "全部确认" if not failed else "部分受理"
        return dict(receipt)

    def _find_receipt(self, receipt_no: str) -> dict[str, Any] | None:
        return next(
            (r for r in store.rows(RECEIPT_MODULE) if r.get("回执编号") == receipt_no),
            None,
        )

    def _find_batch(self, receipt_no: str, key: str) -> dict[str, Any] | None:
        return next(
            (
                b for b in store.rows(BATCH_MODULE)
                if b.get("receipt_no") == receipt_no and b.get("batch_key") == key
            ),
            None,
        )

    @staticmethod
    def batch_key(payload: dict[str, Any]) -> str:
        return "|".join([
            str(payload.get("所属契约", "")),
            str(payload.get("业务期", "")),
            str(payload.get("来源批", "")),
            str(payload.get("件别", "原件")),
            str(int(payload.get("更正序号", 0) or 0)),
        ])

    @staticmethod
    def window_key(payload: dict[str, Any]) -> str:
        return "|".join([
            str(payload.get("所属契约", "")),
            str(payload.get("业务期", "")),
            str(payload.get("来源批", "")),
        ])

    @staticmethod
    def _window_key_of(batch: dict[str, Any]) -> str:
        return "|".join([
            str(batch.get("所属契约", "")),
            str(batch.get("业务期", "")),
            str(batch.get("来源批", "")),
        ])

    @staticmethod
    def _infer_arrival(period: str, now: str) -> str:
        """未显式声明到达性质时，业务期早于当前周窗视为迟到，否则先到。"""
        current_week = datetime.now().strftime("W%V")
        if period.startswith("W") and period < current_week:
            return "迟到"
        return "先到"


def submit_source_batches(
    receipt_no: str,
    batches: list[dict[str, Any]],
    fail_keys: list[str] | None = None,
) -> dict[str, Any]:
    """模块级入口：整组报送来源批并返回回执受理结果数据集。"""
    return FreshnessBatchService().submit_batches(receipt_no, batches, fail_keys)
