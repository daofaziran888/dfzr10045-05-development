<template>
  <section class="page" :data-module="meta.key">
    <header class="page-head">
      <div>
        <h2>{{ meta.name }}</h2>
        <p class="page-desc">{{ meta.desc }}</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">
          登记{{ meta.entity }}
        </button>
        <button
          v-if="meta.key === 'freshness_track'"
          class="btn primary"
          data-testid="open-batch-submission"
          type="button"
          @click="openBatchSubmission"
        >
          整组报送来源批
        </button>
        <button
          v-if="meta.key === 'sla_target'"
          class="btn primary"
          data-testid="open-settle"
          type="button"
          @click="openSettle"
        >
          按观测批次重算结算
        </button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">
          导出{{ meta.name }}清单
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p class="status-legend">
      <span v-for="item in statusSummary" :key="item.status" class="legend-item">
        {{ item.status }}：{{ item.count }}
      </span>
    </p>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in meta.fields" :key="column">{{ column }}</th>
          <th>当前状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in meta.fields" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.status }}</td>
          <td class="row-actions">
            <button
              v-for="action in meta.actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="meta.fields.length + 2" class="empty-state">
            暂无{{ meta.name }}数据，可先登记{{ meta.entity }}
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记{{ meta.entity }}</h3>
        <label v-for="field in meta.fields" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <div v-if="showBatch" class="modal-backdrop" data-testid="batch-modal">
      <form class="modal modal-wide" @submit.prevent="submitBatch">
        <h3>整组报送来源批</h3>
        <p class="page-desc">
          一次上报多个来源批，观测读数与迟到更正按自报业务期写入；原件与补送件带同一更正序号合并为一笔窗口读数。
        </p>
        <label class="create-field">
          <span>报送回执</span>
          <input v-model="receiptNo" data-testid="batch-receipt-no" placeholder="如 RCP-20261125-001" required />
        </label>
        <label class="create-field">
          <span>模拟部分失败的来源批键（每行一个，可选）</span>
          <textarea
            v-model="failKeysText"
            data-testid="batch-fail-keys"
            rows="2"
            placeholder="如 CTR-001|W1|W1:B|原件|0"
          ></textarea>
        </label>

        <table class="data-table batch-table">
          <thead>
            <tr>
              <th>来源批</th>
              <th>所属契约</th>
              <th>业务期</th>
              <th>件别</th>
              <th>更正序号</th>
              <th>承诺延迟</th>
              <th>实际延迟</th>
              <th>到达性质</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in batchRows" :key="index" data-testid="batch-row">
              <td><input v-model="row.来源批" required placeholder="W1:A" /></td>
              <td><input v-model="row.所属契约" required placeholder="CTR-001" /></td>
              <td><input v-model="row.业务期" required placeholder="W1" /></td>
              <td>
                <select v-model="row.件别">
                  <option>原件</option>
                  <option>补送件</option>
                </select>
              </td>
              <td><input v-model.number="row.更正序号" type="number" min="0" /></td>
              <td><input v-model.number="row.承诺延迟" type="number" min="0" /></td>
              <td><input v-model.number="row.实际延迟" type="number" min="0" /></td>
              <td>
                <select v-model="row.到达性质">
                  <option value="">自动判定</option>
                  <option>先到</option>
                  <option>迟到</option>
                </select>
              </td>
              <td>
                <button class="link" type="button" data-testid="batch-remove-row" @click="removeBatchRow(index)">
                  移除
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <div class="page-actions">
          <button class="btn" type="button" data-testid="batch-add-row" @click="addBatchRow">添加来源批</button>
          <button class="btn" type="button" @click="loadReceipt">按回执查询进度</button>
        </div>

        <div v-if="batchResult" class="batch-result" data-testid="batch-result">
          <p>
            受理 {{ batchResult.accepted_count }}/{{ batchResult.batch_count }} 批，
            失败 {{ batchResult.failed_count }} 批，旧序号压制 {{ batchResult.stale_count }} 批，
            本次为{{ batchResult.attempt === 'retry' ? '回执重试' : '首次报送' }}。
          </p>
          <ul v-if="batchResult.failed.length" class="error-list">
            <li v-for="item in batchResult.failed" :key="item.batch_key">未确认：{{ item.batch_key }} — {{ item.message }}</li>
          </ul>
          <ul v-if="batchResult.stale.length" class="stale-list">
            <li v-for="item in batchResult.stale" :key="item.batch_key">
              窗口 {{ item.window_key }} 已接受序号 {{ item.accepted_seq }}，旧序号 {{ item.incoming_seq }} 新值不覆盖，现行值继续供结算
            </li>
          </ul>
        </div>
        <div v-if="receiptDetail" class="batch-result" data-testid="receipt-detail">
          <p>
            回执 {{ receiptDetail.receipt_no }}：已确认 {{ receiptDetail.confirmed_count }} 批，
            尚未确认 {{ receiptDetail.unconfirmed_count }} 批。
          </p>
          <ul v-if="receiptDetail.unconfirmed.length" class="error-list">
            <li v-for="item in receiptDetail.unconfirmed" :key="item.batch_key">{{ item.batch_key }} — {{ item.message }}</li>
          </ul>
        </div>

        <div class="page-actions">
          <button class="btn" type="button" @click="showBatch = false">关闭</button>
          <button class="btn primary" data-testid="submit-batch" type="submit" :disabled="submittingBatch">
            {{ submittingBatch ? '报送中…' : '确认整组报送' }}
          </button>
        </div>
      </form>
    </div>

    <div v-if="showSettle" class="modal-backdrop" data-testid="settle-modal">
      <form class="modal modal-wide" @submit.prevent="runSettle">
        <h3>按观测批次重算等级目标结算</h3>
        <label class="create-field">
          <span>所属契约</span>
          <input v-model="settleContract" data-testid="settle-contract" required placeholder="如 CTR-001" />
        </label>
        <label class="create-field">
          <span>限定业务期（逗号分隔，留空取全部窗口读数）</span>
          <input v-model="settlePeriodsText" data-testid="settle-periods" placeholder="W1,W2" />
        </label>
        <div v-if="settleResult" data-testid="settle-result">
          <table class="data-table">
            <thead>
              <tr><th>等级目标</th><th>目标类型</th><th>样本数</th><th>达成率</th><th>是否违约</th></tr>
            </thead>
            <tbody>
              <tr v-for="item in settleResult.settlements" :key="item.target_id">
                <td>{{ item.target_id }}</td>
                <td>{{ item.target_type }}</td>
                <td>{{ item.sample_size }}</td>
                <td>{{ item.achievement }}</td>
                <td :data-status="item.breached ? '未达标' : '达标'">{{ item.breached ? '未达标' : '达标' }}</td>
              </tr>
            </tbody>
          </table>
          <p class="page-desc">
            实际样本 {{ settleResult.samples_used.length }} 笔；尚未确认来源批 {{ settleResult.unconfirmed_count }} 批。
          </p>
          <ul v-if="settleResult.unconfirmed_batches.length" class="error-list">
            <li v-for="item in settleResult.unconfirmed_batches" :key="item.batch_key">
              {{ item.batch_key }}（{{ item.receipt_no }}）— {{ item.message }}
            </li>
          </ul>
        </div>
        <div class="page-actions">
          <button class="btn" type="button" @click="showSettle = false">关闭</button>
          <button class="btn primary" data-testid="submit-settle" type="submit" :disabled="settling">
            {{ settling ? '重算中…' : '重算结算' }}
          </button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条{{ meta.name }}记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  createEntry,
  downloadEntries,
  getFreshnessReceipt,
  listEntries,
  moduleMeta,
  runAction as applyAction,
  settleFreshnessSla,
  submitFreshnessBatches,
} from '@/api/backend-service'
import type {
  BatchSubmissionResult,
  ReceiptDetail,
  SlaSettlement,
  SourceBatchInput,
} from '@/api/backend-service'
import type { EntryRow } from '@/data/types'

const props = defineProps<{ moduleKey: string }>()
const meta = moduleMeta(props.moduleKey)
const rows = ref<EntryRow[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = meta.fields.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})
const stats = computed(() => [
  { label: meta.metrics[0], value: total.value },
  { label: meta.metrics[1], value: rows.value.filter((row) => row.status === meta.statuses[1]).length },
  {
    label: meta.metrics[2],
    value: rows.value.filter((row) => row.status === meta.statuses[meta.statuses.length - 1]).length,
  },
])
const statusSummary = computed(() =>
  meta.statuses.map((status) => ({
    status,
    count: rows.value.filter((row) => String(row.status) === status).length,
  })),
)

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  try {
    await downloadEntries(meta.key, filters.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(meta.fields.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const result = await createEntry(meta.key, createValues.value)
    if (!result.ok) throw new Error(result.message)
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: EntryRow) {
  errorMessage.value = ''
  try {
    const result = await applyAction(meta.key, Number(row.id), action)
    if (!result.ok) throw new Error(result.message)
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await listEntries(meta.key, filters.value)
    rows.value = payload.items
    total.value = payload.total
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '业务列表读取失败'
  }
}

// ---------------------------------------------------------------------------
// 新鲜度来源批整组报送
// ---------------------------------------------------------------------------
function emptyBatchRow(): SourceBatchInput {
  return {
    来源批: '',
    所属契约: '',
    业务期: '',
    件别: '原件',
    更正序号: 0,
    承诺延迟: 0,
    实际延迟: 0,
    数据水位: '',
    到达性质: '',
  }
}

const showBatch = ref(false)
const submittingBatch = ref(false)
const receiptNo = ref('')
const failKeysText = ref('')
const batchRows = ref<SourceBatchInput[]>([emptyBatchRow(), emptyBatchRow(), emptyBatchRow()])
const batchResult = ref<BatchSubmissionResult | null>(null)
const receiptDetail = ref<ReceiptDetail | null>(null)

function openBatchSubmission() {
  batchResult.value = null
  receiptDetail.value = null
  errorMessage.value = ''
  showBatch.value = true
}

function addBatchRow() {
  batchRows.value.push(emptyBatchRow())
}

function removeBatchRow(index: number) {
  batchRows.value.splice(index, 1)
}

async function submitBatch() {
  submittingBatch.value = true
  errorMessage.value = ''
  try {
    const failKeys = failKeysText.value
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
    batchResult.value = await submitFreshnessBatches(
      receiptNo.value.trim(),
      batchRows.value.filter((row) => row.来源批 && row.所属契约 && row.业务期),
      failKeys,
    )
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '整组报送失败'
  } finally {
    submittingBatch.value = false
  }
}

async function loadReceipt() {
  errorMessage.value = ''
  try {
    receiptDetail.value = await getFreshnessReceipt(receiptNo.value.trim())
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '回执查询失败'
  }
}

// ---------------------------------------------------------------------------
// 服务等级目标：按关联观测批次重算结算
// ---------------------------------------------------------------------------
const showSettle = ref(false)
const settling = ref(false)
const settleContract = ref('')
const settlePeriodsText = ref('')
const settleResult = ref<SlaSettlement | null>(null)

function openSettle() {
  settleResult.value = null
  errorMessage.value = ''
  showSettle.value = true
}

async function runSettle() {
  settling.value = true
  errorMessage.value = ''
  try {
    const periods = settlePeriodsText.value
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)
    settleResult.value = await settleFreshnessSla(settleContract.value.trim(), periods)
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '重算结算失败'
  } finally {
    settling.value = false
  }
}

onMounted(reload)
</script>
