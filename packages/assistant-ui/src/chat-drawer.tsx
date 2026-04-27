"use client";

import * as React from "react";
import { AnimatePresence, motion } from "motion/react";
import { MessageCircle, X, GripVertical } from 'lucide-react';
import { cn } from "@gitintel/ui";
import { Thread } from "./thread";
import { useInitializeSession, useRAGRuntime } from "./runtime";
import { AssistantRuntimeProvider } from "@assistant-ui/react";

const MIN_WIDTH = 320;
const MAX_WIDTH = 800;

export const ChatDrawer = (): React.JSX.Element => {
  const [open, setOpen] = React.useState(false);
  const [drawerWidth, setDrawerWidth] = React.useState(380);
  const [isReady, setIsReady] = React.useState(false);
  const isDraggingRef = React.useRef(false);
  const startXRef = React.useRef(0);
  const startWidthRef = React.useRef(380);
  const drawerRef = React.useRef<HTMLDivElement>(null);

  // Initialize session and wait for drawer animation
  React.useEffect(() => {
    if (open) {
      // Small delay to wait for animation
      const timer = setTimeout(() => {
        setIsReady(true);
        // Focus the input
        const input = drawerRef.current?.querySelector('input[aria-label="Message input"]') as HTMLInputElement | null;
        input?.focus();
      }, 300);
      return () => clearTimeout(timer);
    } else {
      setIsReady(false);
    }
  }, [open]);

  useInitializeSession();

  // Lock body scroll when drawer is open
  React.useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [open]);

  // Mouse event handlers for resize
  const handleMouseDown = React.useCallback(
    (e: React.MouseEvent) => {
      isDraggingRef.current = true;
      startXRef.current = e.clientX;
      startWidthRef.current = drawerWidth;
      document.body.style.cursor = 'ew-resize';
      document.body.style.userSelect = 'none';
    },
    [drawerWidth],
  );

  React.useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDraggingRef.current) return;
      const delta = startXRef.current - e.clientX;
      const newWidth = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidthRef.current + delta));
      setDrawerWidth(newWidth);
    };

    const handleMouseUp = () => {
      if (isDraggingRef.current) {
        isDraggingRef.current = false;
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      }
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, []);

  return (
    <>
      {/* FAB Trigger */}
      <motion.button
        onClick={() => setOpen(true)}
        className={cn(
          'fixed bottom-6 right-6 z-40 flex h-14 w-14 items-center justify-center rounded-full shadow-2xl shadow-blue-500/20 transition-all focus:outline-none focus:ring-2 focus:ring-blue-400 focus:ring-offset-2 focus:ring-offset-[#0d1117] active:scale-95',
          'bg-gradient-to-br from-blue-500 to-indigo-600 hover:from-blue-400 hover:to-indigo-500 hover:shadow-blue-500/40 hover:scale-105 hover:shadow-2xl',
        )}
        aria-label="打开知识库问答"
        whileTap={{ scale: 0.93 }}
      >
        <MessageCircle className="size-6 text-white drop-shadow-lg" />
      </motion.button>

      {/* Backdrop */}
      <AnimatePresence>
        {open && (
          <motion.div
            className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={() => setOpen(false)}
          />
        )}
      </AnimatePresence>

      {/* Drawer */}
      <AnimatePresence>
        {open && (
          <motion.div
            ref={drawerRef}
            className={cn(
              'fixed right-0 top-0 z-50 flex h-full flex-col overflow-hidden',
              'bg-[#0d1117]/95 border-l border-white/[0.06]',
              'shadow-2xl shadow-black/50',
            )}
            style={{ width: drawerWidth }}
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', damping: 30, stiffness: 300 }}
          >
            {/* Resize Handle */}
            <div
              className="absolute left-0 top-0 h-full w-5 cursor-ew-resize flex items-center justify-center hover:bg-white/5 transition-colors"
              onMouseDown={handleMouseDown}
            >
              <GripVertical className="size-4 text-slate-600 hover:text-slate-400 transition-colors" />
            </div>

            {/* Header */}
            <div className="flex h-14 shrink-0 items-center justify-between border-b border-white/[0.06] px-4 pl-6">
              <div className="flex items-center gap-3">
                <div className="flex size-8 items-center justify-center rounded-xl border border-violet-500/20 bg-gradient-to-br from-violet-500/10 to-indigo-500/10 shadow-lg shadow-violet-500/10">
                  <MessageCircle className="size-4 text-violet-400" />
                </div>
                <div>
                  <h2 className="text-sm font-bold text-white">知识库问答</h2>
                  <p className="text-[10px] text-slate-500">基于分析历史的 AI 助手</p>
                </div>
              </div>
              <button
                onClick={() => setOpen(false)}
                className="flex size-8 items-center justify-center rounded-lg text-slate-400 transition-all duration-200 hover:bg-white/10 hover:text-white"
                aria-label="关闭"
              >
                <X className="size-4" />
              </button>
            </div>

            {/* Content */}
            <div className="flex flex-1 overflow-hidden pl-5">
              <div className="flex flex-1 min-h-0">
                <RAGChatWrapper />
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
};

const RAGChatWrapper = (): React.JSX.Element => {
  const runtime = useRAGRuntime();
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <Thread />
    </AssistantRuntimeProvider>
  );
};
