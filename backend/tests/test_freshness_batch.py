"""来源批整组报送测试：组报送→部分失败→回执重试→窗口读数合并→SLO 重算结算。

覆盖题面规则：
- 一次上报 W1:A、W1:B、W2:A 多个来源批，W1:B 前出现部分失败；
- W1:B 原件与补送件带同一更正序号，合起来仍是一笔窗口读数；
- W1 的迟到读数归原观测期 W1，W2 先到读数继续留在 W2；
- 补报时窗口读数已接受更新序号，旧序号新值不覆盖、现行值继续供结算；
- W2:A 迟到更正把延迟由 40 分钟订正成 5 分钟；
- 持回执重试后查看两个等级目标实际采用样本及尚未确认的来源批。
"""
from __future__ import annotations

from app.services.freshness_batch import (
    BATCH_MODULE,
    READING_MODULE,
    RECEIPT_MODULE,
    FreshnessBatchService,
)
from app.store import store

CONTRACT = "CTR-BATCH"


def _seed_contract_targets() -> None:
    """构造带两个等级目标的契约：可用率类与新鲜度延迟类各一个。"""
    sla_rows = store.rows("sla_target")
    sla_rows.append({
        "id": 101, "目标编号": "SLA-BATCH-AVAIL", "所属契约": CONTRACT,
        "目标类型": "查询可用率", "目标阈值": "99",
        "统计窗口": "周度", "当前达成率": "", "违约处置": "通知消费方",
        "最近结算": "", "status": "已设定", "pending": True, "abnormal": False,
    })
    sla_rows.append({
        "id": 102, "目标编号": "SLA-BATCH-FRESH", "所属契约": CONTRACT,
        # 目标阈值沿用 SlaTargetService 的百分比达成率口径：达标率不得低于 70%。
        "目标类型": "新鲜度延迟", "目标阈值": "70",
        "统计窗口": "周度", "当前达成率": "", "违约处置": "自动切换备用源",
        "最近结算": "", "status": "已设定", "pending": True, "abnormal": False,
    })


def _batch(source: str, period: str, actual: int, *, promised: int = 30,
           piece: str = "原件", seq: int = 0, arrival: str | None = None,
           water: str = "") -> dict:
    payload = {
        "来源批": source,
        "所属契约": CONTRACT,
        "业务期": period,
        "件别": piece,
        "更正序号": seq,
        "承诺延迟": promised,
        "实际延迟": actual,
        "数据水位": water or f"{period}T00:00:00",
    }
    if arrival:
        payload["到达性质"] = arrival
    return payload


def _reading_by_window(period: str, source: str) -> dict | None:
    window_key = f"{CONTRACT}|{period}|{source}"
    return next(
        (r for r in store.rows(READING_MODULE) if r.get("窗口键") == window_key),
        None,
    )


class TestBatchSubmissionLifecycle:
    """整组报送、部分失败与回执重试主链路。"""

    def test_full_scenario_partial_failure_retry_and_settlement(self):
        _seed_contract_targets()
        service = FreshnessBatchService()

        # W2 先到的读数先入库（先到件，业务期 W2）。
        first = service.submit_batches("RCP-0", [
            _batch("W2:A", "W2", 40, arrival="先到"),
        ])
        assert first["failed_count"] == 0
        w2 = _reading_by_window("W2", "W2:A")
        assert w2 is not None
        assert w2["业务期"] == "W2"
        assert w2["实际延迟"] == 40
        assert w2["到达性质"] == "先到"

        # 同时报 W1:A、W1:B、W2:A，收件在 W1:B 前出现部分失败。
        w1b_key = FreshnessBatchService.batch_key(
            _batch("W1:B", "W1", 45, arrival="迟到")
        )
        first_group = service.submit_batches(
            "RCP-1",
            [
                _batch("W1:A", "W1", 10, arrival="迟到"),
                _batch("W1:B", "W1", 45, arrival="迟到"),
                _batch("W2:A", "W2", 5, arrival="迟到", seq=1),
            ],
            fail_keys=[w1b_key],
        )

        # W1:B 失败，其余两批确认。
        assert first_group["accepted_count"] == 2
        assert first_group["failed_count"] == 1
        assert first_group["failed"][0]["batch_key"] == w1b_key
        assert {*first_group["accepted_keys"]} == {
            FreshnessBatchService.batch_key(_batch("W1:A", "W1", 10, arrival="迟到")),
            FreshnessBatchService.batch_key(_batch("W2:A", "W2", 5, arrival="迟到", seq=1)),
        }

        # W2:A 迟到更正把延迟由 40 订正成 5，读数仍留在业务期 W2。
        w2 = _reading_by_window("W2", "W2:A")
        assert w2["实际延迟"] == 5
        assert w2["更正序号"] == 1
        assert w2["业务期"] == "W2"
        assert w2["status"] == "达标"

        # W1 迟到读数归原观测期 W1。
        w1a = _reading_by_window("W1", "W1:A")
        assert w1a is not None
        assert w1a["业务期"] == "W1"
        assert w1a["到达性质"] == "迟到"

        # 失败的 W1:B 尚未产生窗口读数。
        assert _reading_by_window("W1", "W1:B") is None

        # 持报送回执查看：W1:B 尚未确认。
        receipt = service.get_receipt("RCP-1")
        assert receipt["unconfirmed_count"] == 1
        assert receipt["unconfirmed"][0]["batch_key"] == w1b_key

        # 持同一回执重试，不再注入失败，W1:B 补受理。
        retry = service.submit_batches(
            "RCP-1",
            [
                _batch("W1:A", "W1", 10, arrival="迟到"),
                _batch("W1:B", "W1", 45, arrival="迟到"),
                _batch("W2:A", "W2", 5, arrival="迟到", seq=1),
            ],
        )
        assert retry["attempt"] == "retry"
        assert retry["failed_count"] == 0
        assert retry["accepted_count"] == 3
        # 重试幂等：已确认批标记 duplicate，没有重复入账。
        statuses = {item["batch_key"]: item["status"] for item in retry["batch_results"]}
        assert statuses[w1b_key] == "accepted"
        assert sum(1 for s in statuses.values() if s == "duplicate") == 2

        # 重试后回执全部确认。
        receipt_after = service.get_receipt("RCP-1")
        assert receipt_after["unconfirmed_count"] == 0
        assert len(receipt_after["confirmed_keys"]) == 3

        # 两个等级目标按关联观测批次重算结算。
        settled = service.settle_sla(CONTRACT)
        assert settled["unconfirmed_count"] == 0
        assert len(settled["settlements"]) == 2

        sample_index = {
            (s["period"], s["source"]): s for s in settled["samples_used"]
        }
        # 现行样本覆盖 W1 两个来源与 W2 一个来源，共三笔窗口读数。
        assert set(sample_index) == {("W1", "W1:A"), ("W1", "W1:B"), ("W2", "W2:A")}
        # W2 采用的是更正后的 5 分钟样本，而不是 40 分钟旧值。
        assert sample_index[("W2", "W2:A")]["actual_minutes"] == 5
        assert sample_index[("W2", "W2:A")]["correction_seq"] == 1
        assert sample_index[("W2", "W2:A")]["lagging"] is False
        # W1 迟到读数归在 W1。
        assert sample_index[("W1", "W1:A")]["period"] == "W1"
        assert sample_index[("W1", "W1:B")]["period"] == "W1"

        by_target = {item["target_id"]: item for item in settled["settlements"]}
        # 三笔样本中仅 W1:B（45>30）滞后：可用率样本全部成功 => 100；
        # 新鲜度延迟达标 2/3 => 66.67，低于阈值 30（百分比口径）判未达标。
        assert by_target["SLA-BATCH-AVAIL"]["achievement"] == 100.0
        assert by_target["SLA-BATCH-AVAIL"]["breached"] is False
        assert by_target["SLA-BATCH-FRESH"]["achievement"] == 66.67
        assert by_target["SLA-BATCH-FRESH"]["breached"] is True
        assert by_target["SLA-BATCH-FRESH"]["sample_size"] == 3


class TestWindowReadingMergeRules:
    """窗口读数合并与更正序号规则。"""

    def test_original_and_supplement_same_seq_merge_into_one_reading(self):
        service = FreshnessBatchService()
        original = _batch("W1:B", "W1", 45, arrival="迟到", seq=2, water="W1@v1")
        service.submit_batches("RCP-M1", [original])
        before = _reading_by_window("W1", "W1:B")

        # 补送件带同一更正序号：合起来仍是一笔窗口读数。
        supplement = _batch(
            "W1:B", "W1", 45, piece="补送件", arrival="迟到", seq=2, water="W1@v1"
        )
        result = service.submit_batches("RCP-M2", [supplement])
        after = _reading_by_window("W1", "W1:B")

        assert after["读数编号"] == before["读数编号"]
        assert len(after["合并来源批"]) == 2
        assert after["更正序号"] == 2
        # 窗口读数表没有新增第二行。
        keys = [r["窗口键"] for r in store.rows(READING_MODULE)]
        assert keys.count(f"{CONTRACT}|W1|W1:B") == 1
        assert result["accepted_count"] == 1

    def test_higher_seq_replaces_current_value(self):
        service = FreshnessBatchService()
        service.submit_batches("RCP-H1", [_batch("W2:A", "W2", 40, seq=0, arrival="先到")])
        service.submit_batches("RCP-H2", [_batch("W2:A", "W2", 5, seq=1, arrival="迟到")])

        reading = _reading_by_window("W2", "W2:A")
        assert reading["更正序号"] == 1
        assert reading["实际延迟"] == 5
        assert reading["status"] == "达标"

    def test_stale_seq_does_not_overwrite_accepted_newer_reading(self):
        service = FreshnessBatchService()
        # 窗口读数先接受更正序号 2。
        service.submit_batches("RCP-S1", [_batch("W3:A", "W3", 8, seq=2, arrival="迟到")])
        # 旧序号 1 的补报迟到，新值不得覆盖现行读数。
        result = service.submit_batches("RCP-S2", [_batch("W3:A", "W3", 60, seq=1, arrival="迟到")])

        reading = _reading_by_window("W3", "W3:A")
        assert reading["更正序号"] == 2
        assert reading["实际延迟"] == 8
        assert result["stale_count"] == 1
        assert result["stale"][0]["incoming_seq"] == 1
        assert result["stale"][0]["accepted_seq"] == 2

        # 现行值（8 分钟、达标）继续供结算使用。
        settled = service.settle_sla(CONTRACT, periods=["W3"])
        sample = settled["samples_used"][0]
        assert sample["actual_minutes"] == 8
        assert sample["correction_seq"] == 2
        assert sample["lagging"] is False

    def test_late_reading_lands_in_original_period(self):
        service = FreshnessBatchService()
        service.submit_batches("RCP-L1", [
            _batch("W1:A", "W1", 25, arrival="迟到"),
            _batch("W2:A", "W2", 12, arrival="先到"),
        ])
        w1 = _reading_by_window("W1", "W1:A")
        w2 = _reading_by_window("W2", "W2:A")
        assert w1["业务期"] == "W1"
        assert w1["到达性质"] == "迟到"
        assert w2["业务期"] == "W2"
        assert w2["到达性质"] == "先到"


class TestReceiptIdempotency:
    """报送回执幂等与未确认来源批查询。"""

    def test_retry_with_same_receipt_is_idempotent(self):
        service = FreshnessBatchService()
        batches = [_batch("W1:A", "W1", 10)]
        first = service.submit_batches("RCP-IDEM", batches)
        second = service.submit_batches("RCP-IDEM", batches)

        assert first["attempt"] == "first"
        assert second["attempt"] == "retry"
        # 来源批表只有一条受理记录，窗口读数也只有一笔。
        rows = [b for b in store.rows(BATCH_MODULE) if b["receipt_no"] == "RCP-IDEM"]
        assert len(rows) == 1
        assert len(store.rows(READING_MODULE)) == 1
        receipt = service.get_receipt("RCP-IDEM")
        assert receipt["confirmed_count"] == 1

    def test_failed_batch_surfaces_as_unconfirmed_until_retry(self):
        service = FreshnessBatchService()
        payload = _batch("W1:B", "W1", 45)
        key = FreshnessBatchService.batch_key(payload)

        first = service.submit_batches("RCP-FAIL", [payload], fail_keys=[key])
        assert first["failed_count"] == 1
        receipt = service.get_receipt("RCP-FAIL")
        assert receipt["unconfirmed"][0]["batch_key"] == key

        # 重试成功后未确认清单清空，回执状态推进为全部确认。
        service.submit_batches("RCP-FAIL", [payload])
        receipt_after = service.get_receipt("RCP-FAIL")
        assert receipt_after["unconfirmed_count"] == 0
        stored = next(r for r in store.rows(RECEIPT_MODULE) if r["回执编号"] == "RCP-FAIL")
        assert stored["status"] == "全部确认"
        assert stored["尝试次数"] == 2
