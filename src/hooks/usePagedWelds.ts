/**
 * src/hooks/usePagedWelds.ts — 样本选择器的分页搜索（T9 / R5）。
 *
 * 顶部的「当前处理数据」选择器与分析「选择数据」卡片原先都固定 `page_size: 50` 且没有翻页入口
 * ——第 51 条之后**永远选不到**。这里把两处收敛到同一个钩子：服务端搜索（300ms 防抖）+ 分页
 * 追加（`loadMore`），默认每页 20、与后端上限 100 对齐。
 *
 * 读取语义按 T3.2：失败时清空本列表并置错误态（不保留上一个数据集的候选，R8），由调用方渲染
 * `ErrorState` + 重试；切换数据集 / 改关键词都会从第 1 页重新开始。
 */
import { useCallback, useEffect, useState } from 'react';
import { listWelds } from '../api/welds';
import type { DataRecord } from '../api/types';

/** 选择器每页条数（与 T9 的默认值一致；后端 `page_size` 上限 100）。 */
export const SELECTOR_PAGE_SIZE = 20;

export interface UsePagedWeldsReturn {
  items: DataRecord[];
  total: number;
  /** 还有未加载的下一页。 */
  hasMore: boolean;
  loading: boolean;
  error: unknown;
  /** 加载下一页并追加（`hasMore` 为 false 时是空操作）。 */
  loadMore: () => void;
  /** 重新从第 1 页拉（错误态重试）。 */
  retry: () => void;
}

export function usePagedWelds(
  datasetId: number | null,
  query: string,
  pageSize = SELECTOR_PAGE_SIZE,
): UsePagedWeldsReturn {
  const [items, setItems] = useState<DataRecord[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const trimmed = query.trim();

  useEffect(() => {
    if (datasetId == null) {
      setItems([]);
      setTotal(0);
      setPage(1);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    const timer = window.setTimeout(() => {
      listWelds({ dataset_id: datasetId, q: trimmed || undefined, page: 1, page_size: pageSize })
        .then((res) => {
          if (cancelled) return;
          setItems(res.items);
          setTotal(res.total);
          setPage(1);
        })
        .catch((err) => {
          if (cancelled) return;
          // 清空旧候选：不能把上一个数据集/上一个关键词的结果当成这次的结果（R8）
          setItems([]);
          setTotal(0);
          setError(err);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 300);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [datasetId, trimmed, pageSize, reloadKey]);

  const loadMore = useCallback(() => {
    if (datasetId == null || loading || items.length >= total) return;
    const nextPage = page + 1;
    setLoading(true);
    listWelds({ dataset_id: datasetId, q: trimmed || undefined, page: nextPage, page_size: pageSize })
      .then((res) => {
        // 按 weld_id 去重：并发新增数据时服务端分页可能把同一条推到两页里
        setItems((prev) => {
          const seen = new Set(prev.map((item) => item.weld_id));
          return [...prev, ...res.items.filter((item) => !seen.has(item.weld_id))];
        });
        setTotal(res.total);
        setPage(nextPage);
        setError(null);
      })
      .catch(setError)
      .finally(() => setLoading(false));
  }, [datasetId, items.length, loading, page, pageSize, total, trimmed]);

  const retry = useCallback(() => setReloadKey((n) => n + 1), []);

  return {
    items,
    total,
    hasMore: items.length < total,
    loading,
    error,
    loadMore,
    retry,
  };
}
