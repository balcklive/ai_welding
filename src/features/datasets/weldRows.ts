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

export const mockWeldRows: WeldRow[] = [
  { id: 'WLD-20260815-0248', time: '2026-08-15 09:42', source: '产线相机 · 03号', machine: 'Fronius CMT', types: '视频 / 时序 / 声音', quality: '通过', version: 'v1.3' },
  { id: 'WLD-20260815-0247', time: '2026-08-15 09:18', source: '实训线 · 02号', machine: 'OTC FD-V8', types: '视频 / 时序', quality: '待复核', version: 'v2.0' },
  { id: 'WLD-20260814-0246', time: '2026-08-14 18:32', source: '产线相机 · 03号', machine: 'Kemppi Minarc', types: '视频 / 时序 / 红外', quality: '通过', version: 'v1.1' },
  { id: 'WLD-20260814-0245', time: '2026-08-14 16:07', source: '实训线 · 01号', machine: 'Panasonic YD-500', types: '视频 / 声音', quality: '异常', version: 'v1.0' },
];
