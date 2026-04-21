"use client";

import React from "react";

export const LandingFooter = () => (
  <footer className="py-20 border-t border-white/5 relative bg-[#10141a]">
    <div className="max-w-7xl mx-auto px-6">
      <div className="flex flex-col md:flex-row justify-between items-start gap-12">
        <div className="max-w-xs">
          <div className="font-bold text-2xl tracking-tighter text-blue-400 mb-4">GITINTEL AI.</div>
          <p className="text-xs text-slate-500 uppercase tracking-widest leading-loose">
            © 2026 GITINTEL AI. ENGINEERED FOR THE GLOBAL CODE PULSE.
          </p>
        </div>
        <div className="flex gap-12">
          <div className="flex flex-col gap-4">
            <h4 className="text-[10px] font-bold text-white uppercase tracking-[0.2em] mb-2">Platform</h4>
            <a href="#" className="text-xs text-slate-500 hover:text-white transition-all">DOCUMENTATION</a>
            <a href="#" className="text-xs text-slate-500 hover:text-white transition-all">API REFERENCE</a>
            <a href="#" className="text-xs text-slate-500 hover:text-white transition-all">PRIVACY POLICY</a>
          </div>
          <div className="flex flex-col gap-4">
            <h4 className="text-[10px] font-bold text-white uppercase tracking-[0.2em] mb-2">Connect</h4>
            <a href="#" className="text-xs text-slate-500 hover:text-white transition-all">GITHUB</a>
            <a href="#" className="text-xs text-slate-500 hover:text-white transition-all">TWITTER</a>
            <a href="#" className="text-xs text-slate-500 hover:text-white transition-all">DISCORD</a>
          </div>
        </div>
      </div>
    </div>
  </footer>
);
