"use client";

/* eslint-disable @typescript-eslint/no-explicit-any */

import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { CheckIcon, CopyIcon } from "lucide-react";

type MarkdownTextProps = {
  content: string;
  className?: string;
};

const CopyButton: React.FC<{ text: string }> = ({ text }) => {
  const [copied, setCopied] = React.useState(false);

  const onCopy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <button
      onClick={onCopy}
      className="flex size-7 items-center justify-center rounded text-slate-400 hover:text-white hover:bg-white/10 transition-colors"
      title="Copy"
    >
      {copied ? <CheckIcon className="size-3.5" /> : <CopyIcon className="size-3.5" />}
    </button>
  );
};

const extractCode = (children: React.ReactNode): string => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const el = React.Children.toArray(children).find((c) => React.isValidElement(c)) as any;
  return String(el?.props?.children ?? "");
};

const extractLanguage = (children: React.ReactNode): string => {
  const codeEl = React.Children.toArray(children).find(
    (c) => React.isValidElement(c) && typeof c === "object",
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ) as React.ReactElement<{ className?: string }> | undefined;
  if (!codeEl?.props?.className) return "code";
  const match = codeEl.props.className.match(/language-(\w+)/);
  return match?.[1] ?? "code";
};

export const MarkdownText: React.FC<MarkdownTextProps> = ({ content, className }) => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const components: Record<string, (props: any) => React.ReactElement> = {
    wrapper: ({ children }: { children: React.ReactNode }) => (
      <div className={className}>{children}</div>
    ),
    h1: ({ children }: { children: React.ReactNode }) => (
      <h1 className="mb-2 mt-4 text-base font-semibold first:mt-0">{children}</h1>
    ),
    h2: ({ children }: { children: React.ReactNode }) => (
      <h2 className="mb-1.5 mt-3 text-sm font-semibold first:mt-0">{children}</h2>
    ),
    h3: ({ children }: { children: React.ReactNode }) => (
      <h3 className="mb-1 mt-2.5 text-sm font-medium first:mt-0">{children}</h3>
    ),
    h4: ({ children }: { children: React.ReactNode }) => (
      <h4 className="mb-1 mt-2 text-sm font-medium first:mt-0">{children}</h4>
    ),
    p: ({ children }: { children: React.ReactNode }) => (
      <p className="mb-2.5 leading-normal first:mt-0 last:mb-0">{children}</p>
    ),
    a: ({ href, children }: { href?: string; children: React.ReactNode }) => (
      <a
        href={href}
        className="text-blue-400 underline underline-offset-2 hover:text-blue-300"
        target="_blank"
        rel="noopener noreferrer"
      >
        {children}
      </a>
    ),
    blockquote: ({ children }: { children: React.ReactNode }) => (
      <blockquote className="my-2.5 border-l-2 border-slate-500 pl-3 italic text-slate-400">
        {children}
      </blockquote>
    ),
    ul: ({ children }: { children: React.ReactNode }) => (
      <ul className="mb-2 ml-4 list-disc marker:text-slate-500 [&>li]:mt-1">
        {children}
      </ul>
    ),
    ol: ({ children }: { children: React.ReactNode }) => (
      <ol className="mb-2 ml-4 list-decimal marker:text-slate-500 [&>li]:mt-1">
        {children}
      </ol>
    ),
    li: ({ children }: { children: React.ReactNode }) => (
      <li className="leading-normal">{children}</li>
    ),
    code: ({ className: codeClassName, children }: { className?: string; children: React.ReactNode }) => {
      const isInline = !codeClassName?.includes("language-");
      if (isInline) {
        return (
          <code className="rounded-md border border-white/10 bg-white/5 px-1.5 py-0.5 font-mono text-[0.85em] text-slate-300">
            {children}
          </code>
        );
      }
      return <code className={codeClassName}>{children}</code>;
    },
    pre: ({ children }: { children: React.ReactNode }) => {
      const lang = extractLanguage(children);
      const code = extractCode(children);
      return (
        <div className="group relative mb-2.5 overflow-hidden rounded-lg border border-white/10 bg-white/5">
          <div className="flex items-center justify-between border-b border-white/10 px-3 py-1.5">
            <span className="text-xs font-medium lowercase text-slate-500">{lang}</span>
            <CopyButton text={code} />
          </div>
          <pre className="overflow-x-auto p-3 text-xs leading-relaxed text-slate-300">
            {children}
          </pre>
        </div>
      );
    },
    table: ({ children }: { children: React.ReactNode }) => (
      <div className="mb-2.5 w-full overflow-x-auto">
        <table className="w-full border-separate border-spacing-0">{children}</table>
      </div>
    ),
    thead: ({ children }: { children: React.ReactNode }) => <thead className="bg-white/5">{children}</thead>,
    th: ({ children }: { children: React.ReactNode }) => (
      <th className="border border-white/10 px-2 py-1.5 text-left text-xs font-medium first:rounded-tl-lg last:rounded-tr-lg">
        {children}
      </th>
    ),
    td: ({ children }: { children: React.ReactNode }) => (
      <td className="border border-b border-l border-r border-white/10 px-2 py-1.5 text-left text-xs first:border-t-0">
        {children}
      </td>
    ),
    tr: ({ children }: { children: React.ReactNode }) => (
      <tr className="p-0 last:border-b-0">{children}</tr>
    ),
    hr: () => <hr className="my-2 border-white/10" />,
    img: ({ src, alt }: { src?: string; alt?: string }) => (
      <img src={src} alt={alt} className="max-w-full rounded-lg" />
    ),
  };

  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {content}
    </ReactMarkdown>
  );
};
