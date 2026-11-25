import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type { ActionResult, EntryRow, OverviewResult, PageResult } from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

// 新鲜度来源批整组报送相关类型与接口。
export type SourceBatchInput = {
  来源批: string
  所属契约: string
  业务期: string
  件别?: string
  更正序号?: number
  承诺延迟?: number
  实际延迟?: number
  数据水位?: string
  到达性质?: string | null
}

export type BatchSubmissionResult = {
  receipt_no: string
  attempt: 'first' | 'retry'
  batch_count: number
  accepted_count: number
  failed_count: number
  stale_count: number
  accepted_keys: string[]
  failed: { batch_key: string; message: string }[]
  stale: { batch_key: string; window_key: string; accepted_seq: number; incoming_seq: number }[]
  batch_results: {
    batch_key: string
    status: 'accepted' | 'failed' | 'stale' | 'duplicate'
    message: string
  }[]
  window_readings: Record<string, string | number | boolean>[]
  receipt: Record<string, string | number | boolean | string[]>
}

export type ReceiptDetail = {
  receipt_no: string
  confirmed_keys: string[]
  unconfirmed: { batch_key: string; status: string; message: string }[]
  confirmed_count: number
  unconfirmed_count: number
  batch_records: Record<string, string | number | boolean>[]
}

export type WindowReading = EntryRow & {
  读数编号: string
  窗口键: string
  所属契约: string
  业务期: string
  来源标识: string
  承诺延迟: number
  实际延迟: number
  更正序号: number
  到达性质: string
  合并来源批: string[]
  迟到件数: number
}

export type SlaSettlement = {
  contract_id: string
  periods: string[]
  settlements: {
    target_id: string
    target_type: string
    threshold: number
    achievement: number
    breached: boolean
    sample_size: number
    samples: Record<string, string | number | boolean>[]
  }[]
  samples_used: Record<string, string | number | boolean>[]
  unconfirmed_batches: { batch_key: string; receipt_no: string; status: string; message: string }[]
  unconfirmed_count: number
}

export async function submitFreshnessBatches(
  receiptNo: string,
  batches: SourceBatchInput[],
  failKeys: string[] = [],
): Promise<BatchSubmissionResult> {
  const response = await request('/api/freshness/batch-submissions', {
    method: 'POST',
    body: JSON.stringify({ receipt_no: receiptNo, batches, fail_keys: failKeys }),
  })
  if (!response.ok) throw new Error('来源批整组报送失败')
  return await response.json()
}

export async function getFreshnessReceipt(receiptNo: string): Promise<ReceiptDetail> {
  const response = await request(`/api/freshness/batch-submissions/${encodeURIComponent(receiptNo)}`)
  if (!response.ok) throw new Error('报送回执读取失败')
  return await response.json()
}

export async function listWindowReadings(contractId = ''): Promise<{ items: WindowReading[]; total: number }> {
  const query = contractId ? `?contract_id=${encodeURIComponent(contractId)}` : ''
  const response = await request(`/api/freshness/window-readings${query}`)
  if (!response.ok) throw new Error('窗口读数读取失败')
  return await response.json()
}

export async function settleFreshnessSla(
  contractId: string,
  periods: string[] = [],
): Promise<SlaSettlement> {
  const response = await request(`/api/freshness/contracts/${encodeURIComponent(contractId)}/settle-sla`, {
    method: 'POST',
    body: JSON.stringify({ periods }),
  })
  if (!response.ok) throw new Error('等级目标重算结算失败')
  return await response.json()
}
