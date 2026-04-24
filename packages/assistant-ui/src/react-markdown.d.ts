/* eslint-disable @typescript-eslint/no-explicit-any */
declare module "react-markdown" {
  import type { ReactNode, ComponentType } from "react";

  export interface ReactMarkdownProps {
    children?: ReactNode;
    remarkPlugins?: any[];
    rehypePlugins?: any[];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    components?: Record<string, ComponentType<any>>;
    className?: string;
  }

  const ReactMarkdown: ComponentType<ReactMarkdownProps>;
  export default ReactMarkdown;
}
