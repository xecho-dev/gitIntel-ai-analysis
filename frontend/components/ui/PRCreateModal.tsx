"use client";

import React, { useState, useCallback, useEffect } from "react";
import dynamic from "next/dynamic";
import { X, Rocket, Loader2, CheckCircle2, AlertCircle, GitPullRequest, ExternalLink, Sparkles, FileCode, GitBranch } from "lucide-react";
import { cn } from "@/lib/utils";

// Monaco DiffEditor 必须动态导入，禁用 SSR
const DiffEditor = dynamic(
  () => import("@monaco-editor/react").then((mod) => ({ default: mod.DiffEditor })),
  { ssr: false }
);

// ─── Types ──────────────────────────────────────────────────────────

export interface CodeFix {
  file: string;
  type: "replace" | "insert" | "delete";
  original: string;
  updated: string;
  reason?: string;
  description: string;
}

interface PRCreateModalProps {
  isOpen: boolean;
  onClose: () => void;
  suggestion: CodeFix | null;
  repoUrl: string;
  branch: string;
}

type ModalState = "generating" | "preview" | "creating" | "success" | "error";

export const PRCreateModal: React.FC<PRCreateModalProps> = ({
  isOpen,
  onClose,
  suggestion,
  repoUrl,
  branch,
}) => {
  const [modalState, setModalState] = useState<ModalState>("generating");
  const [fixes, setFixes] = useState<CodeFix[]>([]);
  const [errorMsg, setErrorMsg] = useState("");
  const [prResult, setPrResult] = useState<{ url: string; number: number; title: string; is_fork: boolean; fork_url: string } | null>(null);
  const [commitMessage, setCommitMessage] = useState("");
  const [editedValues, setEditedValues] = useState<string[]>([]);

  // 弹窗打开时自动触发生成
  useEffect(() => {
    if (isOpen && suggestion) {
      generateFixes();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  const generateFixes = useCallback(async () => {
    if (!suggestion) return;

    setModalState("generating");
    setErrorMsg("");
    setFixes([]);
    setPrResult(null);
    setCommitMessage("");
    setEditedValues([]);

    try {
      const res = await fetch("/api/pr/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          repo_url: repoUrl,
          branch: branch,
          suggestions: [
            {
              id: 1,
              type: suggestion.reason?.split(":")[0] || "general",
              title: suggestion.reason?.split("\n")[0] || "代码优化",
              description: suggestion.description?.split("\n")[1] || "",
              priority: "high",
            },
          ],
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: "生成失败" }));
        throw new Error(err.error ?? "生成失败");
      }

      const data = await res.json();
      if (data.success && data.fixes?.length > 0) {
        setFixes(data.fixes);
        setEditedValues(data.fixes.map((f) => f.updated));
        setModalState("preview");
      } else {
        // 如果没有生成修改，创建一个默认修改
        const defaultFixes: CodeFix[] = [
          {
            file: suggestion.file || "src/suggested_fix.ts",
            type: "replace",
            original: suggestion.original || "",
            updated: suggestion.updated || "",
            description: suggestion.description || "",
            reason: suggestion.reason || "基于优化建议的代码修改",
          },
        ];
        setFixes(defaultFixes);
        setEditedValues(defaultFixes.map((f) => f.updated));
        setModalState("preview");
      }
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "生成代码修改失败");
      setModalState("error");
    }
  }, [repoUrl, branch, suggestion]);

  const handleCreatePR = useCallback(async () => {
    if (fixes.length === 0) return;

    setModalState("creating");
    setErrorMsg("");

    const finalFixes = fixes.map((fix, idx) => ({
      ...fix,
      updated: editedValues[idx] ?? fix.updated,
    }));

    // 与输入框 placeholder 一致：未输入时用建议首行；用于 commit 与 PR 标题（GitHub 列表显示的是 PR 标题）
    const resolvedCommit =
      commitMessage.trim() || suggestion?.reason?.split("\n")[0] || undefined;

    try {
      const res = await fetch("/api/pr/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          repo_url: repoUrl,
          branch: branch,
          fixes: finalFixes,
          commit_message: resolvedCommit,
          pr_title: resolvedCommit,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: "创建 PR 失败" }));
        throw new Error(err.error ?? "创建 PR 失败");
      }

      const data = await res.json();
      setPrResult({
        url: data.pr_url,
        number: data.pr_number,
        title: data.pr_title,
        is_fork: data.is_fork ?? false,
        fork_url: data.fork_url ?? "",
      });
      setModalState("success");
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "创建 PR 失败");
      setModalState("error");
    }
  }, [repoUrl, branch, fixes, editedValues, commitMessage, suggestion]);

  const getLanguage = (file: string): string => {
    if (file.endsWith(".py")) return "python";
    if (file.endsWith(".ts") || file.endsWith(".tsx")) return "typescript";
    if (file.endsWith(".js") || file.endsWith(".jsx")) return "javascript";
    if (file.endsWith(".json")) return "json";
    if (file.endsWith(".md")) return "markdown";
    if (file.endsWith(".css")) return "css";
    if (file.endsWith(".html")) return "html";
    if (file.endsWith(".go")) return "go";
    if (file.endsWith(".java")) return "java";
    if (file.endsWith(".rs")) return "rust";
    return "plaintext";
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div
        className={cn(
          "relative w-[90vw] max-w-[1000px] max-h-[88vh] rounded-2xl overflow-hidden",
          "flex flex-col",
          "bg-[#0f1117] border border-white/10",
          "shadow-2xl shadow-black/50"
        )}
      >
        {/* ── Header ─────────────────────────────────────────── */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/8 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-500/30 to-purple-500/30 flex items-center justify-center">
              <Rocket size={18} className="text-blue-400" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-white tracking-tight">
                {modalState === "success" ? "PR 创建成功" : "AI 自动生成 PR"}
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">
                {modalState === "success"
                  ? `PR #${prResult?.number} 已创建`
                  : suggestion?.description?.split("\n")[0] || "基于优化建议生成代码修改"}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-slate-400 hover:text-white hover:bg-white/5 transition-all"
          >
            <X size={16} />
          </button>
        </div>

        {/* ── Progress Steps ───────────────────────────────── */}
        <div className="px-6 py-3 border-b border-white/5 shrink-0">
          <div className="flex items-center gap-1">
            {/* Step 1: Generate */}
            <div
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
                modalState === "generating"
                  ? "bg-blue-500/20 text-blue-400"
                  : ["preview", "creating", "success"].includes(modalState)
                    ? "bg-emerald-500/20 text-emerald-400"
                    : "text-slate-500"
              )}
            >
              {["preview", "creating", "success"].includes(modalState) ? (
                <CheckCircle2 size={14} />
              ) : modalState === "generating" ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Sparkles size={14} />
              )}
              <span>生成修改</span>
            </div>

            <div
              className={cn(
                "h-[2px] flex-1 mx-2 rounded-full transition-colors",
                ["preview", "creating", "success"].includes(modalState)
                  ? "bg-emerald-400"
                  : "bg-white/10"
              )}
            />

            {/* Step 2: Preview */}
            <div
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
                modalState === "preview"
                  ? "bg-blue-500/20 text-blue-400"
                  : ["creating", "success"].includes(modalState)
                    ? "bg-emerald-500/20 text-emerald-400"
                    : "text-slate-500"
              )}
            >
              {["creating", "success"].includes(modalState) ? (
                <CheckCircle2 size={14} />
              ) : (
                <FileCode size={14} />
              )}
              <span>预览 Diff</span>
            </div>

            <div
              className={cn(
                "h-[2px] flex-1 mx-2 rounded-full transition-colors",
                ["creating", "success"].includes(modalState)
                  ? "bg-emerald-400"
                  : "bg-white/10"
              )}
            />

            {/* Step 3: Create */}
            <div
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
                modalState === "creating"
                  ? "bg-blue-500/20 text-blue-400 animate-pulse"
                  : modalState === "success"
                    ? "bg-emerald-500/20 text-emerald-400"
                    : "text-slate-500"
              )}
            >
              {modalState === "creating" ? (
                <Loader2 size={14} className="animate-spin" />
              ) : modalState === "success" ? (
                <CheckCircle2 size={14} />
              ) : (
                <GitPullRequest size={14} />
              )}
              <span>创建 PR</span>
            </div>
          </div>
        </div>

        {/* ── Body ─────────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto min-h-0 p-6">
          {/* Generating */}
          {modalState === "generating" && (
            <div className="flex flex-col items-center justify-center py-16 gap-5">
              <div className="relative">
                <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-blue-500/20 to-purple-500/20 flex items-center justify-center">
                  <Loader2 size={36} className="text-blue-400 animate-spin" />
                </div>
                <div className="absolute -bottom-1 -right-1 w-6 h-6 rounded-full bg-blue-500/30 flex items-center justify-center">
                  <Sparkles size={12} className="text-blue-400" />
                </div>
              </div>
              <div className="text-center">
                <p className="text-base text-white font-medium">正在分析代码...</p>
                <p className="text-sm text-slate-500 mt-2 max-w-md">
                  基于优化建议「{suggestion?.reason?.split("\n")[0]}」生成代码修改方案
                </p>
              </div>
            </div>
          )}

          {/* Preview */}
          {modalState === "preview" && (
            <div className="space-y-4">
              {/* Suggestion context */}
              {suggestion?.reason && (
                <div className="p-4 bg-blue-500/10 border border-blue-500/20 rounded-xl">
                  <div className="flex items-start gap-3">
                    <div className="w-8 h-8 rounded-lg bg-blue-500/20 flex items-center justify-center shrink-0 mt-0.5">
                      <Sparkles size={14} className="text-blue-400" />
                    </div>
                    <div>
                      <p className="text-sm text-blue-400 font-medium">
                        {suggestion.description.split("\n")[0]}
                      </p>
                      {suggestion.description.split("\n")[1] && (
                        <p className="text-xs text-slate-400 mt-1">
                          {suggestion.description.split("\n")[1]}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* Generated fixes */}
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <GitBranch size={14} className="text-emerald-400" />
                  <span className="text-sm text-slate-300 font-medium">
                    将生成 {fixes.length} 个代码修改
                  </span>
                </div>

                {/* 统一 commit message */}
                <div className="flex items-center gap-3 px-4 py-3 bg-white/[0.02] border border-white/5 rounded-xl">
                  <span className="text-xs text-slate-500 shrink-0">Commit:</span>
                  <input
                    type="text"
                    placeholder={suggestion?.reason?.split("\n")[0] || "描述此次修改内容..."}
                    value={commitMessage}
                    onChange={(e) => setCommitMessage(e.target.value)}
                    className="flex-1 bg-transparent text-sm text-slate-200 placeholder-slate-600 outline-none border-none"
                    maxLength={72}
                  />
                  <span className="text-xs text-slate-600">{commitMessage.length}/72</span>
                </div>

                {fixes.map((fix, idx) => (
                  <div
                    key={idx}
                    className="rounded-xl border border-white/5 overflow-hidden bg-[#1a1d27]"
                  >
                    {/* File header */}
                    <div className="flex items-center gap-3 px-4 py-3 border-b border-white/5">
                      <span
                        className={cn(
                          "w-6 h-6 rounded-md flex items-center justify-center text-xs font-bold",
                          fix.type === "delete"
                            ? "bg-red-500/20 text-red-400"
                            : fix.type === "insert"
                              ? "bg-emerald-500/20 text-emerald-400"
                              : "bg-blue-500/20 text-blue-400"
                        )}
                      >
                        {fix.type === "delete" ? "D" : fix.type === "insert" ? "A" : "M"}
                      </span>
                      <span className="text-sm font-mono text-slate-300 truncate flex-1">
                        {fix.file}
                      </span>
                      {/* {fix.reason && (
                        <span className="text-xs text-slate-500 truncate max-w-[200px]">
                          {fix.reason.slice(0, 50)}
                        </span>
                      )} */}
                    </div>

                    {/* Diff Editor - 左右分栏 */}
                    <div className="relative">
                      {/* Header tabs */}
                      <div className="flex border-b border-white/5">
                        <div className="flex-1 px-4 py-2 bg-red-500/5 border-r border-white/5">
                          <div className="flex items-center gap-2">
                            <span className="w-2 h-2 rounded-full bg-red-400" />
                            <span className="text-xs text-red-400 font-medium">旧代码</span>
                          </div>
                        </div>
                        <div className="flex-1 px-4 py-2 bg-emerald-500/5">
                          <div className="flex items-center gap-2">
                            <span className="w-2 h-2 rounded-full bg-emerald-400" />
                            <span className="text-xs text-emerald-400 font-medium">新代码</span>
                          </div>
                        </div>
                      </div>

                      {/* Monaco DiffEditor */}
                      <div className="h-[240px]">
                        <DiffEditor
                          height="240px"
                          language={getLanguage(fix.file)}
                          theme="vs-dark"
                          original={fix.original || "// 无原代码"}
                          modified={editedValues[idx] ?? fix.updated}
                          onMount={(editor) => {
                            // 左侧（original）设为只读
                            const originalEditor = editor.getOriginalEditor();
                            originalEditor.updateOptions({ readOnly: true });
                            // 监听右侧内容变化，同步到 editedValues
                            let skipFirst = true;
                            editor.getModifiedEditor().onDidChangeModelContent(() => {
                              if (skipFirst) {
                                skipFirst = false;
                                return;
                              }
                              setEditedValues((prev) => {
                                const next = [...prev];
                                next[idx] = editor.getModifiedEditor().getValue();
                                return next;
                              });
                            });
                          }}
                          options={{
                            readOnly: false,
                            minimap: { enabled: false },
                            scrollBeyondLastLine: false,
                            fontSize: 12,
                            lineNumbers: "on",
                            wordWrap: "on",
                            renderSideBySide: true,
                            renderLineHighlight: "none",
                            scrollbar: {
                              verticalScrollbarSize: 4,
                              horizontalScrollbarSize: 4,
                            },
                            padding: { top: 8, bottom: 8 },
                            diffWordWrap: "on",
                          }}
                        />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Creating */}
          {modalState === "creating" && (
            <div className="flex flex-col items-center justify-center py-16 gap-5">
              <div className="relative">
                <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-blue-500/20 to-purple-500/20 flex items-center justify-center">
                  <Loader2 size={36} className="text-blue-400 animate-spin" />
                </div>
                <div className="absolute -bottom-1 -right-1 w-6 h-6 rounded-full bg-emerald-500/30 flex items-center justify-center">
                  <GitBranch size={12} className="text-emerald-400" />
                </div>
              </div>
              <div className="text-center">
                <p className="text-base text-white font-medium">正在创建 Pull Request...</p>
                <p className="text-sm text-slate-500 mt-2">
                  创建分支 → 提交 {fixes.length} 个文件 → 创建 PR
                </p>
              </div>
            </div>
          )}

          {/* Success */}
          {modalState === "success" && (
            <div className="flex flex-col items-center justify-center py-12 gap-6">
              <div className="relative">
                <div className="w-20 h-20 rounded-full bg-gradient-to-br from-emerald-500/30 to-green-500/30 flex items-center justify-center">
                  <CheckCircle2 size={40} className="text-emerald-400" />
                </div>
                <div className="absolute -top-1 -right-1 w-7 h-7 rounded-full bg-emerald-500/30 flex items-center justify-center">
                  <GitPullRequest size={14} className="text-emerald-400" />
                </div>
              </div>
              <div className="text-center">
                <p className="text-lg text-white font-semibold">PR 创建成功！</p>
                <p className="text-sm text-slate-400 mt-2 max-w-md">{prResult?.title}</p>
                <p className="text-xs text-slate-600 mt-3">
                  PR #{prResult?.number} · {repoUrl}
                </p>
                {prResult?.is_fork && (
                  <div className="mt-3 px-3 py-2 bg-blue-500/10 border border-blue-500/20 rounded-lg">
                    <p className="text-xs text-blue-400">
                      此仓库为 Fork，代码已提交到你的仓库。
                    </p>
                    {prResult?.fork_url && (
                      <a
                        href={prResult.fork_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-blue-300 underline hover:text-blue-200"
                      >
                        查看你的 Fork →
                      </a>
                    )}
                  </div>
                )}
              </div>
              {prResult?.url && (
                <a
                  href={prResult.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 px-6 py-3 bg-blue-500 text-white text-sm font-medium rounded-xl hover:bg-blue-600 transition-all shadow-lg shadow-blue-500/20"
                >
                  <GitPullRequest size={18} />
                  在 GitHub 查看 PR
                  <ExternalLink size={14} />
                </a>
              )}
              <button
                onClick={onClose}
                className="px-4 py-2 text-xs rounded-lg bg-white/5 border border-white/10 text-slate-400 hover:text-white hover:bg-white/10 transition-all"
              >
                关闭
              </button>
            </div>
          )}

          {/* Error */}
          {modalState === "error" && (
            <div className="flex flex-col items-center justify-center py-12 gap-5">
              <div className="w-16 h-16 rounded-full bg-red-500/20 flex items-center justify-center">
                <AlertCircle size={28} className="text-red-400" />
              </div>
              <div className="text-center">
                <p className="text-sm text-red-400 font-medium">
                  {errorMsg.includes("generate") || errorMsg.includes("生成") || errorMsg.includes("Token")
                    ? "操作失败"
                    : "创建 PR 失败"}
                </p>
                <p className="text-xs text-slate-500 mt-2 max-w-md whitespace-pre-wrap">
                  {errorMsg}
                </p>
              </div>
              <div className="flex items-center gap-3">
                <button
                  onClick={
                    errorMsg.includes("generate") ||
                    errorMsg.includes("生成") ||
                    errorMsg.includes("Token")
                      ? generateFixes
                      : handleCreatePR
                  }
                  className="px-5 py-2 text-sm rounded-lg bg-blue-500 text-white font-medium hover:bg-blue-600 transition-all"
                >
                  重试
                </button>
                <button
                  onClick={onClose}
                  className="px-4 py-2 text-sm rounded-lg border border-white/10 text-slate-400 hover:text-white hover:bg-white/5 transition-all"
                >
                  取消
                </button>
              </div>
            </div>
          )}
        </div>

        {/* ── Footer ─────────────────────────────────────────── */}
        {modalState === "preview" && fixes.length > 0 && (
          <div className="px-6 py-4 border-t border-white/8 shrink-0 bg-[#0f1117]">
            <div className="flex items-center justify-between">
              <p className="text-xs text-slate-500">
                将创建一个新分支并提交 {fixes.length} 个文件修改
              </p>
              <div className="flex items-center gap-3">
                <button
                  onClick={onClose}
                  className="px-4 py-2 text-xs rounded-lg border border-white/10 text-slate-400 hover:text-white hover:bg-white/5 transition-all"
                >
                  取消
                </button>
                <button
                  onClick={handleCreatePR}
                  className="flex items-center gap-2 px-5 py-2 text-xs rounded-lg bg-blue-500 text-white font-medium hover:bg-blue-600 transition-all shadow-lg shadow-blue-500/20"
                >
                  <Rocket size={14} />
                  创建 PR
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
