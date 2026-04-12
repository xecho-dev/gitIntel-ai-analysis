import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "账户管理 - GitIntel",
  description: "管理您的 GitIntel 账户、个人资料、订阅计划和 API 设置。",
  robots: {
    index: false,
    follow: false,
  },
};

export default function AccountLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}