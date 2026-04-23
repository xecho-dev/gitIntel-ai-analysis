import axios from 'axios';
import type {
  AdminUserListResponse,
  AdminHistoryListResponse,
  AdminOverviewStats,
  AdminHistoryDetailResponse,
  AdminUserHistoryResponse,
  HistoryFilterParams,
} from '@/types';

const baseURL = '/api';

const request = axios.create({
  baseURL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

request.interceptors.request.use((config) => config, (error) => Promise.reject(error));

request.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const message = error.response?.data?.detail || error.message || '请求失败';
    console.error('[API Error]', message);
    return Promise.reject(error);
  }
);

export default request;

// ─── 管理端 API ──────────────────────────────────────────────────────────────

/** 系统概览统计数据 */
export const getOverviewStats = (): Promise<AdminOverviewStats> =>
  request.get('/admin/overview');

/** 全部用户列表（分页） */
export const getUserList = (params?: { page?: number; pageSize?: number; search?: string }): Promise<AdminUserListResponse> =>
  request.get('/admin/users', { params });

/** 更新指定用户信息（禁用/启用等） */
export const updateUser = (userId: string, data: Record<string, unknown>) =>
  request.put(`/admin/users/${userId}`, data);

/** 全站分析历史（分页） */
export const getAnalysisHistory = (params?: {
  page?: number;
  pageSize?: number;
  search?: string;
}): Promise<AdminHistoryListResponse> =>
  request.get('/admin/analysis-history', { params });

/** 删除指定分析记录 */
export const deleteAnalysisRecord = (recordId: string) =>
  request.delete(`/admin/analysis-history/${recordId}`);

/** 分析历史高级筛选（支持多条件） */
export const getFilteredHistory = (params?: HistoryFilterParams): Promise<AdminHistoryListResponse> =>
  request.get('/admin/analysis-history', { params });

/** 获取单条分析记录详情（包含用户信息 + LangSmith追踪信息） */
export const getHistoryDetail = (recordId: string): Promise<AdminHistoryDetailResponse> =>
  request.get(`/admin/analysis-history/${recordId}`);

/** 获取指定用户的分析历史（包含用户基本信息） */
export const getUserHistory = (userId: string, params?: {
  page?: number;
  pageSize?: number;
  search?: string;
}): Promise<AdminUserHistoryResponse> =>
  request.get(`/admin/users/${userId}/history`, { params });