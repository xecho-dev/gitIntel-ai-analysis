"use client";

import React from "react";
import { motion } from "motion/react";
import { signOut } from "next-auth/react";
import {
  Github,
  Check,
  Zap,
  CreditCard,
  FileText,
  Settings,
  Key,
  ArrowUpRight,
  RefreshCw,
  Trash2,
  Copy,
  ChevronRight,
  LogOut,
  AlertTriangle,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";

interface GitHubProfile {
  login?: string;
  name?: string;
  email?: string;
  image?: string;
  bio?: string;
  company?: string;
  location?: string;
  blog?: string;
  public_repos?: number;
  followers?: number;
  following?: number;
  created_at?: string;
}

export default function AccountPage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const profile = session?.user as (GitHubProfile & { login?: string }) | undefined;

  if (status === "loading") {
    return (
      <div className="space-y-8 animate-pulse">
        <div className="h-12 w-64 bg-white/5 rounded" />
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          <div className="lg:col-span-4 h-96 bg-white/5 rounded-lg" />
          <div className="lg:col-span-8 h-96 bg-white/5 rounded-lg" />
        </div>
      </div>
    );
  }

  if (!session || !profile) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] text-center space-y-4">
        <AlertTriangle size={48} className="text-amber-400" />
        <h2 className="text-2xl font-bold">请先登录</h2>
        <p className="text-slate-400">登录后即可查看账户信息</p>
        <button
          onClick={() => router.push("/login")}
          className="px-6 py-2.5 bg-blue-500 text-white rounded-md hover:bg-blue-600 transition-colors font-medium"
        >
          去登录
        </button>
      </div>
    );
  }

  const formatDate = (dateStr?: string) => {
    if (!dateStr) return "未知";
    return new Date(dateStr).toLocaleDateString("zh-CN", {
      year: "numeric",
      month: "long",
      day: "numeric",
    });
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      className="space-y-12"
    >
      <div>
        <h1 className="text-4xl font-black tracking-tight mb-2">
          账户与订阅
        </h1>
        <p className="text-slate-400">
          管理您的个人资料、订阅计划和系统配置
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <GlassCard className="lg:col-span-4 p-8 flex flex-col items-center text-center">
          <div className="relative mb-6">
            <div className="w-24 h-24 rounded-full p-1 bg-gradient-to-tr from-blue-400 to-purple-400">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={profile.image ?? `https://github.com/${profile.login}.png`}
                alt={profile.name ?? profile.login ?? "avatar"}
                className="w-full h-full rounded-full bg-[#10141a] border-4 border-[#10141a] object-cover"
              />
            </div>
            <div className="absolute bottom-0 right-0 w-6 h-6 bg-emerald-400 rounded-full border-4 border-[#10141a] flex items-center justify-center">
              <Check
                size={12}
                className="text-[#002112]"
                strokeWidth={3}
              />
            </div>
          </div>
          <h2 className="text-2xl font-bold mb-1">{profile.name ?? profile.login}</h2>
          {profile.login && (
            <div className="flex items-center gap-2 text-blue-400 text-sm font-mono mb-4">
              <Github size={14} />
              github.com/{profile.login}
            </div>
          )}
          {profile.bio && (
            <p className="text-slate-400 text-xs mb-4">{profile.bio}</p>
          )}
          <div className="w-full pt-6 border-t border-white/5 text-left space-y-4">
            {profile.location && (
              <div className="flex justify-between text-sm">
                <span className="text-slate-500">位置</span>
                <span className="font-medium">{profile.location}</span>
              </div>
            )}
            {profile.company && (
              <div className="flex justify-between text-sm">
                <span className="text-slate-500">公司</span>
                <span className="font-medium">{profile.company}</span>
              </div>
            )}
            <div className="flex justify-between text-sm">
              <span className="text-slate-500">仓库</span>
              <span className="font-medium">{profile.public_repos ?? 0}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-slate-500">粉丝</span>
              <span className="font-medium">{profile.followers ?? 0}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-slate-500">加入日期</span>
              <span className="font-medium">{formatDate(profile.created_at)}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-slate-500">账户角色</span>
              <span className="font-medium">技术专家 (Architect)</span>
            </div>
          </div>
          <button
            onClick={() => signOut({ callbackUrl: "/login" })}
            className="mt-6 w-full py-2.5 border border-rose-500/20 text-rose-400 hover:bg-rose-500/10 transition-colors rounded-sm font-medium flex items-center justify-center gap-2"
          >
            <LogOut size={14} />
            退出登录
          </button>
        </GlassCard>

        <div className="lg:col-span-8 space-y-6">
          <GlassCard className="p-8 relative overflow-hidden group" glow>
            <div className="absolute top-0 right-0 p-6 opacity-10">
              <Zap size={96} />
            </div>
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-8 relative z-10">
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <Badge variant="tertiary">Premium Pro</Badge>
                  <span className="text-emerald-400 text-xs">年度订阅</span>
                </div>
                <h3 className="text-3xl font-bold">专业版订阅</h3>
              </div>
              <div className="text-right">
                <p className="text-slate-500 text-sm mb-1">距离下次结算</p>
                <p className="text-xl font-bold font-mono">
                  14 天{" "}
                  <span className="text-slate-600 font-normal text-sm">
                    / 2024.11.20
                  </span>
                </p>
              </div>
            </div>

            <div className="space-y-6 relative z-10">
              <div>
                <div className="flex justify-between text-sm mb-2 font-mono">
                  <span>AI 扫描额度 (本月)</span>
                  <span>78 / 200</span>
                </div>
                <div className="h-2 w-full bg-[#31353c] rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-blue-400 to-purple-400"
                    style={{ width: "39%" }}
                  />
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="bg-[#0a0e14] p-4 rounded-sm border border-white/5">
                  <p className="text-xs text-slate-500 mb-1">存储空间</p>
                  <p className="text-lg font-bold font-mono">
                    4.2 GB{" "}
                    <span className="text-xs font-normal text-slate-600">
                      / 10GB
                    </span>
                  </p>
                </div>
                <div className="bg-[#0a0e14] p-4 rounded-sm border border-white/5">
                  <p className="text-xs text-slate-500 mb-1">导出报告</p>
                  <p className="text-lg font-bold font-mono">
                    12{" "}
                    <span className="text-xs font-normal text-slate-600">
                      / 不限
                    </span>
                  </p>
                </div>
                <div className="bg-[#0a0e14] p-4 rounded-sm border border-white/5">
                  <p className="text-xs text-slate-500 mb-1">API 调用</p>
                  <p className="text-lg font-bold font-mono">
                    1,402{" "}
                    <span className="text-xs font-normal text-slate-600">
                      / 5k
                    </span>
                  </p>
                </div>
              </div>
            </div>
          </GlassCard>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <GlassCard className="p-6 flex items-start gap-4 hover:bg-white/5 transition-colors cursor-pointer group">
              <div className="p-3 rounded-sm bg-blue-500/10 text-blue-400">
                <CreditCard size={24} />
              </div>
              <div className="flex-1">
                <h4 className="font-bold mb-1">管理支付方式</h4>
                <p className="text-xs text-slate-500">
                  修改您的信用卡或 PayPal 信息
                </p>
              </div>
              <ChevronRight
                className="text-slate-600 group-hover:text-blue-400 transition-colors"
                size={20}
              />
            </GlassCard>
            <GlassCard className="p-6 flex items-start gap-4 hover:bg-white/5 transition-colors cursor-pointer group">
              <div className="p-3 rounded-sm bg-emerald-500/10 text-emerald-400">
                <FileText size={24} />
              </div>
              <div className="flex-1">
                <h4 className="font-bold mb-1">账单历史</h4>
                <p className="text-xs text-slate-500">查看并下载过往发票</p>
              </div>
              <ChevronRight
                className="text-slate-600 group-hover:text-emerald-400 transition-colors"
                size={20}
              />
            </GlassCard>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <GlassCard className="p-8 flex flex-col border-l-2 border-blue-400">
          <div className="flex items-center gap-2 mb-6 text-blue-400">
            <Settings size={18} />
            <h3 className="font-bold uppercase tracking-wider text-sm">
              基本设置
            </h3>
          </div>
          <div className="space-y-6 flex-1">
            <div>
              <label className="block text-[10px] text-slate-500 uppercase tracking-widest mb-1">
                电子邮箱
              </label>
              <div className="flex items-center justify-between gap-4">
                <p className="text-sm font-medium">{profile.email ?? "未公开邮箱"}</p>
                <button className="text-[10px] text-blue-400 hover:underline uppercase font-bold">
                  更改
                </button>
              </div>
            </div>
            <div>
              <label className="block text-[10px] text-slate-500 uppercase tracking-widest mb-1">
                通知偏好
              </label>
              <div className="flex items-center justify-between py-2">
                <span className="text-sm">漏洞扫描提醒</span>
                <div className="w-8 h-4 bg-blue-500 rounded-full relative cursor-pointer">
                  <div className="absolute right-0.5 top-0.5 w-3 h-3 bg-blue-950 rounded-full" />
                </div>
              </div>
            </div>
          </div>
          <button className="mt-8 text-xs text-rose-400 font-medium flex items-center gap-2 hover:opacity-80 transition-opacity">
            <Trash2 size={14} />
            注销账户
          </button>
        </GlassCard>

        <GlassCard className="p-8 flex flex-col border-l-2 border-emerald-400">
          <div className="flex items-center gap-2 mb-6 text-emerald-400">
            <Key size={18} />
            <h3 className="font-bold uppercase tracking-wider text-sm">
              API 令牌
            </h3>
          </div>
          <div className="space-y-4 flex-1">
            <div className="p-3 bg-[#0a0e14] border border-white/5 rounded-sm">
              <div className="flex justify-between items-center mb-2">
                <span className="text-[10px] font-mono text-slate-500">
                  PROD_KEY_01
                </span>
                <span className="text-[10px] text-emerald-400 font-bold">
                  已激活
                </span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <code className="text-xs text-slate-300 font-mono">
                  gi_sk_****************4k2l
                </code>
                <Copy
                  size={14}
                  className="text-slate-500 cursor-pointer hover:text-white transition-colors"
                />
              </div>
            </div>
            <p className="text-[10px] text-slate-500 leading-relaxed">
              API 令牌允许第三方服务访问您的分析数据。请妥善保管，切勿泄露。
            </p>
          </div>
          <button className="mt-8 py-2 border border-emerald-400/20 text-emerald-400 text-xs hover:bg-emerald-500/10 transition-colors uppercase font-bold tracking-widest rounded-sm">
            创建新令牌
          </button>
        </GlassCard>

        <GlassCard className="p-8 flex flex-col border-l-2 border-purple-400">
          <div className="flex items-center gap-2 mb-6 text-purple-400">
            <ArrowUpRight size={18} />
            <h3 className="font-bold uppercase tracking-wider text-sm">
              方案管理
            </h3>
          </div>
          <div className="flex-1 space-y-4">
            <div className="flex items-center gap-4 group cursor-pointer p-2 -mx-2 hover:bg-white/5 transition-colors rounded-sm">
              <div className="w-10 h-10 bg-[#31353c] rounded-sm flex items-center justify-center">
                <Zap
                  size={20}
                  className="text-slate-500 group-hover:text-blue-400 transition-colors"
                />
              </div>
              <div>
                <p className="text-sm font-bold">升级到企业版</p>
                <p className="text-[10px] text-slate-500">
                  无限团队席位与私有化部署
                </p>
              </div>
            </div>
            <div className="flex items-center gap-4 group cursor-pointer p-2 -mx-2 hover:bg-white/5 transition-colors rounded-sm">
              <div className="w-10 h-10 bg-[#31353c] rounded-sm flex items-center justify-center">
                <RefreshCw
                  size={20}
                  className="text-slate-500 group-hover:text-purple-400 transition-colors"
                />
              </div>
              <div>
                <p className="text-sm font-bold">降级到基础版</p>
                <p className="text-[10px] text-slate-500">
                  仅保留基础扫描与历史记录
                </p>
              </div>
            </div>
          </div>
          <div className="mt-8 pt-4 border-t border-white/5">
            <p className="text-[10px] text-slate-600 italic">
              订阅受《GitIntel 服务条款》约束
            </p>
          </div>
        </GlassCard>
      </div>
    </motion.div>
  );
}
