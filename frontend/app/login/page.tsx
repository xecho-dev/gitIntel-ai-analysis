"use client";

import { signIn } from "next-auth/react";
import { Github } from "lucide-react";

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

          <p className="text-xs text-slate-500 text-center mt-6">
            登录即表示你同意我们的服务条款。我们仅获取你的公开 GitHub 信息。
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
