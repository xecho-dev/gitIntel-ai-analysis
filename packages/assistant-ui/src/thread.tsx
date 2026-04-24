'use client';

import {
  ArrowDownIcon,
  ArrowUpIcon,
  CheckIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CopyIcon,
  DownloadIcon,
  LoaderIcon,
  PencilIcon,
  RefreshCwIcon,
  SquareIcon,
} from 'lucide-react';
import {
  ActionBarPrimitive,
  AuiIf,
  BranchPickerPrimitive,
  ComposerPrimitive,
  ErrorPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
} from '@assistant-ui/react';
import '@assistant-ui/react-markdown/styles/dot.css';

import { cn } from '@gitintel/ui';
import { ToolFallback } from './tool-fallback';
import { ComposerAddAttachment, ComposerAttachments, UserMessageAttachments } from './attachment';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

function AssistantText({ text }: { text: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ children }) => (
          <p className="mb-2.5 leading-normal first:mt-0 last:mb-0">{children}</p>
        ),
        h1: ({ children }) => (
          <h1 className="mb-2 mt-4 text-base font-semibold first:mt-0">{children}</h1>
        ),
        h2: ({ children }) => (
          <h2 className="mb-1.5 mt-3 text-sm font-semibold first:mt-0">{children}</h2>
        ),
        h3: ({ children }) => (
          <h3 className="mb-1 mt-2.5 text-sm font-medium first:mt-0">{children}</h3>
        ),
        a: ({ href, children }) => (
          <a
            href={href}
            className="text-blue-400 underline underline-offset-2 hover:text-blue-300"
            target="_blank"
            rel="noopener noreferrer"
          >
            {children}
          </a>
        ),
        ul: ({ children }) => (
          <ul className="mb-2 ml-4 list-disc marker:text-slate-500 [&>li]:mt-1">{children}</ul>
        ),
        ol: ({ children }) => (
          <ol className="mb-2 ml-4 list-decimal marker:text-slate-500 [&>li]:mt-1">{children}</ol>
        ),
        li: ({ children }) => <li className="leading-normal">{children}</li>,
        code: ({ className, children }) => {
          const isInline = !className?.includes('language-');
          if (isInline) {
            return (
              <code className="rounded-md border border-white/10 bg-white/5 px-1.5 py-0.5 font-mono text-[0.85em] text-slate-300">
                {children}
              </code>
            );
          }
          return <code className={className}>{children}</code>;
        },
        pre: ({ children }) => (
          <div className="group relative mb-2.5 overflow-hidden rounded-lg border border-white/10 bg-white/5">
            <pre className="overflow-x-auto p-3 text-xs leading-relaxed text-slate-300">
              {children}
            </pre>
          </div>
        ),
        blockquote: ({ children }) => (
          <blockquote className="my-2.5 border-l-2 border-slate-500 pl-3 italic text-slate-400">
            {children}
          </blockquote>
        ),
      }}
    >
      {text}
    </ReactMarkdown>
  );
}

function UserText({ text }: { text: string }) {
  return <span>{text}</span>;
}

export function Thread() {
  return (
    <ThreadPrimitive.Root className="flex h-full flex-col bg-[#0d1117] text-sm w-full">
      <ThreadPrimitive.Viewport
        turnAnchor="top"
        className="relative flex flex-1 flex-col overflow-x-auto overflow-y-scroll scroll-smooth px-4 pt-4"
      >
        <AuiIf condition={(s) => s.thread.isEmpty}>
          <ThreadWelcome />
        </AuiIf>

        <ThreadPrimitive.Messages
          components={{
            UserMessage,
            EditComposer,
            AssistantMessage,
          }}
        />

        <ThreadPrimitive.ViewportFooter className="sticky bottom-0 mx-auto mt-auto flex w-full max-w-full flex-col gap-4 overflow-visible rounded-t-3xl bg-[#0d1117] pb-4">
          <ThreadScrollToBottom />
          <Composer />
        </ThreadPrimitive.ViewportFooter>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
  );
}

function ThreadWelcome() {
  const suggestions = [
    '如何提升代码质量？',
    '有哪些架构问题？',
    '依赖风险有哪些？',
    '最佳重构建议？',
  ];

  return (
    <div className="mx-auto my-auto flex w-full max-w-full flex-grow flex-col">
      <div className="flex w-full flex-grow flex-col items-center justify-center">
        <div className="flex size-full flex-col justify-center px-8">
          <div className="mb-2 text-2xl font-semibold text-white">知识库问答助手</div>
          <div className="text-slate-400">
            基于你的分析历史，帮你解答代码架构、质量、依赖风险等问题
          </div>
        </div>
      </div>
      <div className="grid w-full gap-2 pb-4 md:grid-cols-2">
        {suggestions.map((prompt) => (
          <ThreadPrimitive.Suggestion key={prompt} prompt={prompt} asChild>
            <button className="h-auto w-full flex-col items-start justify-start gap-1 rounded-2xl border border-white/10 bg-white/5 px-5 py-4 text-left text-sm text-slate-300 transition-all hover:border-violet-500/30 hover:bg-violet-500/10 hover:text-violet-300">
              <span className="font-medium">{prompt}</span>
            </button>
          </ThreadPrimitive.Suggestion>
        ))}
      </div>
    </div>
  );
}

function Composer() {
  return (
    <ComposerPrimitive.Root className="relative flex w-full flex-col">
      <ComposerPrimitive.AttachmentDropzone className="flex w-full flex-col rounded-2xl border border-white/10 bg-[#161b22] px-1 pt-2 outline-none transition-shadow focus-within:border-violet-500/40 focus-within:ring-2 focus-within:ring-violet-500/20 data-[dragging=true]:border-ring data-[dragging=true]:border-dashed data-[dragging=true]:bg-accent/50">
        <ComposerAttachments />
        <ComposerPrimitive.Input
          placeholder="输入你的问题..."
          className="mb-1 max-h-32 min-h-14 w-full resize-none bg-transparent px-4 pt-2 pb-3 text-sm text-white outline-none placeholder:text-slate-600 focus-visible:ring-0"
          rows={1}
          autoFocus
          aria-label="Message input"
        />
        <ComposerAction />
      </ComposerPrimitive.AttachmentDropzone>
    </ComposerPrimitive.Root>
  );
}

function ComposerAction() {
  return (
    <div className="relative mx-2 mb-2 flex items-center justify-between">
      <ComposerAddAttachment />

      <AuiIf condition={(s) => !s.thread.isRunning}>
        <ComposerPrimitive.Send asChild>
          <button
            className="flex size-8 items-center justify-center rounded-full bg-blue-500 text-white hover:bg-blue-600"
            style={{
              backgroundColor: 'var(--accent-color, #3b82f6)',
              color: 'var(--accent-foreground, #ffffff)',
            }}
            aria-label="发送消息"
          >
            <ArrowUpIcon className="size-4" />
          </button>
        </ComposerPrimitive.Send>
      </AuiIf>

      <AuiIf condition={(s) => s.thread.isRunning}>
        <ComposerPrimitive.Cancel asChild>
          <button
            type="button"
            className="flex size-8 items-center justify-center rounded-full"
            style={{
              backgroundColor: 'var(--accent-color, #3b82f6)',
              color: 'var(--accent-foreground, #ffffff)',
            }}
            aria-label="停止生成"
          >
            <SquareIcon className="size-3 fill-current" />
          </button>
        </ComposerPrimitive.Cancel>
      </AuiIf>
    </div>
  );
}

function ThreadScrollToBottom() {
  return (
    <ThreadPrimitive.ScrollToBottom asChild>
      <button
        className="absolute -top-12 z-10 self-center rounded-full p-4 text-slate-400 hover:bg-white/10 disabled:invisible"
        title="滚动到底部"
      >
        <ArrowDownIcon />
      </button>
    </ThreadPrimitive.ScrollToBottom>
  );
}

function UserMessage() {
  return (
    <MessagePrimitive.Root
      className="mx-auto grid w-full max-w-full auto-rows-auto grid-cols-[minmax(72px,1fr)_auto] content-start gap-y-2 px-2 py-3 fade-in slide-in-from-bottom-1 animate-in duration-150"
      data-role="user"
    >
      <UserMessageAttachments />

      <div className="relative col-start-2 min-w-0">
        <div className="rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-600 px-4 py-2.5 text-white shadow-lg shadow-blue-500/20 break-words">
          <MessagePrimitive.Parts
            components={{
              Text: UserText,
            }}
          />
        </div>
        <div className="absolute top-1/2 left-0 -translate-x-full -translate-y-1/2 pr-2">
          <UserActionBar />
        </div>
      </div>

      <BranchPicker className="col-span-full col-start-1 row-start-3 -mr-1 justify-end" />
    </MessagePrimitive.Root>
  );
}

function UserActionBar() {
  return (
    <ActionBarPrimitive.Root
      hideWhenRunning
      autohide="not-last"
      className="flex flex-col items-end"
    >
      <ActionBarPrimitive.Edit asChild>
        <button className="p-4 text-slate-400 hover:text-white" title="编辑">
          <PencilIcon />
        </button>
      </ActionBarPrimitive.Edit>
    </ActionBarPrimitive.Root>
  );
}

function EditComposer() {
  return (
    <MessagePrimitive.Root className="mx-auto flex w-full max-w-full flex-col px-2 py-3">
      <ComposerPrimitive.Root className="ml-auto flex w-full max-w-[85%] flex-col rounded-2xl bg-muted">
        <ComposerPrimitive.Input
          className="min-h-14 w-full resize-none bg-transparent p-4 text-sm text-foreground outline-none"
          autoFocus
        />
        <div className="mx-3 mb-3 flex items-center gap-2 self-end">
          <ComposerPrimitive.Cancel asChild>
            <button className="rounded px-3 py-1 text-sm hover:bg-white/10">取消</button>
          </ComposerPrimitive.Cancel>
          <ComposerPrimitive.Send asChild>
            <button className="rounded bg-blue-500 px-3 py-1 text-sm text-white hover:bg-blue-600">
              更新
            </button>
          </ComposerPrimitive.Send>
        </div>
      </ComposerPrimitive.Root>
    </MessagePrimitive.Root>
  );
}

function AssistantMessage() {
  return (
    <MessagePrimitive.Root
      className="relative mx-auto w-full max-w-full py-3 fade-in slide-in-from-bottom-1 animate-in duration-150"
      data-role="assistant"
    >
      <div className="break-words px-2 leading-relaxed text-slate-200">
        <MessagePrimitive.Parts
          components={{
            Text: AssistantText,
            tools: { Fallback: ToolFallback },
          }}
        />
        <MessageError />
        <AuiIf condition={(s) => s.thread.isRunning && s.message.content.length === 0}>
          <div className="flex items-center gap-2 text-slate-500">
            <LoaderIcon className="size-4 animate-spin" />
            <span className="text-sm">思考中...</span>
          </div>
        </AuiIf>
      </div>

      <div className="ml-2 flex min-h-6 items-center">
        <BranchPicker />
        <AssistantActionBar />
      </div>
    </MessagePrimitive.Root>
  );
}

function MessageError() {
  return (
    <MessagePrimitive.Error>
      <ErrorPrimitive.Root className="mt-2 rounded-md border border-destructive bg-destructive/10 p-3 text-sm text-destructive">
        <ErrorPrimitive.Message className="line-clamp-2" />
      </ErrorPrimitive.Root>
    </MessagePrimitive.Error>
  );
}

function AssistantActionBar() {
  return (
    <ActionBarPrimitive.Root
      hideWhenRunning
      autohide="not-last"
      className="-ml-1 flex gap-1 text-slate-500"
    >
      <ActionBarPrimitive.Copy asChild>
        <button
          className="flex size-6 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
          title="复制"
        >
          <AuiIf condition={(s) => s.message.isCopied}>
            <CheckIcon className="size-3.5 text-green-500" />
          </AuiIf>
          <AuiIf condition={(s) => !s.message.isCopied}>
            <CopyIcon className="size-3.5" />
          </AuiIf>
        </button>
      </ActionBarPrimitive.Copy>
      <ActionBarPrimitive.ExportMarkdown asChild>
        <button
          className="flex size-6 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
          title="导出为 Markdown"
        >
          <DownloadIcon className="size-3.5" />
        </button>
      </ActionBarPrimitive.ExportMarkdown>
      <ActionBarPrimitive.Reload asChild>
        <button
          className="flex size-6 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
          title="重新生成"
        >
          <RefreshCwIcon className="size-3.5" />
        </button>
      </ActionBarPrimitive.Reload>
    </ActionBarPrimitive.Root>
  );
}

function BranchPicker({ className, ...rest }: { className?: string }) {
  return (
    <BranchPickerPrimitive.Root
      hideWhenSingleBranch
      className={cn('mr-2 -ml-2 inline-flex items-center text-xs text-slate-500', className)}
      {...rest}
    >
      <BranchPickerPrimitive.Previous asChild>
        <button
          className="flex size-6 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
          title="上一个"
        >
          <ChevronLeftIcon />
        </button>
      </BranchPickerPrimitive.Previous>
      <span className="mx-1 font-medium">
        <BranchPickerPrimitive.Number /> / <BranchPickerPrimitive.Count />
      </span>
      <BranchPickerPrimitive.Next asChild>
        <button
          className="flex size-6 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
          title="下一个"
        >
          <ChevronRightIcon />
        </button>
      </BranchPickerPrimitive.Next>
    </BranchPickerPrimitive.Root>
  );
}
