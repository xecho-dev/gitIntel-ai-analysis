"use client";

import React, { useState, useEffect, useCallback } from "react";
import { motion } from "motion/react";
import {
  Search,
  Filter,
  RefreshCw,
  History,
  ChevronRight,
  TrendingUp,
  ShieldAlert,
  Code2,
  Trash2,
  Loader2,
  GitBranch,
  ExternalLink,
  AlertTriangle,
  CheckCircle,
  XCircle,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { Modal } from "@/components/ui/Modal";
import { cn } from "@/lib/utils";
import type { HistoryItem, HistoryStats, HistoryListResponse } from "@/lib/types";

const PAGE_SIZE = 20;

function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  const diffHour = Math.floor(diffMs / 3600000);
  const diffDay = Math.floor(diffMs / 86400000);

  if (diffMin < 1) return "刚刚";
  if (diffMin < 60) return `${diffMin} 分钟前`;
  if (diffHour < 24) return `${diffHour} 小时前`;
  if (diffDay < 30) return `${diffDay} 天前`;
  return date.toLocaleDateString("zh-CN", { year: "numeric", month: "long", day: "numeric" });
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function healthLabel(score: number | null): string {
  if (score === null) return "—";
  if (score >= 85) return `优 (${score}%)`;
  if (score >= 60) return `良 (${score}%)`;
  return `危 (${score}%)`;
}

// ─── Detail Modal ───────────────────────────────────────────────

interface DetailModalProps {
  item: HistoryItem;
  onClose: () => void;
}

function DetailModal({ item, onClose }: DetailModalProps) {
  const result = item.result_data;
  const repoUrl = item.repo_url;
  const branch = item.branch;

  return (
    <Modal open onClose={onClose} title={`分析详情 · ${item.repo_name}`}>
      <div className="space-y-6">
        {/* Repo Info */}
        <div className="flex items-center gap-3 p-4 rounded-lg bg-[#0a0e14] border border-white/5">
          <Code2 className="text-blue-400" size={20} />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-bold text-[#dfe2eb] truncate">{item.repo_name}</p>
            <p className="text-xs text-slate-500 truncate">{repoUrl}</p>
          </div>
          {branch && (
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-sm bg-[#31353c] text-xs text-slate-300 border border-white/5">
              <GitBranch size={12} />
              {branch}
            </div>
          )}
          <a
            href={repoUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="p-2 rounded-md text-slate-400 hover:text-white hover:bg-white/10 transition-colors"
            title="在 GitHub 查看"
          >
            <ExternalLink size={14} />
          </a>
        </div>

        {/* Scores Summary */}
        <div className="grid grid-cols-3 gap-3">
          <ScoreCard
            label="架构健康度"
            value={item.health_score}
            suffix="%"
            icon={<TrendingUp size={14} />}
            color={item.health_score !== null && item.health_score >= 85 ? "emerald" : item.health_score !== null && item.health_score >= 60 ? "slate" : "rose"}
          />
          <ScoreCard label="风险等级" value={item.risk_level ?? "—"} icon={<ShieldAlert size={14} />} />
          <ScoreCard label="分析时间" value={formatDate(item.created_at)} />
        </div>

        {/* No Result Data */}
        {!result && (
          <div className="flex flex-col items-center gap-3 py-12 text-center">
            <History size={40} className="text-slate-600" />
            <p className="text-slate-400">该记录未保存完整分析结果</p>
          </div>
        )}

        {/* Architecture */}
        {result?.architecture && (
          <DetailSection title="架构分析">
            <div className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
              <DetailRow label="复杂度" value={result.architecture.complexity} />
              <DetailRow label="组件数量" value={result.architecture.components} />
              <DetailRow label="架构风格" value={result.architecture.architectureStyle} />
              <DetailRow label="可维护性" value={result.architecture.maintainability} />
            </div>
            {result.architecture.techStack?.length > 0 && (
              <div className="mt-3">
                <p className="text-xs text-slate-500 mb-2">技术栈</p>
                <div className="flex flex-wrap gap-1.5">
                  {result.architecture.techStack.map((t) => (
                    <Badge key={t} variant="primary">{t}</Badge>
                  ))}
                </div>
              </div>
            )}
            {result.architecture.summary && (
              <p className="mt-3 text-xs text-slate-400 leading-relaxed">{result.architecture.summary}</p>
            )}
          </DetailSection>
        )}

        {/* Quality */}
        {result?.quality && (
          <DetailSection title="代码质量">
            <div className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
              <DetailRow label="健康分" value={result.quality.healthScore} suffix=" / 100" />
              <DetailRow label="测试覆盖率" value={result.quality.testCoverage} suffix="%" />
              <DetailRow label="代码质量复杂度" value={result.quality.qualityComplexity} />
              <DetailRow label="可维护性" value={result.quality.qualityMaintainability} />
            </div>
          </DetailSection>
        )}

        {/* Dependency */}
        {result?.dependency && (
          <DetailSection title="依赖风险">
            <div className="flex items-center gap-6 text-sm">
              <div className="text-center">
                <p className="text-2xl font-bold text-rose-400">{result.dependency.high}</p>
                <p className="text-[10px] text-slate-500 uppercase tracking-widest mt-1">高风险</p>
              </div>
              <div className="text-center">
                <p className="text-2xl font-bold text-purple-400">{result.dependency.medium}</p>
                <p className="text-[10px] text-slate-500 uppercase tracking-widest mt-1">中风险</p>
              </div>
              <div className="text-center">
                <p className="text-2xl font-bold text-emerald-400">{result.dependency.low}</p>
                <p className="text-[10px] text-slate-500 uppercase tracking-widest mt-1">低风险</p>
              </div>
              <div className="text-center">
                <p className="text-2xl font-bold text-slate-300">{result.dependency.total}</p>
                <p className="text-[10px] text-slate-500 uppercase tracking-widest mt-1">总依赖</p>
              </div>
            </div>
            {result.dependency.deps?.slice(0, 5).map((dep: { name: string; version?: string; risk?: string; riskLevel?: string }) => (
              <div key={dep.name} className="flex items-center justify-between py-2 border-b border-white/5 last:border-0">
                <span className="text-xs font-mono text-slate-300">{dep.name}</span>
                <div className="flex items-center gap-2">
                  {dep.risk && (
                    <Badge variant={dep.riskLevel === "high" ? "destructive" : dep.riskLevel === "medium" ? "secondary" : "outline"}>
                      {dep.risk}
                    </Badge>
                  )}
                  {dep.version && <span className="text-xs text-slate-500">{dep.version}</span>}
                </div>
              </div>
            ))}
          </DetailSection>
        )}

        {/* Suggestions */}
        {(() => {
          const suggestions = result?.suggestion?.suggestions ?? result?.suggestions ?? [];
          if (suggestions.length === 0) return null;
          return (
            <DetailSection title="优化建议">
              <div className="space-y-3">
                {suggestions.map((s: { id: number; priority: string; title: string; description: string; category?: string; source?: string }) => (
                <div key={s.id} className="p-3 rounded-lg bg-[#0a0e14] border border-white/5">
                  <div className="flex items-start gap-2">
                    <div className="mt-0.5">
                      {s.priority === "high" ? (
                        <XCircle size={14} className="text-rose-400" />
                      ) : s.priority === "medium" ? (
                        <AlertTriangle size={14} className="text-purple-400" />
                      ) : (
                        <CheckCircle size={14} className="text-emerald-400" />
                      )}
                    </div>
                    <div>
                      <p className="text-sm font-medium text-[#dfe2eb]">{s.title}</p>
                      <p className="text-xs text-slate-400 mt-1 leading-relaxed">{s.description}</p>
                      <div className="flex items-center gap-2 mt-2">
                        <Badge variant={s.priority === "high" ? "destructive" : s.priority === "medium" ? "secondary" : "outline"} className="text-[10px]">
                          {s.priority}
                        </Badge>
                        {s.category && <span className="text-[10px] text-slate-500">{s.category}</span>}
                        {s.source && <span className="text-[10px] text-slate-500">{s.source}</span>}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </DetailSection>
          );
        })()}
      </div>
    </Modal>
  );
}

function ScoreCard({ label, value, suffix = "", icon, color = "blue" }: {
  label: string;
  value: string | number | null;
  suffix?: string;
  icon?: React.ReactNode;
  color?: "blue" | "emerald" | "rose" | "purple" | "slate";
}) {
  const colorMap: Record<string, string> = {
    blue: "text-blue-400",
    emerald: "text-emerald-400",
    rose: "text-rose-400",
    purple: "text-purple-400",
    slate: "text-slate-300",
  };
  return (
    <div className="flex flex-col gap-1 p-3 rounded-lg bg-[#0a0e14] border border-white/5">
      <span className="text-[10px] text-slate-500 uppercase tracking-widest">{label}</span>
      <div className="flex items-center gap-1.5">
        {icon && <span className={colorMap[color]}>{icon}</span>}
        <span className={`text-lg font-bold ${colorMap[color]}`}>
          {value ?? "—"}{suffix && value !== "—" ? suffix : ""}
        </span>
      </div>
    </div>
  );
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-3">
      <h4 className="text-xs font-bold uppercase tracking-widest text-slate-500 border-b border-white/5 pb-2">{title}</h4>
      {children}
    </div>
  );
}

function DetailRow({ label, value, suffix }: { label: string; value: string | number | null | undefined; suffix?: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-slate-500">{label}</span>
      <span className="text-sm font-medium text-[#dfe2eb]">{value ?? "—"}{suffix ?? ""}</span>
    </div>
  );
}

export default function HistoryPage() {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [stats, setStats] = useState<HistoryStats | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<HistoryItem | null>(null);
  const [detailItem, setDetailItem] = useState<HistoryItem | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchHistory = useCallback(
    async (p: number, q: string) => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams({
          page: String(p),
          page_size: String(PAGE_SIZE),
          ...(q ? { search: q } : {}),
        });
        const res = await fetch(`/api/history?${params}`);
        if (!res.ok) throw new Error(`请求失败: ${res.status}`);
        const data: HistoryListResponse = await res.json();
        setItems(data.items);
        setStats(data.stats);
        setTotal(data.total);
        setPage(data.page);
      } catch (e) {
        setError(e instanceof Error ? e.message : "加载失败");
      } finally {
        setLoading(false);
      }
    },
    []
  );

  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => {
    fetchHistory(1, search);
    // 故意只监听 search，初始化和分页在 useCallback 中处理
  }, [search]);
  /* eslint-enable react-hooks/exhaustive-deps */

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setSearch(searchInput);
    setPage(1);
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    const id = deleteTarget.id;
    setDeletingId(id);
    setDeleteTarget(null);
    try {
      const res = await fetch(`/api/history/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("删除失败");
      setItems((prev) => prev.filter((item) => item.id !== id));
      setTotal((prev) => prev - 1);
      setStats((prev) =>
        prev
          ? {
              ...prev,
              total_scans: prev.total_scans - 1,
            }
          : prev
      );
    } catch {
      alert("删除失败，请重试");
    } finally {
      setDeletingId(null);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      className="space-y-8"
    >
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
        <div>
          <h1 className="text-4xl font-black tracking-tighter mb-2">
            分析历史记录
          </h1>
          <p className="text-slate-400">
            深度审计资产库：追溯代码演进与安全态势
          </p>
        </div>
        <form onSubmit={handleSearch} className="flex gap-4">
          <div className="relative group">
            <input
              type="text"
              placeholder="搜索存储库..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              className="bg-[#1c2026] border-none text-[#dfe2eb] px-4 py-2 pl-10 rounded-sm focus:ring-1 focus:ring-blue-500 w-64 transition-all text-sm"
            />
            <Search
              className="absolute left-3 top-2.5 text-slate-500"
              size={16}
            />
          </div>
          <button
            type="submit"
            className="bg-[#1c2026] p-2 px-4 rounded-sm hover:bg-[#31353c] transition-colors flex items-center gap-2 text-sm"
          >
            <Filter size={16} />
            <span>筛选</span>
          </button>
        </form>
      </div>

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <GlassCard className="p-6 flex flex-col justify-between">
            <span className="text-slate-500 text-[10px] uppercase tracking-widest mb-4">
              扫描总计
            </span>
            <div className="text-4xl font-bold text-blue-400">
              {stats.total_scans}
            </div>
            <div className="mt-4 flex items-center gap-1 text-emerald-400 text-xs">
              <TrendingUp size={12} />
              <span>历史累计</span>
            </div>
          </GlassCard>
          <GlassCard className="p-6 flex flex-col justify-between">
            <span className="text-slate-500 text-[10px] uppercase tracking-widest mb-4">
              平均健康得分
            </span>
            <div className="text-4xl font-bold text-emerald-400">
              {stats.avg_health_score}
            </div>
            <div className="mt-4 h-1 bg-[#1c2026] rounded-full overflow-hidden">
              <div
                className="h-full bg-emerald-400"
                style={{ width: `${Math.min(100, stats.avg_health_score)}%` }}
              />
            </div>
          </GlassCard>
          <GlassCard
            className="p-6 col-span-2 relative overflow-hidden"
          >
            <div className="relative z-10">
              <span className="text-slate-500 text-[10px] uppercase tracking-widest mb-4">
                安全概览
              </span>
              <div className="flex items-end gap-6 mt-2">
                <div>
                  <div className="text-3xl font-bold text-rose-400">
                    {String(stats.high_risk_count).padStart(2, "0")}
                  </div>
                  <div className="text-[10px] text-slate-500 uppercase mt-1">
                    高风险
                  </div>
                </div>
                <div className="h-10 w-[1px] bg-white/10" />
                <div>
                  <div className="text-3xl font-bold text-purple-400">
                    {String(stats.medium_risk_count).padStart(2, "0")}
                  </div>
                  <div className="text-[10px] text-slate-500 uppercase mt-1">
                    中风险
                  </div>
                </div>
              </div>
            </div>
            <ShieldAlert
              className="absolute right-0 bottom-0 opacity-10"
              style={{ fontSize: 120 }}
            />
          </GlassCard>
        </div>
      )}

      {/* Loading / Error / Empty States */}
      {loading && (
        <div className="flex items-center justify-center py-20">
          <Loader2 size={32} className="animate-spin text-blue-400" />
          <span className="ml-3 text-slate-400">加载中...</span>
        </div>
      )}

      {error && !loading && (
        <div className="text-center py-20">
          <p className="text-rose-400 mb-4">{error}</p>
          <button
            onClick={() => fetchHistory(page, search)}
            className="px-4 py-2 bg-[#31353c] rounded-sm hover:bg-[#414754] transition-colors text-sm"
          >
            重试
          </button>
        </div>
      )}

      {!loading && !error && items.length === 0 && (
        <div className="text-center py-20 space-y-4">
          <History size={48} className="mx-auto text-slate-600" />
          <p className="text-slate-400">暂无分析记录</p>
          <p className="text-slate-600 text-sm">
            {search
              ? `没有找到包含 "${search}" 的记录`
              : "在首页分析一个 GitHub 仓库开始使用"}
          </p>
        </div>
      )}

      {/* History List */}
      {!loading && !error && items.length > 0 && (
        <div className="space-y-4">
          {items.map((item) => (
            <GlassCard
              key={item.id}
              className={cn(
                "group border-l-2",
                item.border_color ?? "border-blue-400"
              )}
            >
              <div className="flex flex-col md:flex-row items-center p-6 gap-6">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3 mb-1">
                    <Code2 className="text-xl text-blue-400" size={20} />
                    <h3 className="text-lg font-bold tracking-tight truncate">
                      {item.repo_name}
                    </h3>
                    {item.branch && (
                      <Badge variant="primary">
                        {item.branch === "main" ? "主分支" : item.branch}
                      </Badge>
                    )}
                    <Badge variant="outline" className="font-mono text-[10px]">
                      {item.repo_url}
                    </Badge>
                  </div>
                  <div className="flex items-center gap-4 text-xs text-slate-500">
                    <span className="flex items-center gap-1">
                      <History size={14} /> {formatDate(item.created_at)}
                    </span>
                    <span className="flex items-center gap-1">
                      <RefreshCw size={14} /> {formatRelativeTime(item.created_at)} 完成
                    </span>
                  </div>
                </div>

                <div className="flex flex-wrap md:flex-nowrap gap-8 items-center">
                  <div className="text-center">
                    <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">
                      架构健康度
                    </div>
                    <div
                      className={cn(
                        "text-xl font-bold",
                        (item.health_score ?? 0) >= 85
                          ? "text-emerald-400"
                          : (item.health_score ?? 0) >= 60
                          ? "text-slate-200"
                          : "text-rose-400"
                      )}
                    >
                      {healthLabel(item.health_score)}
                    </div>
                  </div>
                  <div className="text-center">
                    <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">
                      代码质量
                    </div>
                    <div className="text-xl font-bold">
                      {item.quality_score ?? "—"}
                    </div>
                  </div>
                  <div className="text-center min-w-[100px]">
                    <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">
                      安全风险
                    </div>
                    <div className="flex items-center justify-center gap-1">
                      <span
                        className={cn(
                          "w-2 h-2 rounded-full",
                          item.risk_level_bg ?? "bg-slate-400"
                        )}
                      />
                      <span
                        className={cn(
                          "text-sm font-bold",
                          item.risk_level_color ?? "text-slate-400"
                        )}
                      >
                        {item.risk_level ?? "—"}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="flex gap-2">
                  <button
                    onClick={() => setDetailItem(item)}
                    className="px-4 py-2 bg-[#31353c] hover:bg-blue-500/20 hover:text-blue-400 transition-all text-xs font-bold uppercase tracking-widest rounded-sm border border-white/5"
                  >
                    查看详情
                  </button>
                  <button
                    onClick={() => setDeleteTarget(item)}
                    disabled={deletingId === item.id}
                    className="p-2 bg-[#31353c] hover:bg-rose-500/20 hover:text-rose-400 transition-all text-[#dfe2eb] rounded-sm border border-white/5 disabled:opacity-50"
                    title="删除"
                  >
                    {deletingId === item.id ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <Trash2 size={14} />
                    )}
                  </button>
                </div>
              </div>
            </GlassCard>
          ))}
        </div>
      )}

      {/* Pagination */}
      {!loading && !error && total > 0 && (
        <div className="mt-12 flex items-center justify-between border-t border-white/5 pt-8">
          <span className="text-xs text-slate-500 uppercase tracking-widest">
            显示 {total} 条结果中的 {(page - 1) * PAGE_SIZE + 1}–
            {Math.min(page * PAGE_SIZE, total)} 条
          </span>
          <div className="flex gap-1">
            <button
              onClick={() => {
                const p = page - 1;
                setPage(p);
                fetchHistory(p, search);
              }}
              disabled={page <= 1}
              className="w-8 h-8 flex items-center justify-center rounded-sm bg-[#31353c] text-slate-500 hover:text-blue-400 transition-all disabled:opacity-30"
            >
              <ChevronRight className="rotate-180" size={16} />
            </button>
            {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
              const pageNum = i + 1;
              return (
                <button
                  key={pageNum}
                  onClick={() => {
                    setPage(pageNum);
                    fetchHistory(pageNum, search);
                  }}
                  className={cn(
                    "w-8 h-8 flex items-center justify-center rounded-sm text-xs font-bold transition-all",
                    page === pageNum
                      ? "bg-blue-500 text-blue-950"
                      : "bg-[#31353c] text-slate-300 hover:bg-[#414754]"
                  )}
                >
                  {pageNum}
                </button>
              );
            })}
            <button
              onClick={() => {
                const p = page + 1;
                setPage(p);
                fetchHistory(p, search);
              }}
              disabled={page >= totalPages}
              className="w-8 h-8 flex items-center justify-center rounded-sm bg-[#31353c] text-slate-500 hover:text-blue-400 transition-all disabled:opacity-30"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {deleteTarget && (
        <Modal
          open
          onClose={() => setDeleteTarget(null)}
          title="删除分析记录"
          description={`确定要删除 "${deleteTarget.repo_name}" 的分析记录吗？此操作不可撤销。`}
        >
          <div className="flex flex-col gap-6">
            <div className="flex items-start gap-3 p-4 rounded-lg bg-rose-500/10 border border-rose-500/20">
              <AlertTriangle className="text-rose-400 shrink-0 mt-0.5" size={18} />
              <div>
                <p className="text-sm text-rose-300">此操作不可撤销</p>
                <p className="text-xs text-rose-400/60 mt-1">
                  删除后，与该记录关联的分析数据将永久消失。
                </p>
              </div>
            </div>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setDeleteTarget(null)}
                className="px-5 py-2 rounded-sm border border-white/10 text-slate-300 hover:bg-white/5 transition-all text-sm font-medium"
              >
                取消
              </button>
              <button
                onClick={handleDelete}
                disabled={!!deletingId}
                className="px-5 py-2 rounded-sm bg-rose-500/20 border border-rose-500/30 text-rose-400 hover:bg-rose-500/30 transition-all text-sm font-bold flex items-center gap-2 disabled:opacity-50"
              >
                {deletingId ? <Loader2 size={14} className="animate-spin" /> : null}
                确认删除
              </button>
            </div>
          </div>
        </Modal>
      )}

      {/* Detail Modal */}
      {detailItem && (
        <DetailModal item={detailItem} onClose={() => setDetailItem(null)} />
      )}
    </motion.div>
  );
}
