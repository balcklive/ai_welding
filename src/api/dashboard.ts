/**
 * src/api/dashboard.ts — 数据总览（§3.2 / §4.2）。
 */
import { request } from './client';
import type {
  DashboardAttributes,
  DashboardDistributions,
  DashboardStats,
  Project,
} from './types';

export interface DashboardData {
  stats: DashboardStats;
  attributes: DashboardAttributes;
  distributions: DashboardDistributions;
  projects: Project[];
}

interface DashboardCacheEntry {
  fetchedAt: number;
  data: DashboardData;
}

const DASHBOARD_CACHE_KEY = 'ai-welding:dashboard:v1';
// Keep the browser cache short-lived so the overview remains current without
// requesting all four aggregates on every hard refresh. When Redis is added,
// move this cache contract to a server-side Redis key and keep this module as
// the API boundary; do not expose Redis credentials or connection details here.
const DASHBOARD_CACHE_TTL_MS = 5 * 60 * 1000;

function readDashboardCache(): DashboardData | null {
  try {
    const raw = localStorage.getItem(DASHBOARD_CACHE_KEY);
    if (!raw) return null;
    const entry = JSON.parse(raw) as DashboardCacheEntry;
    if (!entry?.fetchedAt || Date.now() - entry.fetchedAt >= DASHBOARD_CACHE_TTL_MS) {
      localStorage.removeItem(DASHBOARD_CACHE_KEY);
      return null;
    }
    return entry.data;
  } catch {
    localStorage.removeItem(DASHBOARD_CACHE_KEY);
    return null;
  }
}

function writeDashboardCache(data: DashboardData): void {
  try {
    localStorage.setItem(DASHBOARD_CACHE_KEY, JSON.stringify({ fetchedAt: Date.now(), data } satisfies DashboardCacheEntry));
  } catch {
    // Storage may be unavailable or full; the API response remains usable.
  }
}

/** Clear after a future dashboard-affecting mutation when immediate freshness is required. */
export function clearDashboardCache(): void {
  try {
    localStorage.removeItem(DASHBOARD_CACHE_KEY);
  } catch {
    // Ignore unavailable browser storage.
  }
}

/** 统计卡：数据总量 / 厂商总量 / 最大容量 / 已标注样本+完成度。 */
export async function getStats(): Promise<DashboardStats> {
  return request<DashboardStats>('/dashboard/stats');
}

/** 属性面板：焊机种类 / 缺陷种类 / 多模态种类 / 采集频率档位。 */
export async function getAttributes(): Promise<DashboardAttributes> {
  return request<DashboardAttributes>('/dashboard/attributes');
}

/** 分布图：厂商比重 / 过渡类型 / 焊接类型 / 缺陷分布 / 厂商词云。 */
export async function getDistributions(): Promise<DashboardDistributions> {
  return request<DashboardDistributions>('/dashboard/distributions');
}

/** 数据项目卡片（名称/状态/样本数/标注进度/最近更新）。 */
export async function getProjects(): Promise<Project[]> {
  return request<Project[]>('/dashboard/projects');
}

/**
 * Read all overview aggregates from one cache entry or fetch them together.
 * Future Redis migration: replace the localStorage read/write implementation
 * with a Redis-backed server cache and preserve the DashboardData shape.
 */
export async function getDashboardData(): Promise<DashboardData> {
  const cached = readDashboardCache();
  if (cached) return cached;

  const [stats, attributes, distributions, projects] = await Promise.all([
    getStats(),
    getAttributes(),
    getDistributions(),
    getProjects(),
  ]);
  const data = { stats, attributes, distributions, projects };
  writeDashboardCache(data);
  return data;
}
