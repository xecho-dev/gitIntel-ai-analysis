"use client";

import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center space-y-4">
      <div className="text-6xl font-bold text-slate-700">404</div>
      <h1 className="text-2xl font-semibold text-slate-200">页面未找到</h1>
      <p className="text-slate-500">抱歉，您访问的页面不存在。</p>
      <Link
        href="/"
        className="mt-4 px-6 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-xl transition-colors"
      >
        返回首页
      </Link>
    </div>
  );
}
