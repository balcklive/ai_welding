import { useCallback, useEffect, useState } from 'react';
import { ArrowDown, ArrowUp, Check, Pencil, Plus, RefreshCw, Trash2, X } from 'lucide-react';
import { ApiError } from '../../api/client';
import {
  createOptionItem, deleteOptionItem, listOptionGroups, moveOptionItem, updateOptionItem,
} from '../../api/settings';
import type { OptionGroup, OptionItem } from '../../api/types';
import { PageIntro } from '../../shared/components/PageIntro';
import { StatusPill } from '../../shared/components/StatusPill';

/** 正在编辑（改名）的选项定位。 */
interface EditingRef { groupKey: string; itemId: number; value: string }

/** 二次确认删除的选项定位（行内确认，避免阻塞式原生弹窗）。 */
interface DeleteRef { groupKey: string; itemId: number; value: string }

/** 统一取错误文案：后端 `err(code, message)` 的 message 直接透出。 */
const errorText = (err: unknown, fallback: string): string =>
  err instanceof ApiError && err.message ? err.message : err instanceof Error && err.message ? err.message : fallback;

/**
 * 系统设置页（`settings` 路由）：把数据登记/数据集录入的可选项做成可维护字典。
 *
 * 覆盖分组（后端 `OPTION_GROUPS` 定义，前端只按 key 渲染）：数据厂家/焊机型号、
 * 焊接方法、数据来源、产品/项目信息、数据集任务类型、标注缺陷类别。
 *
 * 关键规则：
 * - **停用即删减**：删除按钮调用 `DELETE`，后端按引用情况返回 `deleted`（物理删）
 *   或 `deactivated`（软删为停用）——页面按返回的 mode 给不同提示，不猜语义。
 * - **权限**：字典是全局配置，写操作仅管理员；403 时把后端文案原样提示，不做静默。
 * - **不缓存**：每次写操作成功后重新拉取全量分组，避免局部合并导致排序/停用态漂移。
 */
export function SettingsPage() {
  const [groups, setGroups] = useState<OptionGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState<EditingRef | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<DeleteRef | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setGroups(await listOptionGroups());
      setLoadError(null);
    } catch (err) {
      setLoadError(errorText(err, '可选项配置加载失败，请稍后重试'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  /** 统一的写操作包装：串行（pending 单值）、成功刷新、失败透出后端文案。
   *  `action` 返回字符串时作为提示文案（删除的软删/物理删差异化提示用）。 */
  const run = async (groupKey: string, action: () => Promise<string | void>, okText: string) => {
    if (pending) return;
    setPending(groupKey);
    setNotice(null);
    try {
      const custom = await action();
      await load();
      setNotice({ tone: 'ok', text: typeof custom === 'string' ? custom : okText });
    } catch (err) {
      setNotice({ tone: 'error', text: errorText(err, '操作失败，请重试') });
    } finally {
      setPending(null);
      setEditing(null);
      setConfirmDelete(null);
    }
  };

  const handleCreate = (group: OptionGroup) => {
    const value = (drafts[group.key] ?? '').trim();
    if (!value) return;
    void run(group.key, async () => {
      await createOptionItem(group.key, { value });
      setDrafts((prev) => ({ ...prev, [group.key]: '' }));
    }, `已新增「${value}」`);
  };

  const handleRename = () => {
    if (!editing) return;
    const { groupKey, itemId, value } = editing;
    const next = value.trim();
    if (!next) return;
    void run(groupKey, () => updateOptionItem(groupKey, itemId, { value: next }).then(() => undefined), `已改名为「${next}」`);
  };

  const handleToggleActive = (group: OptionGroup, item: OptionItem) =>
    void run(
      group.key,
      () => updateOptionItem(group.key, item.id, { active: !item.active }).then(() => undefined),
      item.active ? `已停用「${item.value}」（历史数据不受影响）` : `已启用「${item.value}」`,
    );

  const handleMove = (group: OptionGroup, item: OptionItem, direction: 'up' | 'down') =>
    void run(group.key, () => moveOptionItem(group.key, item.id, direction).then(() => undefined), '顺序已更新');

  const handleDelete = (group: OptionGroup, item: OptionItem) =>
    void run(group.key, async () => {
      const result = await deleteOptionItem(group.key, item.id);
      return result.mode === 'deactivated'
        ? `「${item.value}」已被 ${result.references} 条历史数据引用，已转为停用（历史数据仍正常显示）`
        : `已删除「${item.value}」`;
    }, `已处理「${item.value}」`);

  const totalItems = groups.reduce((sum, group) => sum + group.items.length, 0);

  return <div className="page-wrap">
    <PageIntro
      eyebrow="系统管理"
      title="系统设置"
      description="维护数据登记与数据集录入时的可选项：厂家/焊机型号、焊接方法、数据来源、产品信息、任务类型与标注类别。"
      action={<span className="workflow-chip"><Check size={14} />共 {groups.length} 组 · {totalItems} 项</span>}
    />
    <section className="panel settings-intro">
      <div>
        <h2>可选项字典</h2>
        <p>这里的增删改立即作用于录入表单，无需改代码或重新发布。删除已被历史数据引用的选项时会自动转为「停用」——录入时不再可选，历史台账仍按原值显示。</p>
      </div>
      <button className="outline-button" onClick={() => void load()} disabled={loading}>
        <RefreshCw size={14} />{loading ? '刷新中…' : '刷新'}
      </button>
    </section>
    {notice && <p className={notice.tone === 'error' ? 'toolbar-error settings-notice' : 'accent-text settings-notice'} role={notice.tone === 'error' ? 'alert' : 'status'}>{notice.text}</p>}
    {loadError && <p className="toolbar-error settings-notice" role="alert">{loadError}</p>}
    {loading && !groups.length ? <p className="dataset-empty-state" role="status">可选项配置加载中…</p> : (
      <div className="settings-grid">
        {groups.map((group) => <section className="panel settings-panel" key={group.key}>
          <div className="panel-heading">
            <div>
              <h2>{group.label} <span className="inline-count">{group.items.filter((item) => item.active).length} 启用 / {group.items.length} 项</span></h2>
              <p>{group.description}</p>
            </div>
          </div>
          <div className="settings-add">
            <input
              value={drafts[group.key] ?? ''}
              placeholder={group.key === 'product' ? '例如：某型号构件焊接项目' : '输入新增选项'}
              onChange={(event) => setDrafts((prev) => ({ ...prev, [group.key]: event.target.value }))}
              onKeyDown={(event) => { if (event.key === 'Enter') handleCreate(group); }}
            />
            <button className="primary-button" disabled={pending === group.key || !(drafts[group.key] ?? '').trim()} onClick={() => handleCreate(group)}>
              <Plus size={14} />新增
            </button>
          </div>
          {group.items.length ? <div className="settings-item-list">
            {group.items.map((item, index) => {
              const isEditing = editing?.groupKey === group.key && editing.itemId === item.id;
              const isConfirming = confirmDelete?.groupKey === group.key && confirmDelete.itemId === item.id;
              return <div className={`settings-item ${item.active ? '' : 'settings-item--off'}`} key={item.id}>
                {group.color && <i className="settings-color-dot" style={{ background: item.color ?? '#c9d8d6' }} />}
                {isEditing ? <input
                  className="settings-item-input"
                  autoFocus
                  value={editing.value}
                  onChange={(event) => setEditing({ ...editing, value: event.target.value })}
                  onKeyDown={(event) => { if (event.key === 'Enter') handleRename(); if (event.key === 'Escape') setEditing(null); }}
                /> : <strong className="settings-item-value">{item.value}</strong>}
                {!item.active && <StatusPill tone="muted">已停用</StatusPill>}
                <div className="settings-item-actions">
                  {isEditing ? <>
                    <button className="ghost-button" onClick={handleRename} disabled={pending === group.key}><Check size={13} />保存</button>
                    <button className="ghost-button" onClick={() => setEditing(null)}><X size={13} />取消</button>
                  </> : isConfirming ? <>
                    <button className="danger-button" onClick={() => handleDelete(group, item)} disabled={pending === group.key}><Trash2 size={13} />确认删除</button>
                    <button className="ghost-button" onClick={() => setConfirmDelete(null)}>取消</button>
                  </> : <>
                    <button className="icon-button" title="上移" aria-label={`上移 ${item.value}`} disabled={index === 0 || pending === group.key} onClick={() => handleMove(group, item, 'up')}><ArrowUp size={13} /></button>
                    <button className="icon-button" title="下移" aria-label={`下移 ${item.value}`} disabled={index === group.items.length - 1 || pending === group.key} onClick={() => handleMove(group, item, 'down')}><ArrowDown size={13} /></button>
                    <button className="ghost-button" onClick={() => setEditing({ groupKey: group.key, itemId: item.id, value: item.value })}><Pencil size={13} />改名</button>
                    <button className="ghost-button" onClick={() => handleToggleActive(group, item)}>{item.active ? '停用' : '启用'}</button>
                    <button className="ghost-button settings-delete" onClick={() => setConfirmDelete({ groupKey: group.key, itemId: item.id, value: item.value })}><Trash2 size={13} />删除</button>
                  </>}
                </div>
              </div>;
            })}
          </div> : <p className="dataset-empty-state" role="status">该分组暂无选项，新增后将出现在对应录入表单/标注调色板中。</p>}
        </section>)}
      </div>
    )}
  </div>;
}
