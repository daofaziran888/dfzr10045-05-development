# 数契工坊 · 数据契约与服务化查询开放平台

面向数据契约登记、契约版本演进、字段承诺校验、消费方订阅、服务化查询端点、结果集快照、口径对账与双跑差异归因、新鲜度追踪、服务等级目标违约处置与用量计量的数据应用开放平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8002/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5175/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8002`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 数据契约 | `data_contract` | 数据契约 | 契约编号、契约名称、数据主题 |
| 契约版本 | `contract_version` | 契约版本 | 版本编号、所属契约、版本号 |
| 字段承诺 | `field_promise` | 字段承诺 | 承诺编号、所属版本、字段名称 |
| 消费方应用 | `consumer_app` | 消费方应用 | 应用编号、应用名称、所属团队 |
| 订阅计划 | `subscription_plan` | 订阅计划 | 订阅编号、消费方应用、所属契约 |
| 查询端点 | `service_endpoint` | 查询端点 | 端点编号、所属契约、端点路径 |
| 查询计划 | `query_plan` | 查询计划 | 计划编号、所属端点、筛选条件 |
| 结果集快照 | `result_set` | 结果集快照 | 快照编号、所属计划、绑定版本 |
| 缓存策略 | `cache_policy` | 缓存策略 | 策略编号、所属端点、缓存键构成 |
| 限流配额 | `rate_quota` | 限流配额 | 配额编号、消费方应用、所属端点 |
| 服务等级目标 | `sla_target` | 等级目标 | 目标编号、所属契约、目标类型 |
| 违约事件 | `sla_breach` | 违约事件 | 事件编号、所属目标、违约窗口 |
| 口径对账 | `reconcile_task` | 对账任务 | 对账编号、对账口径、左侧来源 |
| 双跑比对 | `dual_run` | 双跑记录 | 双跑编号、关联对账、旧口径版本 |
| 差异归因 | `diff_attrib` | 归因条目 | 归因编号、关联比对、差异字段 |
| 数据集发布 | `dataset_release` | 发布批次 | 发布编号、数据集名称、绑定版本 |
| 新鲜度追踪 | `freshness_track` | 新鲜度读数 | 读数编号、所属契约、承诺延迟 |
| 抽样探查 | `sample_probe` | 探查样本 | 样本编号、所属数据集、抽样比例 |
| 访问授权 | `access_grant` | 授权记录 | 授权编号、消费方应用、所属端点 |
| 用量计量 | `usage_meter` | 用量读数 | 计量编号、消费方应用、所属端点 |
| 服务事件 | `incident_log` | 服务事件 | 事件编号、所属端点、事件类别 |
| 契约审计 | `contract_audit` | 审计条目 | 条目编号、所属契约、操作类型 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 新鲜度来源批整组报送

新鲜度追踪除逐条登记外，另提供整组报送入口（`backend/app/services/freshness_batch.py`），
前端在「新鲜度追踪」页点「整组报送来源批」、在「服务等级目标」页点「按观测批次重算结算」。

- `POST /api/freshness/batch-submissions`：一个报送回执携带多个来源批，
  观测读数与迟到更正按来源批自报业务期批量写入；`fail_keys` 可注入部分失败。
- `GET  /api/freshness/batch-submissions/{receipt_no}`：持回执查询已确认与尚未确认的来源批。
- `GET  /api/freshness/window-readings`：原件与补送件按更正序号合并后的现行窗口读数。
- `GET  /api/freshness/source-batches`：来源批受理记录（可按回执过滤）。
- `POST /api/freshness/contracts/{contract_id}/settle-sla`：用关联观测批次重算
  等级目标结算样本，返回实际采用样本与尚未确认的来源批。

规则：同一回执重试幂等；原件与补送件带同一更正序号合并为一笔窗口读数；
迟到读数归原观测期、先到读数留在先到业务期；窗口读数已接受更新序号时，
旧序号新值不覆盖，现行值继续供结算。


领域：数据工程
子方向：数据分析与数据应用
