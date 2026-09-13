/**
 * src/api/settings.ts — 系统设置·可选项字典（`/api/v1/settings/options`）。
 *
 * 契约见 `docs/API接口清单.md` §3.13。写操作仅管理员（后端校验，403 → ApiError）。
 * 不做 GET 缓存：设置页改完必须立刻反映到登记页，避免 TTL 内读到旧字典。
 */

import { request } from './client';
import type { OptionGroup, OptionItem } from './types';

/** 全部选项组 + 选项（含已停用项）。 */
export async function listOptionGroups(): Promise<OptionGroup[]> {
  const data = await request<{ groups: OptionGroup[] }>('/settings/options');
  return data.groups ?? [];
}

/** 新增选项（同组重名 → 409）。 */
export async function createOptionItem(
  groupKey: string,
  body: { value: string; color?: string | null },
): Promise<OptionItem> {
  const data = await request<{ item: OptionItem }>(`/settings/options/${groupKey}`, {
    method: 'POST',
    body,
  });
  return data.item;
}

/** 改名 / 改颜色 / 停用-启用（空字段表示不改）。 */
export async function updateOptionItem(
  groupKey: string,
  itemId: number,
  body: { value?: string; color?: string | null; active?: boolean },
): Promise<OptionItem> {
  const data = await request<{ item: OptionItem }>(
    `/settings/options/${groupKey}/${itemId}`,
    { method: 'PATCH', body },
  );
  return data.item;
}

/** 上移 / 下移一位。 */
export async function moveOptionItem(
  groupKey: string,
  itemId: number,
  direction: 'up' | 'down',
): Promise<OptionItem[]> {
  const data = await request<{ items: OptionItem[] }>(
    `/settings/options/${groupKey}/${itemId}/move`,
    { method: 'POST', body: { direction } },
  );
  return data.items ?? [];
}

/**
 * 删除选项：被业务数据引用 → 软删（`mode='deactivated'`，转为停用）；
 * 未被引用 → 物理删除（`mode='deleted'`）。
 */
export async function deleteOptionItem(
  groupKey: string,
  itemId: number,
): Promise<{ mode: 'deleted' | 'deactivated'; value: string; references: number }> {
  return request<{ mode: 'deleted' | 'deactivated'; value: string; references: number }>(
    `/settings/options/${groupKey}/${itemId}`,
    { method: 'DELETE' },
  );
}
