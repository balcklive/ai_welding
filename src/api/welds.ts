/**
 * src/api/welds.ts — 焊缝数据（列表 · 登记 · 版本 · 核验）（§3.3 / §4.2）。
 *
 * - 列表服务端分页+筛选，按焊缝 ID 去重、仅最新版本；`tab` 传 `recent` 取最近登记。
 * - `registration_id` 兼容 DB id / registration_no / weld_id 三种标识。
 * - `attachRawFiles` 的 `storage_bytes` 可选（后端缺省 0）。
 */
import { request } from './client';
import type {
  DataRecord,
  DataVersion,
  Page,
  Registration,
  RegistrationForm,
  ValidationReport,
  WeldListQuery,
} from './types';

/** 数据列表：服务端分页 + 筛选。 */
export async function listWelds(
  params: WeldListQuery,
): Promise<Page<DataRecord>> {
  return request<Page<DataRecord>>('/welds', { query: params });
}

/** 单条焊缝详情（来源/焊机/模态/核验状态/最新版本）。 */
export async function getWeld(weldId: string): Promise<DataRecord> {
  return request<DataRecord>(`/welds/${weldId}`);
}

/** 新建登记：同时生成 v1.0「原始数据」版本，返回与 DataRecord 同构的登记信息。 */
export async function createRegistration(
  body: RegistrationForm,
): Promise<Registration> {
  return request<Registration>('/registrations', { method: 'POST', body });
}

/** 编辑选中数据的登记信息（body 部分字段可选）。 */
export async function updateRegistration(
  id: string,
  body: Partial<RegistrationForm>,
): Promise<Registration> {
  return request<Registration>(`/registrations/${id}`, {
    method: 'PATCH',
    body,
  });
}

/** 关联登记原始文件到 v1.0 版本：回填版本 object_keys 与记录容量。 */
export async function attachRawFiles(
  id: string,
  objectKeys: string[],
  storageBytes?: number,
): Promise<DataVersion> {
  const body: { object_keys: string[]; storage_bytes?: number } = {
    object_keys: objectKeys,
  };
  if (storageBytes !== undefined) {
    body.storage_bytes = storageBytes;
  }
  return request<DataVersion>(`/registrations/${id}/raw-files`, {
    method: 'POST',
    body,
  });
}

/** 登记信息详情。 */
export async function getRegistration(id: string): Promise<Registration> {
  return request<Registration>(`/registrations/${id}`);
}

/** 版本链（v1.0~v1.3 + 操作人/时间/动作）。 */
export async function listVersions(weldId: string): Promise<DataVersion[]> {
  return request<DataVersion[]>(`/welds/${weldId}/versions`);
}

/** 新建数据版本（去噪处理/人工修正等加工动作，不覆盖旧版）。 */
export async function createVersion(
  weldId: string,
  body: {
    action: '去噪处理' | '人工修正';
    note?: string;
    object_keys?: string[];
  },
): Promise<DataVersion> {
  return request<DataVersion>(`/welds/${weldId}/versions`, {
    method: 'POST',
    body,
  });
}

/** 单个版本详情。 */
export async function getVersion(
  weldId: string,
  versionId: string,
): Promise<DataVersion> {
  return request<DataVersion>(`/welds/${weldId}/versions/${versionId}`);
}

/** 执行核验（同步 15 项规则），返回质量评分 + 通过/警告/失败计数。 */
export async function runValidation(
  weldId: string,
  versionId: string,
): Promise<ValidationReport> {
  return request<ValidationReport>(
    `/welds/${weldId}/versions/${versionId}/validation`,
    { method: 'POST' },
  );
}

/** 核验明细：每条规则状态与异常原因、核验时间/耗时。 */
export async function getValidation(
  weldId: string,
  versionId: string,
): Promise<ValidationReport> {
  return request<ValidationReport>(
    `/welds/${weldId}/versions/${versionId}/validation`,
  );
}
