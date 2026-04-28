import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,

  // Docker 部署：standalone 产出最小自包含构建产物
  output: "standalone",
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
  },

  // 关键：确保 Next.js 在构建时正确处理 workspace 包中的 Tailwind 类名提取
  transpilePackages: [
    "@gitintel/ui",
    "@gitintel/types",
  ],

  // 确保 CSS 文件被包含在 standalone 构建产物中
  outputFileTracingIncludes: {
    "/**": [
      "./.next/static/css/**/*.css",
    ],
  },

  // 图片域名配置（如果后续接入 CDN/OSS）
  images: {
    remotePatterns: [],
  },
};

export default nextConfig;
