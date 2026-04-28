'use client';

import React, { useRef, useEffect, useState, useCallback } from 'react';
import { cn } from '@/lib/utils';
import {
  X,
  ChevronUp,
  Bot,
  User,
  Send,
  Square,
  PanelRightClose,
} from 'lucide-react';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  createdAt?: Date;
}

// ─── Markdown 渲染 ────────────────────────────────────────────────

function MarkdownContent({ content }: { content: string }) {
  const lines = content.split('\n');
  const elements: React.ReactNode[] = [];
  let codeBlock: { lang: string; content: string[] } | null = null;
  let listItems: string[] = [];
  let inList = false;

  const flushCodeBlock = () => {
    if (!codeBlock) return;
    elements.push(
      <pre
        key={`code-${elements.length}`}
        className="bg-[#1a2030] border border-white/10 rounded-lg p-4 my-3 overflow-x-auto text-sm"
      >
        <code className="text-slate-200 font-mono">{codeBlock.content.join('\n')}</code>
      </pre>,
    );
    codeBlock = null;
  };

  const flushList = () => {
    if (!inList || listItems.length === 0) return;
    elements.push(
      <ul key={`list-${elements.length}`} className="list-disc pl-5 my-2 space-y-1">
        {listItems.map((item, i) => (
          <li key={i} className="text-slate-300 text-sm leading-relaxed">
            {item}
          </li>
        ))}
      </ul>,
    );
    listItems = [];
    inList = false;
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    if (line.startsWith('```')) {
      if (codeBlock) {
        flushCodeBlock();
      } else {
        flushList();
        codeBlock = { lang: line.slice(3).trim(), content: [] };
      }
      continue;
    }

    if (codeBlock) {
      codeBlock.content.push(line);
      continue;
    }

    if (line.startsWith('- ') || line.startsWith('* ')) {
      if (!inList) {
        flushList();
        inList = true;
      }
      listItems.push(line.slice(2));
      continue;
    }
    flushList();

    if (line.startsWith('# ')) {
      elements.push(
        <h1 key={`h1-${i}`} className="text-xl font-bold text-white mt-5 mb-2">
          {line.slice(2)}
        </h1>,
      );
    } else if (line.startsWith('## ')) {
      elements.push(
        <h2 key={`h2-${i}`} className="text-lg font-semibold text-slate-100 mt-4 mb-2">
          {line.slice(3)}
        </h2>,
      );
    } else if (line.startsWith('### ')) {
      elements.push(
        <h3 key={`h3-${i}`} className="text-base font-medium text-slate-200 mt-3 mb-1">
          {line.slice(4)}
        </h3>,
      );
    } else if (line.startsWith('> ')) {
      elements.push(
        <blockquote
          key={`q-${i}`}
          className="border-l-2 border-blue-500/40 pl-4 my-2 text-slate-400 italic text-sm"
        >
          {line.slice(2)}
        </blockquote>,
      );
    } else if (line.trim() === '') {
      elements.push(<div key={`sp-${i}`} className="h-1" />);
    } else {
      const parts: React.ReactNode[] = [];
      let last = 0;
      const re = /`([^`]+)`|\*\*([^*]+)\*\*/g;
      let m: RegExpExecArray | null;
      while ((m = re.exec(line)) !== null) {
        if (m.index > last) parts.push(line.slice(last, m.index));
        if (m[1]) {
          parts.push(
            <code
              key={`ic-${m.index}`}
              className="bg-[#1a2030] text-blue-300 px-1.5 py-0.5 rounded text-sm font-mono"
            >
              {m[1]}
            </code>,
          );
        } else if (m[2]) {
          parts.push(
            <strong key={`b-${m.index}`} className="text-white font-semibold">
              {m[2]}
            </strong>,
          );
        }
        last = m.index + m[0].length;
      }
      if (last < line.length) parts.push(line.slice(last));
      elements.push(
        <p key={`p-${i}`} className="text-slate-300 text-sm leading-relaxed">
          {parts.length > 0 ? parts : line}
        </p>,
      );
    }
  }

  flushCodeBlock();
  flushList();
  return <>{elements}</>;
}

// ─── 单条气泡 ────────────────────────────────────────────────────

function ChatBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user';

  return (
    <div
      className={cn(
        'flex gap-3 w-full animate-in slide-in-from-bottom-2',
        isUser ? 'flex-row-reverse' : '',
      )}
      style={{ animationDuration: '200ms' }}
    >
      <div
        className={cn(
          'flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-xs',
          isUser ? 'bg-blue-500/20 text-blue-400' : 'bg-purple-500/20 text-purple-400',
        )}
      >
        {isUser ? <User size={14} /> : <Bot size={14} />}
      </div>

      <div className={cn('flex flex-col max-w-[85%]', isUser ? 'items-end' : 'items-start')}>
        <div
          className={cn(
            'rounded-2xl px-4 py-3 text-sm leading-relaxed',
            isUser
              ? 'bg-blue-500 text-white rounded-tr-sm'
              : 'bg-[#1a2030] text-slate-200 border border-white/5 rounded-tl-sm',
          )}
        >
          <MarkdownContent content={message.content} />
        </div>
        {message.createdAt && (
          <span className="text-[10px] text-slate-600 mt-1 px-1">
            {message.createdAt.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
          </span>
        )}
      </div>
    </div>
  );
}

function LoadingIndicator() {
  return (
    <div className="flex gap-1 items-center py-1 px-1">
      <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce [animation-delay:0ms]" />
      <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce [animation-delay:150ms]" />
      <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce [animation-delay:300ms]" />
    </div>
  );
}

// ─── ChatDrawer 主组件 ───────────────────────────────────────────

interface ChatDrawerProps {
  onClose: () => void;
}

export function ChatDrawer({ onClose }: ChatDrawerProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isExpanded, setIsExpanded] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const assistantMsgIdRef = useRef<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // 组件挂载时创建真实会话
  useEffect(() => {
    const now = new Date();
    const title = `${now.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })} 对话`;
    fetch('/api/chat/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.id) setSessionId(data.id);
      })
      .catch(() => {
        /* ignore */
      });
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const parseSSE = useCallback((raw: string) => {
    // Handle [DONE] sentinel
    if (raw === '[DONE]') return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }, []);

  const handleSSEEvent = useCallback((parsed: Record<string, unknown>) => {
    const t = parsed.type as string;
    const msgId = assistantMsgIdRef.current;
    if (!msgId) return;

    if (t === 'error') {
      setError((parsed.message as string) ?? '发生错误');
      setMessages((prev) =>
        prev.map((m) =>
          m.id === msgId ? { ...m, content: m.content + `\n[错误] ${parsed.message ?? ''}` } : m,
        ),
      );
      return;
    }

    if (t === 'token' || t === 'chunk') {
      const delta = ((parsed.delta ?? parsed.text ?? '') as string) || '';
      if (delta) {
        setMessages((prev) =>
          prev.map((m) => (m.id === msgId ? { ...m, content: m.content + delta } : m)),
        );
      }
      return;
    }

    // Handle done event: backend sends the complete answer in answer/full_text
    if (t === 'done') {
      const answer = ((parsed.answer ?? parsed.full_text ?? '') as string) || '';
      if (answer) {
        setMessages((prev) => prev.map((m) => (m.id === msgId ? { ...m, content: answer } : m)));
      }
      return;
    }
  }, []);

  const sendMessage = useCallback(
    async (content: string) => {
      if (!content.trim() || isLoading) return;

      // 等 sessionId 就绪
      if (!sessionId) {
        setError('会话尚未创建，请稍后重试');
        return;
      }

      const userMsg: ChatMessage = {
        id: `user-${Date.now()}`,
        role: 'user',
        content: content.trim(),
        createdAt: new Date(),
      };

      const msgId = `asst-${Date.now()}`;
      assistantMsgIdRef.current = msgId;
      const assistantMsg: ChatMessage = {
        id: msgId,
        role: 'assistant',
        content: '',
        createdAt: new Date(),
      };

      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setIsLoading(true);
      setError(null);

      const ctrl = new AbortController();
      abortRef.current = ctrl;

      try {
        const res = await fetch('/api/chat/stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sessionId, content: content.trim() }),
          signal: ctrl.signal,
        });

        if (!res.ok) {
          throw new Error(`请求失败: ${res.status}`);
        }

        if (!res.body) throw new Error('后端返回空响应');

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let done = false;

        while (true) {
          const { done: readerDone, value } = await reader.read();
          if (readerDone) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() ?? '';

          for (const line of lines) {
            const raw = line.startsWith('data: ') ? line.slice(6).trim() : line.trim();

            if (raw === '[DONE]') {
              done = true;
              continue;
            }

            // Lines after [DONE] are raw JSON
            if (done) {
              const parsed = parseSSE(raw);
              if (!parsed || !(parsed as Record<string, unknown>).type) continue;
              handleSSEEvent(parsed as Record<string, unknown>);
              done = false;
              continue;
            }

            const parsed = parseSSE(raw);
            if (!parsed) continue;
            handleSSEEvent(parsed as Record<string, unknown>);
          }
        }
      } catch (err) {
        if ((err as Error).name === 'AbortError') return;
        const msg = (err as Error).message ?? '未知错误';
        setError(msg);
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsgIdRef.current
              ? { ...m, content: m.content || `[网络错误] ${msg}` }
              : m,
          ),
        );
      } finally {
        setIsLoading(false);
        abortRef.current = null;
        assistantMsgIdRef.current = null;
        textareaRef.current?.focus();
      }
    },
    [isLoading, sessionId, parseSSE, handleSSEEvent],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    setIsLoading(false);
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;
    const text = input.trim();
    setInput('');
    sendMessage(text);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!input.trim() || isLoading) return;
      const text = input.trim();
      setInput('');
      sendMessage(text);
    }
  };

  const adjustTextareaHeight = () => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
  };

  return (
    <div className="fixed bottom-6 right-6 w-[800px] h-[800px] flex flex-col bg-[#0d1117]/95 backdrop-blur-xl border border-white/10 rounded-2xl shadow-2xl shadow-black/50 z-[9999] overflow-hidden animate-in slide-in-from-bottom-4 fade-in duration-300 md:w-[640px] md:h-[700px] sm:w-[calc(100vw-32px)] sm:h-[calc(100vh-120px)]">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-white/5 bg-[#161b22] flex-shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
          <span className="text-sm font-medium text-slate-200">AI 助手</span>
          <span className="text-xs text-slate-500">· 基于 Qwen</span>
        </div>
        <div className="flex items-center gap-1">
          {isLoading && (
            <button
              onClick={stop}
              className="p-1.5 text-slate-500 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-all"
              title="停止生成"
            >
              <Square size={14} />
            </button>
          )}
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="p-1.5 text-slate-500 hover:text-slate-300 hover:bg-white/5 rounded-lg transition-all"
          >
            {isExpanded ? <ChevronUp size={16} /> : <PanelRightClose size={16} />}
          </button>
          <button
            onClick={onClose}
            className="p-1.5 text-slate-500 hover:text-slate-300 hover:bg-white/5 rounded-lg transition-all"
            title="关闭"
          >
            <X size={16} />
          </button>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="px-5 py-2 bg-red-500/10 border-b border-red-500/20 text-red-400 text-xs flex-shrink-0">
          {error}
        </div>
      )}

      {isExpanded && (
        <>
          {/* 消息列表 */}
          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4 min-h-0 [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-track]:bg-transparent [&::-webkit-scrollbar-thumb]:bg-white/10 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:hover:bg-white/20">
            {messages.length === 0 && (
              <div className="flex flex-col items-center justify-center h-full text-center space-y-3 py-12">
                <div className="w-12 h-12 bg-purple-500/10 rounded-2xl flex items-center justify-center">
                  <Bot size={24} className="text-purple-400" />
                </div>
                <p className="text-slate-300 text-sm font-medium">有什么可以帮你的？</p>
                <p className="text-slate-600 text-xs">询问代码架构、依赖风险或优化建议</p>
              </div>
            )}

            {messages.map((msg, idx) => {
              const isLastAssistant = idx === messages.length - 1 && msg.role === "assistant" && msg.content === "" && isLoading;
              if (isLastAssistant) return null;
              return <ChatBubble key={msg.id} message={msg} />;
            })}

            {isLoading && messages.length > 0 && messages[messages.length - 1].content === '' && (
              <div className="flex gap-3">
                <div className="flex-shrink-0 w-8 h-8 rounded-full bg-purple-500/20 text-purple-400 flex items-center justify-center">
                  <Bot size={14} />
                </div>
                <div className="rounded-2xl rounded-tl-sm bg-[#1a2030] border border-white/5 px-4 py-3">
                  <LoadingIndicator />
                </div>
              </div>
            )}

            <div ref={bottomRef} />
          </div>

          {/* 输入区 */}
          <div className="px-4 py-3 border-t border-white/5 bg-[#161b22] flex-shrink-0">
            <form onSubmit={handleSubmit} className="flex gap-2 items-center">
              <div className="flex-1 relative flex items-center">
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => {
                    setInput(e.target.value);
                    adjustTextareaHeight();
                  }}
                  onKeyDown={handleKeyDown}
                  placeholder="输入消息，Enter 发送，Shift+Enter 换行…"
                  rows={1}
                  disabled={isLoading}
                  className="w-full bg-[#0d1117] border border-white/10 rounded-xl px-4 py-3 text-sm text-slate-200 placeholder-slate-600 resize-none focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/20 disabled:opacity-50 transition-all"
                  style={{ minHeight: '48px', maxHeight: '160px' }}
                />
              </div>
              <button
                type="submit"
                disabled={!input.trim() || isLoading}
                className="flex-shrink-0 w-10 h-10 bg-blue-500 hover:bg-blue-600 disabled:bg-slate-800 disabled:text-slate-600 text-white rounded-xl flex items-center justify-center transition-all"
              >
                <Send size={16} />
              </button>
            </form>
            <p className="text-[10px] text-slate-700 mt-2 text-center">
              AI 助手可能产生不准确的信息，请核实后再使用
            </p>
          </div>
        </>
      )}
    </div>
  );
}
