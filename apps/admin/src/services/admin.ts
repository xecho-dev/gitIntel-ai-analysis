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

// Inject admin auth token from localStorage on every request
request.interceptors.request.use((config) => {
  try {
    const token = localStorage.getItem('admin_token');
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`;
    }
  } catch {
    // localStorage not available
  }
  return config;
});

request.interceptors.response.use(
  (response) => response.data,
  (error) => {
    // If 401, clear auth and redirect to login
    if (error.response?.status === 401) {
      try {
        localStorage.removeItem('admin_token');
        localStorage.removeItem('admin_user');
        localStorage.removeItem('admin_token_expires_at');
      } catch {
        // ignore
      }
      if (typeof window !== 'undefined' && !window.location.pathname.includes('/login')) {
        window.location.href = '/login';
      }
    }
    const message = error.response?.data?.detail || error.message || '请求失败';
    console.error('[API Error]', message);
    return Promise.reject(error);
  }
);

export default request;

// ─── Admin Auth API ───────────────────────────────────────────────────────────

export interface AdminLoginResponse {
  token: string;
  expires_at: string;
  user: {
    id: string;
    username: string;
    nickname: string;
    avatar?: string | null;
    role: string;
  };
}

export interface AdminMeResponse {
  id: string;
  username: string;
  nickname: string;
  avatar?: string | null;
  role: string;
}

/** 管理员登录 */
export const adminLogin = (username: string, password: string): Promise<AdminLoginResponse> =>
  request.post('/admin/login', { username, password });

/** 注销当前 token */
export const adminLogout = (): Promise<{ success: boolean }> =>
  request.post('/admin/logout');

/** 获取当前登录管理员信息 */
export const adminMe = (): Promise<AdminMeResponse> =>
  request.get('/admin/me');

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