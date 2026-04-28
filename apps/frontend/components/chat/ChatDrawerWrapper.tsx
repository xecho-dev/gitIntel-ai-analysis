"use client";

import { useEffect } from "react";
import { useAppStore } from "@/store/useAppStore";
import { ChatDrawer } from "@/components/chat/ChatDrawer";
import { MessageSquare } from "lucide-react";

export function ChatDrawerWrapper() {
  const { isChatDrawerOpen, setChatDrawerOpen } = useAppStore();

  // 打开抽屉时锁定背景滚动
  useEffect(() => {
    if (isChatDrawerOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [isChatDrawerOpen]);

  return (
    <>
      {/* 毛玻璃蒙层 */}
      {isChatDrawerOpen && (
        <div
          className="fixed inset-0 z-[9997] bg-black/40 backdrop-blur-sm"
          onClick={() => setChatDrawerOpen(false)}
        />
      )}

      {/* 浮动入口按钮 — 固定在右下角 */}
      {!isChatDrawerOpen && (
        <button
          onClick={() => setChatDrawerOpen(true)}
          className="fixed bottom-6 right-6 z-[9998] w-14 h-14 bg-blue-500 hover:bg-blue-600 text-white rounded-full shadow-lg shadow-blue-500/30 flex items-center justify-center transition-all duration-200 hover:scale-105 active:scale-95"
          title="打开 AI 助手"
        >
          <MessageSquare size={22} />
        </button>
      )}

      {/* 抽屉内容 */}
      {isChatDrawerOpen && (
        <ChatDrawer onClose={() => setChatDrawerOpen(false)} />
      )}
    </>
  );
}
