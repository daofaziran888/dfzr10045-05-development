"""测试共享固件：每次测试前把内存仓库重置回种子数据，隔离跨用例污染。

服务与测试普遍以 ``from app.store import store`` 持有同一个单例引用，
因此不替换实例，而是原地清空并重灌种子表，保证所有持有方看到的都是同一份新数据。
"""
from __future__ import annotations

import importlib

import pytest

import app.seed as _seed
import app.store as _store_mod


@pytest.fixture(autouse=True)
def clean_store():
    """每个测试用例使用独立的种子数据快照，防止跨测试数据污染。"""
    seed_module = importlib.reload(_seed)
    store = _store_mod.store
    store._tables = {
        name: [dict(row) for row in rows]
        for name, rows in seed_module.SEED_ROWS.items()
    }
    yield store
