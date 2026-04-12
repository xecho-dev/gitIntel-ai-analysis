import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "登录 - GitIntel",
  description: "使用 GitHub 账号登录 GitIntel，开始 AI 驱动的代码分析之旅。",
  robots: {
    index: false,
    follow: false,
  },
};

export default function LoginLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}