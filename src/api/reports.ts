/**
 * src/api/reports.ts — 通用报告导出（§3.7 / §4.2）。
 *
 * `POST /reports/export` 为每个 ref_id 装配报告写 MinIO，返回预签名下载 URL 列表。
 */
import { request } from './client';
import type { ExportRequest } from './types';

/** 导出核验/分析/标注集/特征集/测试/数据列表报告。 */
export async function exportReport(
  body: ExportRequest,
): Promise<{ urls: { ref_id: string; url: string }[] }> {
  return request<{ urls: { ref_id: string; url: string }[] }>(
    '/reports/export',
    { method: 'POST', body },
  );
}
