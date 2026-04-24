"use client";

import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { CheckIcon, CopyIcon } from "lucide-react";

type MarkdownTextProps = {
  children?: React.ReactNode;
  className?: string;
};

const CopyButton = ({ text }: { text: string }) => {
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
      title="复制"
    >
      {copied ? <CheckIcon className="size-3.5" /> : <CopyIcon className="size-3.5" />}
    </button>
  );
};

const extractCode = (children: React.ReactNode): string => {
  const el = React.Children.toArray(children).find((c) => React.isValidElement(c)) as React.ElementType;
  return String((el as React.ReactElement<{ children?: React.ReactNode }>)?.props?.children ?? "");
};

const extractLanguage = (children: React.ReactNode): string => {
  const codeEl = React.Children.toArray(children).find(
    (c) => React.isValidElement(c),
  ) as React.ReactElement<{ className?: string }> | undefined;
  if (!codeEl?.props?.className) return "code";
  const match = codeEl.props.className.match(/language-(\w+)/);
  return match?.[1] ?? "code";
};

export const MarkdownText = ({ children, className }: MarkdownTextProps) => {
  // Extract text content from children for markdown
  const content = React.useMemo(() => {
    if (typeof children === 'string') return children;
    if (Array.isArray(children)) {
      return children.map((c) => (typeof c === 'string' ? c : '')).join('');
    }
    return '';
  }, [children]);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const components: Record<string, (props: any) => React.ReactElement> = {
    wrapper: ({ children: c }: { children: React.ReactNode }) => (
      <div className={className}>{c}</div>
    ),
    h1: ({ children: c }: { children: React.ReactNode }) => (
      <h1 className="mb-2 mt-4 text-base font-semibold first:mt-0">{c}</h1>
    ),
    h2: ({ children: c }: { children: React.ReactNode }) => (
      <h2 className="mb-1.5 mt-3 text-sm font-semibold first:mt-0">{c}</h2>
    ),
    h3: ({ children: c }: { children: React.ReactNode }) => (
      <h3 className="mb-1 mt-2.5 text-sm font-medium first:mt-0">{c}</h3>
    ),
    h4: ({ children: c }: { children: React.ReactNode }) => (
      <h4 className="mb-1 mt-2 text-sm font-medium first:mt-0">{c}</h4>
    ),
    p: ({ children: c }: { children: React.ReactNode }) => (
      <p className="mb-2.5 leading-normal first:mt-0 last:mb-0">{c}</p>
    ),
    a: ({ href, children: c }: { href?: string; children: React.ReactNode }) => (
      <a
        href={href}
        className="text-blue-400 underline underline-offset-2 hover:text-blue-300"
        target="_blank"
        rel="noopener noreferrer"
      >
        {c}
      </a>
    ),
    blockquote: ({ children: c }: { children: React.ReactNode }) => (
      <blockquote className="my-2.5 border-l-2 border-slate-500 pl-3 italic text-slate-400">
        {c}
      </blockquote>
    ),
    ul: ({ children: c }: { children: React.ReactNode }) => (
      <ul className="mb-2 ml-4 list-disc marker:text-slate-500 [&>li]:mt-1">{c}</ul>
    ),
    ol: ({ children: c }: { children: React.ReactNode }) => (
      <ol className="mb-2 ml-4 list-decimal marker:text-slate-500 [&>li]:mt-1">{c}</ol>
    ),
    li: ({ children: c }: { children: React.ReactNode }) => <li className="leading-normal">{c}</li>,
    code: ({
      className: codeClassName,
      children: c,
    }: {
      className?: string;
      children: React.ReactNode;
    }) => {
      const isInline = !codeClassName?.includes('language-');
      if (isInline) {
        return (
          <code className="rounded-md border border-white/10 bg-white/5 px-1.5 py-0.5 font-mono text-[0.85em] text-slate-300">
            {c}
          </code>
        );
      }
      return <code className={codeClassName}>{c}</code>;
    },
    pre: ({ children: c }: { children: React.ReactNode }) => {
      const lang = extractLanguage(c);
      const code = extractCode(c);
      return (
        <div className="group relative mb-2.5 overflow-hidden rounded-lg border border-white/10 bg-white/5">
          <div className="flex items-center justify-between border-b border-white/10 px-3 py-1.5">
            <span className="text-xs font-medium lowercase text-slate-500">{lang}</span>
            <CopyButton text={code} />
          </div>
          <pre className="overflow-x-auto p-3 text-xs leading-relaxed text-slate-300">{c}</pre>
        </div>
      );
    },
    table: ({ children: c }: { children: React.ReactNode }) => (
      <div className="mb-2.5 w-full overflow-x-auto">
        <table className="w-full border-separate border-spacing-0">{c}</table>
      </div>
    ),
    thead: ({ children: c }: { children: React.ReactNode }) => (
      <thead className="bg-white/5">{c}</thead>
    ),
    th: ({ children: c }: { children: React.ReactNode }) => (
      <th className="border border-white/10 px-2 py-1.5 text-left text-xs font-medium first:rounded-tl-lg last:rounded-tr-lg">
        {c}
      </th>
    ),
    td: ({ children: c }: { children: React.ReactNode }) => (
      <td className="border border-b border-l border-r border-white/10 px-2 py-1.5 text-left text-xs first:border-t-0">
        {c}
      </td>
    ),
    tr: ({ children: c }: { children: React.ReactNode }) => (
      <tr className="p-0 last:border-b-0">{c}</tr>
    ),
    hr: () => <hr className="my-2 border-white/10" />,
    img: ({ src, alt }: { src?: string; alt?: string }) => (
      <img src={src} alt={alt} className="max-w-full rounded-lg" />
    ),
  };

  // If no content, return nothing
  if (!content) return null;

  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {content}
    </ReactMarkdown>
  );
};
