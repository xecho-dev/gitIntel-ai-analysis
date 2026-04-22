"use client";

import React, { useState, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { Search, Zap, Loader2 } from "lucide-react";
import { useAppStore, AgentEventData } from "@/store/useAppStore";
import { analyzeRepo } from "@/lib/api";

export const AnalyzeInput = ({ userId }: { userId: string }) => {
  const router = useRouter();
  const { data: session } = useSession();
  const [localRepoUrl, setLocalRepoUrl] = useState("https://github.com/facebook/react.git");
  const isAnalyzing = useAppStore((s) => s.isAnalyzing);
  const error = useAppStore((s) => s.error);

  // 检查是否有待恢复的分析任务（OAuth 授权后）
  useEffect(() => {
    const pendingRepoUrl = sessionStorage.getItem("gitintel_pending_repo_url");
    const pendingBranch = sessionStorage.getItem("gitintel_pending_branch");

    if (pendingRepoUrl) {
      // 清除存储
      sessionStorage.removeItem("gitintel_pending_repo_url");
      sessionStorage.removeItem("gitintel_pending_branch");

      // 设置仓库地址
      setLocalRepoUrl(pendingRepoUrl);

      // 延迟一点触发分析，等待 OAuth 状态同步
      const timer = setTimeout(() => {
        const store = useAppStore.getState();
        if (session?.user && !store.isAnalyzing) {
          // 直接调用 handleAnalyze 逻辑
          const repoUrl = pendingRepoUrl;
          store.reset();
          store.setError(null);
          store.setIsAnalyzing(true);
          store.setRepoUrl(repoUrl);

          analyzeRepo(repoUrl, pendingBranch || undefined, userId, (data: unknown) => {
            const event = data as { agent?: string; type?: string };
            if (event?.agent) {
              store.setActiveAgent(event.agent);
            }
            if (event?.type === "error") {
              const msg = (data as { message?: string }).message ?? "分析失败，请检查仓库地址或 Token 权限";
              store.setError(msg);
              store.setIsAnalyzing(false);
              store.setActiveAgent(null);
              return;
            }
            store.pushAgentEvent(data as AgentEventData);
          }).catch((err) => {
            store.setError(err instanceof Error ? err.message : "分析失败");
          }).finally(() => {
            store.setIsAnalyzing(false);
            store.setActiveAgent(null);
          });
        }
      }, 500);

      return () => clearTimeout(timer);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  const handleAnalyze = useCallback(async () => {
    // 未登录重定向到登录页
    if (!session?.user) {
      router.push("/login");
      return;
    }

    const store = useAppStore.getState();
    if (!localRepoUrl.trim()) {
      store.setError("请输入仓库地址");
      return;
    }
    const repoUrl = localRepoUrl;

    // 清空上一次的分析结果
    store.reset();
    store.setError(null);
    store.setIsAnalyzing(true);
    store.setRepoUrl(repoUrl);

    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      await analyzeRepo(repoUrl, undefined, userId, (data: any) => {
        const event = data as { agent?: string; type?: string };
        if (event?.agent) {
          store.setActiveAgent(event.agent);
        }
        if (event?.type === "error") {
          // 后端返回的权限 / 访问错误，直接显示给用户
          const msg = (data as { message?: string }).message ?? "分析失败，请检查仓库地址或 Token 权限";
          store.setError(msg);
          store.setIsAnalyzing(false);
          store.setActiveAgent(null);
          return;
        }
        store.pushAgentEvent(data);
      });
    } catch (err) {
      useAppStore.getState().setError(err instanceof Error ? err.message : "分析失败");
    } finally {
      store.setIsAnalyzing(false);
      store.setActiveAgent(null);
    }
  }, [localRepoUrl, userId, session, router]);

  return (
    <div className="max-w-3xl mx-auto mt-8 space-y-2">
      <div className="flex gap-3 p-1.5 bg-[#1c2026] rounded-xl border border-white/5 shadow-2xl">
        <div className="flex-1 flex items-center px-4 gap-3">
          <Search className="text-slate-500" size={18} />
          <input
            type="text"
            value={localRepoUrl}
            onChange={(e) => setLocalRepoUrl(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAnalyze()}
            placeholder="https://github.com/facebook/react"
            className="bg-transparent border-none text-[#dfe2eb] w-full focus:ring-0 placeholder:text-slate-600 text-sm"
          />
        </div>
        <button
          onClick={handleAnalyze}
          disabled={isAnalyzing}
          className="bg-blue-400 text-blue-950 px-8 py-2.5 font-black text-sm rounded-lg hover:brightness-110 transition-all flex items-center gap-2 disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {isAnalyzing ? (
            <>
              <Loader2 size={16} className="animate-spin" />
              <span>分析中...</span>
            </>
          ) : (
            <>
              <span>立即分析</span>
              <Zap size={16} fill="currentColor" />
            </>
          )}
        </button>
      </div>

      {error && (
        <div className="px-4 py-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-400 text-sm">
          {error}
        </div>
      )}
    </div>
  );
};
