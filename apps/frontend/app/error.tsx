"use client";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center space-y-4 p-8">
      <div className="text-6xl font-bold text-red-500">错误</div>
      <h1 className="text-2xl font-semibold text-slate-200">出错了</h1>
      <p className="text-slate-500 max-w-md">{error.message || "发生了未知错误"}</p>
      <button
        onClick={reset}
        className="mt-4 px-6 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-xl transition-colors"
      >
        重试
      </button>
    </div>
  );
}
