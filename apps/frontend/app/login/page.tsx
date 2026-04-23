"use client";

import { signIn } from "next-auth/react";
import { Github, Shield } from "lucide-react";

export default function LoginPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0d1117]">
      <div className="w-full max-w-md p-8">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold tracking-tighter text-blue-400 mb-2">
            GitIntel
          </h1>
          <p className="text-slate-400 text-sm">
            使用 GitHub 账号登录，开始 AI 仓库分析
          </p>
        </div>

        <div className="bg-[#161b22] border border-white/10 rounded-lg p-8">
          <button
            onClick={() => signIn("github", { callbackUrl: "/" })}
            className="w-full flex items-center justify-center gap-3 px-6 py-3 bg-white text-[#24292f] font-semibold rounded-md hover:bg-slate-100 transition-all text-sm"
          >
            <Github size={20} />
            使用 GitHub 登录
          </button>

          <div className="mt-6 p-4 bg-blue-500/5 border border-blue-500/20 rounded-lg">
            <div className="flex items-center gap-2 text-blue-400 text-xs font-medium mb-2">
              <Shield size={14} />
              需要以下权限
            </div>
            <ul className="text-xs text-slate-400 space-y-1">
              <li className="flex items-center gap-2">
                <span className="text-emerald-400">✓</span> 读取你的公开资料（用户名、头像等）
              </li>
              <li className="flex items-center gap-2">
                <span className="text-emerald-400">✓</span> 读写你的仓库（用于创建 PR 和分支）
              </li>
            </ul>
          </div>

          <p className="text-xs text-slate-500 text-center mt-6">
            登录即表示你同意我们的服务条款。我们仅获取必要的 GitHub 权限用于创建 PR。
          </p>
        </div>

        <p className="text-xs text-slate-600 text-center mt-4">
          还没有 GitHub OAuth App？{" "}
          <a
            href="https://github.com/settings/applications/new"
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-500 hover:underline"
          >
            点击申请
          </a>
        </p>
      </div>
    </div>
  );
}
