import type { Metadata } from "next";
import { Inter, Space_Grotesk, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Header } from "@/components/layout/Header";
import { Background } from "@/components/layout/Background";
import Providers from "@/components/Providers";
import { WebSiteJsonLd, OrganizationJsonLd, SoftwareApplicationJsonLd } from "@/components/seo";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
});

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-headline",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: {
    default: "GitIntel AI Analysis - AI 驱动的 GitHub 仓库智能分析工具",
    template: "%s | GitIntel",
  },
  description:
    "GitIntel 利用 AI 技术对 GitHub 仓库进行深度架构分析、代码质量评估、依赖风险检测和优化建议，帮助开发者全面了解项目健康状况。",
  keywords: [
    "GitHub 分析",
    "AI 代码分析",
    "代码质量评估",
    "依赖风险检测",
    "架构分析工具",
    "DevOps",
    "代码审查",
    "安全漏洞扫描",
  ],
  authors: [{ name: "GitIntel Team", url: "https://gitintel.ai" }],
  creator: "GitIntel",
  metadataBase: new URL(process.env.NEXT_PUBLIC_BASE_URL || "http://gitintel.top"),
  alternates: {
    canonical: "/",
    languages: {
      "zh-CN": "/",
      en: "/en",
    },
  },
  openGraph: {
    type: "website",
    locale: "zh_CN",
    url: "/",
    siteName: "GitIntel",
    title: "GitIntel AI Analysis - AI 驱动的 GitHub 仓库智能分析工具",
    description:
      "利用 AI 技术对 GitHub 仓库进行深度架构分析、代码质量评估、依赖风险检测和优化建议。",
    images: [
      {
        url: "/og-image.png",
        width: 1200,
        height: 630,
        alt: "GitIntel - AI 驱动的代码分析平台",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "GitIntel AI Analysis",
    description: "AI 驱动的 GitHub 仓库智能分析工具",
    images: ["/og-image.png"],
    creator: "@gitintel",
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-video-preview": -1,
      "max-image-preview": "large",
      "max-snippet": -1,
    },
  },
  verification: {
    google: process.env.GOOGLE_SITE_VERIFICATION,
  },
  icons: {
    icon: "/favicon.ico",
    shortcut: "/favicon-16x16.png",
    apple: "/apple-touch-icon.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body
        className={`${inter.variable} ${spaceGrotesk.variable} ${jetbrainsMono.variable} font-sans antialiased`}
      >
        <Providers>
          <Background />
          <Header />
          <WebSiteJsonLd />
          <OrganizationJsonLd />
          <SoftwareApplicationJsonLd />
          <main className="pt-24 pb-12 px-6 lg:px-12 max-w-[1400px] mx-auto min-h-screen">
            {children}
          </main>
        </Providers>
      </body>
    </html>
  );
}
