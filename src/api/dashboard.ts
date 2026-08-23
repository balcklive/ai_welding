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
