'use client';

import React, { useRef, useEffect, useState, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { cn } from '@/lib/utils';
import {
  X,
  ChevronUp,
  Bot,
  User,
  Send,
  Square,
  PanelRightClose,
  Brain,
  Database,
  FileText,
  Zap,
  Sparkles,
  ChevronRight,
  ExternalLink,
  ThumbsUp,
  ThumbsDown,
} from 'lucide-react';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  createdAt?: Date;
  intent?: string;
  sources?: RAGSource[];
  qualityScore?: number;
}

export interface RAGSource {
  id: number;
  title: string;
  category: string;
  relevance: number;
  repo_url?: string;
  preview: string;
  has_code_fix?: boolean;
  content?: string;
  code_fix?: {
    file?: string;
    type?: string;
    original?: string;
    updated?: string;
    reason?: string;
  };
}

// ─── Pipeline Stage ───────────────────────────────────────────────────

type PipelineStage = 'idle' | 'query' | 'retrieving' | 'sources' | 'generating' | 'done';

const PIPELINE_STAGES: { key: PipelineStage; label: string; icon: React.ReactNode }[] = [
  { key: 'query', label: 'Query Processing', icon: <Brain size={12} /> },
  { key: 'retrieving', label: 'Retrieval', icon: <Database size={12} /> },
  { key: 'sources', label: 'Context', icon: <FileText size={12} /> },
  { key: 'generating', label: 'Generation', icon: <Zap size={12} /> },
];

function PipelineIndicator({ stage, percent }: { stage: PipelineStage; percent: number }) {
  return (
    <div className="flex items-center gap-1.5 px-3 py-2 bg-[#0d1117]/80 rounded-lg border border-white/5">
      {PIPELINE_STAGES.map((s, idx) => {
        const isActive = s.key === stage;
        const isPast = PIPELINE_STAGES.findIndex((x) => x.key === stage) > idx;
        const isDone = stage === 'done' || isPast;

        return (
          <React.Fragment key={s.key}>
            <div
              className={cn(
                'flex items-center gap-1 px-2 py-1 rounded-md text-xs transition-all',
                isActive && 'bg-blue-500/20 text-blue-400',
                isDone && !isActive && 'text-green-400/70',
                !isActive && !isDone && 'text-slate-500',
              )}
            >
              {s.icon}
              <span className="hidden sm:inline">{s.label}</span>
            </div>
            {idx < PIPELINE_STAGES.length - 1 && (
              <ChevronRight size={10} className="text-slate-600" />
            )}
          </React.Fragment>
        );
      })}
      <span className="ml-auto text-[10px] text-slate-500 tabular-nums">{percent}%</span>
    </div>
  );
}

// ─── RAG Sources Panel ─────────────────────────────────────────────────

function SourceCard({ source, expanded, onToggle }: { source: RAGSource; expanded: boolean; onToggle: () => void }) {
  return (
    <div className="border border-white/5 rounded-lg overflow-hidden bg-white/[0.02]">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-white/[0.02] transition-colors"
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="flex-shrink-0 w-5 h-5 rounded bg-blue-500/20 text-blue-400 text-[10px] font-mono flex items-center justify-center">
            {source.id}
          </span>
          <span className="text-xs text-slate-300 truncate">{source.title}</span>
          {source.has_code_fix && (
            <span className="flex-shrink-0 px-1.5 py-0.5 bg-green-500/10 text-green-400 text-[10px] rounded">
              代码
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className="text-[10px] text-slate-500">{source.category}</span>
          <span className={cn(
            'text-[10px] px-1.5 py-0.5 rounded',
            source.relevance >= 0.7 ? 'bg-green-500/10 text-green-400' :
            source.relevance >= 0.5 ? 'bg-yellow-500/10 text-yellow-400' :
            'bg-slate-500/10 text-slate-400'
          )}>
            {(source.relevance * 100).toFixed(0)}%
          </span>
          <ChevronUp size={12} className={cn('text-slate-500 transition-transform', expanded && 'rotate-180')} />
        </div>
      </button>

      {expanded && (
        <div className="px-3 pb-3 space-y-2">
          <p className="text-[11px] text-slate-400 leading-relaxed">{source.preview}</p>
          {source.code_fix && (
            <div className="bg-[#1a2030] rounded-md p-2 space-y-1.5">
              <div className="text-[10px] text-slate-500">
                {source.code_fix.file && <span>文件: {source.code_fix.file}</span>}
              </div>
              {source.code_fix.original && (
                <div>
                  <div className="text-[10px] text-red-400/70 mb-1">原代码:</div>
                  <pre className="text-[10px] text-red-300/80 font-mono overflow-x-auto whitespace-pre-wrap">
                    {source.code_fix.original}
                  </pre>
                </div>
              )}
              {source.code_fix.updated && (
                <div>
                  <div className="text-[10px] text-green-400/70 mb-1">修改后:</div>
                  <pre className="text-[10px] text-green-300/80 font-mono overflow-x-auto whitespace-pre-wrap">
                    {source.code_fix.updated}
                  </pre>
                </div>
              )}
              {source.code_fix.reason && (
                <div className="text-[10px] text-slate-400 italic">
                  原因: {source.code_fix.reason}
                </div>
              )}
            </div>
          )}
          {source.repo_url && (
            <div className="text-[10px] text-slate-500">
              来源: <span className="text-blue-400/70">{source.repo_url}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Markdown 渲染 ────────────────────────────────────────────────────

function MarkdownContent({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        h1: ({ children }) => <h1 className="text-xl font-bold text-slate-100 mt-5 mb-2">{children}</h1>,
        h2: ({ children }) => <h2 className="text-lg font-semibold text-slate-100 mt-4 mb-2">{children}</h2>,
        h3: ({ children }) => <h3 className="text-base font-medium text-slate-200 mt-3 mb-1">{children}</h3>,
        p: ({ children }) => <p className="text-slate-300 text-sm leading-relaxed">{children}</p>,
        a: ({ href, children }) => (
          <a href={href} className="text-blue-400 no-underline hover:underline inline-flex items-center gap-0.5" target="_blank" rel="noopener noreferrer">
            {children}<ExternalLink size={10} />
          </a>
        ),
        code: ({ className, children, ...props }) => {
          const isInline = !className;
          if (isInline) {
            return (
              <code className="bg-[#1a2030] text-blue-300 px-1.5 py-0.5 rounded text-sm font-mono" {...props}>
                {children}
              </code>
            );
          }
          return (
            <code className={cn('block bg-[#1a2030] border border-white/10 rounded-lg p-4 my-3 overflow-x-auto text-sm', className)} {...props}>
              {children}
            </code>
          );
        },
        pre: ({ children }) => <>{children}</>,
        blockquote: ({ children }) => (
          <blockquote className="border-l-2 border-blue-500/40 pl-4 my-2 text-slate-400 italic text-sm">{children}</blockquote>
        ),
        ul: ({ children }) => <ul className="list-disc pl-5 my-2 space-y-1">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal pl-5 my-2 space-y-1">{children}</ol>,
        li: ({ children }) => <li className="text-slate-300 text-sm leading-relaxed">{children}</li>,
        table: ({ children }) => <table className="w-full border-collapse my-3 text-sm">{children}</table>,
        thead: ({ children }) => <thead className="bg-white/5">{children}</thead>,
        th: ({ children }) => <th className="border border-white/10 px-3 py-2 text-left text-slate-200">{children}</th>,
        td: ({ children }) => <td className="border border-white/10 px-3 py-2 text-slate-300">{children}</td>,
        hr: () => <hr className="border-white/10 my-4" />,
        strong: ({ children }) => <strong className="text-slate-100 font-semibold">{children}</strong>,
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

// ─── 单条气泡 ─────────────────────────────────────────────────────────

function ChatBubble({ message, sources, expandedSources, onToggleSource, onFeedback }: {
  message: ChatMessage;
  sources: RAGSource[];
  expandedSources: Set<number>;
  onToggleSource: (id: number) => void;
  onFeedback: (id: string, good: boolean) => void;
}) {
  const isUser = message.role === 'user';
  const showSources = sources.length > 0;

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

        {/* Intent badge */}
        {!isUser && message.intent && (
          <div className="flex items-center gap-1 mt-1 px-1">
            <span className="text-[10px] text-slate-600">意图:</span>
            <span className="text-[10px] px-1.5 py-0.5 bg-purple-500/10 text-purple-400 rounded">
              {message.intent}
            </span>
          </div>
        )}

        {/* Sources */}
        {!isUser && showSources && (
          <div className="mt-2 w-full max-w-md space-y-1">
            <div className="flex items-center gap-1 px-1">
              <Database size={10} className="text-slate-500" />
              <span className="text-[10px] text-slate-500">
                参考资料 ({sources.length})
              </span>
            </div>
            {sources.slice(0, 3).map((source) => (
              <SourceCard
                key={source.id}
                source={source}
                expanded={expandedSources.has(source.id)}
                onToggle={() => onToggleSource(source.id)}
              />
            ))}
            {sources.length > 3 && (
              <button className="text-[10px] text-blue-400 hover:text-blue-300 px-1">
                查看全部 {sources.length} 条 →
              </button>
            )}
          </div>
        )}

        {/* Feedback */}
        {!isUser && message.content && (
          <div className="flex items-center gap-1 mt-1 px-1">
            <button
              onClick={() => onFeedback(message.id, true)}
              className="p-1 text-slate-600 hover:text-green-400 transition-colors"
              title="回答有帮助"
            >
              <ThumbsUp size={12} />
            </button>
            <button
              onClick={() => onFeedback(message.id, false)}
              className="p-1 text-slate-600 hover:text-red-400 transition-colors"
              title="回答不满意"
            >
              <ThumbsDown size={12} />
            </button>
            <span className="text-[10px] text-slate-600 ml-1">
              {message.createdAt?.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Loading Indicator ────────────────────────────────────────────────

function LoadingIndicator({ stage, message }: { stage: PipelineStage; message?: string }) {
  return (
    <div className="flex gap-3">
      <div className="flex-shrink-0 w-8 h-8 rounded-full bg-purple-500/20 text-purple-400 flex items-center justify-center">
        <Bot size={14} />
      </div>
      <div className="rounded-2xl rounded-tl-sm bg-[#1a2030] border border-white/5 px-4 py-3">
        <PipelineIndicator stage={stage} percent={0} />
        {message && (
          <p className="text-xs text-slate-400 mt-2">{message}</p>
        )}
      </div>
    </div>
  );
}

// ─── ChatDrawer 主组件 ───────────────────────────────────────────────

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
  const [pipelineStage, setPipelineStage] = useState<PipelineStage>('idle');
  const [pipelinePercent, setPipelinePercent] = useState(0);
  const [pipelineMessage, setPipelineMessage] = useState('');
  const [currentSources, setCurrentSources] = useState<RAGSource[]>([]);
  const [expandedSources, setExpandedSources] = useState<Set<number>>(new Set());

  // Intentionally unused — retained for future pipeline UI display
  void pipelinePercent;
  void currentSources;

  const assistantMsgIdRef = useRef<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const sessionCreatedRef = useRef(false);

  // 组件挂载时创建真实会话
  useEffect(() => {
    if (sessionCreatedRef.current) return;
    sessionCreatedRef.current = true;

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
  }, [messages, pipelineStage]);

  const toggleSource = useCallback((id: number) => {
    setExpandedSources((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const handleFeedback = useCallback((id: string, good: boolean) => {
    // 反馈收集（后续可发送到后端）
    console.log(`Feedback for ${id}: ${good ? 'good' : 'bad'}`);
  }, []);

  const handleSSEEvent = useCallback((parsed: Record<string, unknown>) => {
    const t = parsed.type as string;
    const msgId = assistantMsgIdRef.current;

    switch (t) {
      case 'connected':
        setPipelineStage('query');
        setPipelinePercent(5);
        setPipelineMessage('正在连接...');
        break;

      case 'route':
        setPipelineStage('retrieving');
        setPipelinePercent(parsed.percent as number ?? 10);
        setPipelineMessage(parsed.message as string ?? '正在检索...');
        break;

      case 'retrieving':
        setPipelineStage('sources');
        setPipelinePercent(parsed.percent as number ?? 30);
        setPipelineMessage(parsed.message as string ?? '整理上下文...');
        break;

      case 'sources': {
        const rawSources = parsed.sources as Array<Record<string, unknown>> | undefined;
        if (rawSources && Array.isArray(rawSources)) {
          const mapped = rawSources.map((s, i) => ({
            id: typeof s.id === 'number' ? s.id : i + 1,
            title: String(s.title ?? '未知来源'),
            category: String(s.category ?? ''),
            relevance: typeof s.relevance === 'number' ? s.relevance :
                       typeof s.score === 'number' ? s.score : 0,
            repo_url: s.repo_url ? String(s.repo_url) : undefined,
            preview: String(s.preview ?? ''),
            has_code_fix: Boolean(s.has_code_fix ?? false),
            content: s.content ? String(s.content) : undefined,
            code_fix: s.code_fix as RAGSource['code_fix'] | undefined,
          }));
          setCurrentSources(mapped);
        }
        setPipelinePercent(parsed.percent as number ?? 40);
        setPipelineMessage(parsed.message as string ?? `找到 ${rawSources?.length ?? 0} 条相关知识`);
        break;
      }

      case 'generating':
        setPipelineStage('generating');
        setPipelinePercent(parsed.percent as number ?? 55);
        setPipelineMessage('正在生成回答...');
        break;

      case 'token':
        setPipelineStage('generating');
        if (msgId) {
          const delta = ((parsed.delta ?? '') as string) || '';
          const fullText = ((parsed.full_text ?? '') as string) || '';
          if (delta) {
            setMessages((prev) =>
              prev.map((m) => (m.id === msgId ? { ...m, content: fullText } : m)),
            );
          }
        }
        setPipelinePercent(parsed.percent as number ?? 60);
        break;

      case 'done': {
        if (msgId) {
          const answer = ((parsed.answer ?? parsed.full_text ?? '') as string) || '';
          const sources = (parsed.sources as RAGSource[] | undefined) ?? [];
          const intent = String(parsed.intent ?? '');
          setMessages((prev) =>
            prev.map((m) =>
              m.id === msgId
                ? { ...m, content: answer, intent, sources, qualityScore: parsed.quality_score as number }
                : m,
            ),
          );
        }
        setPipelineStage('done');
        setPipelinePercent(100);
        setPipelineMessage('回答完成');
        break;
      }

      case 'error':
        setError((parsed.message as string) ?? '发生错误');
        setPipelineStage('idle');
        if (msgId) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === msgId
                ? { ...m, content: m.content + `\n\n[错误] ${parsed.message ?? ''}` }
                : m,
            ),
          );
        }
        break;
    }
  }, []);

  const sendMessage = useCallback(
    async (content: string) => {
      if (!content.trim() || isLoading) return;

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
      setPipelineStage('query');
      setPipelinePercent(5);
      setPipelineMessage('正在分析问题...');
      setCurrentSources([]);
      setExpandedSources(new Set());

      const ctrl = new AbortController();
      abortRef.current = ctrl;

      try {
        const res = await fetch('/api/chat/send', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sessionId, content: content.trim() }),
          signal: ctrl.signal,
        });

        if (!res.ok) {
          throw new Error(`请求失败: ${res.status}`);
        }

        if (!res.body) throw new Error('后端返回空响应');

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() ?? '';

          for (const line of lines) {
            const raw = line.startsWith('data: ')
              ? line.slice(6).trim()
              : line.trim();

            if (raw === '[DONE]') continue;

            try {
              const parsed = JSON.parse(raw);
              handleSSEEvent(parsed as Record<string, unknown>);
            } catch {
              /* ignore parse errors */
            }
          }
        }
      } catch (err) {
        if ((err as Error).name === 'AbortError') return;
        const msg = (err as Error).message ?? '未知错误';
        setError(msg);
        setPipelineStage('idle');
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsgIdRef.current
              ? { ...m, content: m.content || `[网络错误] ${msg}` }
              : m,
          ),
        );
      } finally {
        setIsLoading(false);
        setPipelineStage('done');
        abortRef.current = null;
        assistantMsgIdRef.current = null;
        textareaRef.current?.focus();
      }
    },
    [isLoading, sessionId, handleSSEEvent],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    setIsLoading(false);
    setPipelineStage('idle');
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
          <span className="text-xs text-slate-500">· RAG Pipeline</span>
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
                  <Sparkles size={24} className="text-purple-400" />
                </div>
                <p className="text-slate-300 text-sm font-medium">有什么可以帮你的？</p>
                <p className="text-slate-600 text-xs">基于知识库的智能问答助手</p>
              </div>
            )}

            {messages.map((msg) => {
              const isLastAssistant = msg.id === assistantMsgIdRef.current && isLoading;
              if (isLastAssistant && msg.content === '') {
                return (
                  <LoadingIndicator
                    key={msg.id}
                    stage={pipelineStage}
                    message={pipelineMessage}
                  />
                );
              }
              return (
                <ChatBubble
                  key={msg.id}
                  message={msg}
                  sources={msg.sources ?? []}
                  expandedSources={expandedSources}
                  onToggleSource={toggleSource}
                  onFeedback={handleFeedback}
                />
              );
            })}

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
