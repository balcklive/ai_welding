import type { DataRecord } from '../../api/types';

export interface WeldRow {
  id: string;
  time: string;
  source: string;
  machine: string;
  types: string;
  quality: string;
  version: string;
}

export function toWeldRow(record: DataRecord): WeldRow {
  return {
    id: record.weld_id,
    time: record.collected_at ?? record.created_at ?? '—',
    source: record.source,
    machine: record.machine ?? '—',
    types: (record.modalities ?? []).join(' / ') || '—',
    quality: record.quality,
    version: record.latest_version?.version_no ?? '—',
  };
}

// T3.2：`mockWeldRows` 已删除——接口失败一律走错误态，不再用演示数据兜底。

