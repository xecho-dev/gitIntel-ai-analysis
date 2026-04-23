import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,

  // Docker 部署：standalone 产出最小自包含构建产物
  output: "standalone",
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
  },

  // 图片域名配置（如果后续接入 CDN/OSS）
  images: {
    remotePatterns: [],
  },
};

export default nextConfig;
