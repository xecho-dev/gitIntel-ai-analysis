import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "分析历史 - GitIntel",
  description: "查看和管理您过去的 GitHub 仓库分析记录，了解代码健康度演变趋势。",
  robots: {
    index: false,
    follow: false,
  },
};

export default function HistoryLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}