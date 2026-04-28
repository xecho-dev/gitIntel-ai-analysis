"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut, useSession } from "next-auth/react";
import { LayoutDashboard, History, UserCircle, LogOut, Github } from 'lucide-react';
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: '/workspace', label: '工作台', icon: LayoutDashboard },
  { href: '/history', label: '历史记录', icon: History },
  { href: '/account', label: '账户中心', icon: UserCircle },
];

export const Header = () => {
  const pathname = usePathname();
  const { data: session, status } = useSession();

  const isLoginPage = pathname === "/login";

  const handleSignOut = () => {
    signOut({ callbackUrl: "/" });
  };

  const goToAccount = () => {
    window.open(`https://github.com/${session?.user?.login}`, "_blank");
  };

  if (isLoginPage) return null;

  return (
    <>
    <header className="fixed top-0 w-full z-50 bg-[#10141a]/80 backdrop-blur-xl border-b border-white/5 flex justify-between items-center px-6 h-16">
      <div className="flex items-center gap-8">
        <div className="flex items-center gap-2">
          <span className="text-xl font-bold tracking-tighter text-blue-400 font-headline">
            GitIntel
          </span>
        </div>
        <nav className="hidden md:flex gap-1">
          {NAV_ITEMS.map((item) => {
            const isActive = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "px-4 py-2 text-sm tracking-tight transition-all duration-200 rounded flex items-center gap-2",
                  isActive
                    ? "text-blue-400 font-bold bg-blue-500/10"
                    : "text-slate-400 hover:text-slate-200 hover:bg-white/5"
                )}
              >
                <item.icon size={16} />
                {item.label}
              </Link>
            );
          })}

        </nav>
      </div>

      <div className="flex items-center gap-4">
        {/* <button className="hidden md:block px-4 py-1.5 bg-blue-500/10 text-blue-400 border border-blue-500/20 rounded-sm hover:bg-blue-500/20 transition-all font-medium text-xs uppercase tracking-widest">
          升级专业版
        </button> */}

        <div className="flex items-center gap-2">
          {/* <button className="p-2 text-slate-400 hover:bg-white/5 rounded-full transition-colors">
            <Bell size={20} />
          </button> */}

          {status === "loading" ? (
            <div className="w-8 h-8 rounded bg-slate-800 animate-pulse" />
          ) : session?.user ? (
            <>
              <div className="flex items-center gap-2 px-2" onClick={goToAccount}>
                <Github size={14} className="text-slate-400" />
                <span className="text-xs text-slate-300 hidden md:block">
                  {(session.user as { login?: string }).login ?? session.user.name}
                </span>
              </div>
              <div className="w-8 h-8 rounded overflow-hidden border border-white/10">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={session.user.image ?? ""}
                  alt={session.user.name ?? "avatar"}
                  className="w-full h-full object-cover"
                />
              </div>
              <button
                onClick={handleSignOut}
                className="p-2 text-slate-400 hover:bg-white/5 rounded-full transition-colors"
                title="退出登录"
              >
                <LogOut size={20} />
              </button>
            </>
          ) : (
            <Link
              href="/login"
              className="flex items-center gap-2 px-3 py-1.5 bg-blue-500 text-white text-xs font-medium rounded hover:bg-blue-600 transition-colors"
            >
              <Github size={14} />
              登录
            </Link>
          )}
        </div>
      </div>
    </header>

    </>
  );
};
