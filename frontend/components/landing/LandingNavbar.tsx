"use client";

import React from "react";
import Link from "next/link";
import { Cpu } from "lucide-react";

export const LandingNavbar = () => (
  <nav className="fixed top-0 left-0 right-0 z-50 border-b border-white/5 bg-[#10141a]/80 backdrop-blur-md">
    <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
      <div className="flex items-center gap-8">
        <Link href="/" className="font-bold text-xl tracking-tighter text-white flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-[rgba(96,165,250,0.2)] flex items-center justify-center border border-blue-500/30">
            <Cpu className="w-5 h-5 text-blue-400" />
          </div>
          GitIntel
        </Link>
        <div className="hidden md:flex items-center gap-6">
          <a href="#features" className="text-sm font-medium text-slate-400 hover:text-white transition-colors">DOCS</a>
          <a href="#pricing" className="text-sm font-medium text-slate-400 hover:text-white transition-colors">PRICING</a>
          <a href="#labs" className="text-sm font-medium text-slate-400 hover:text-white transition-colors">ABOUT</a>
        </div>
      </div>
      <Link href="/login" className="px-5 py-2 rounded-lg bg-white/5 border border-white/10 hover:bg-white/10 transition-all text-sm font-semibold text-white">
        SIGN IN
      </Link>
    </div>
  </nav>
);
