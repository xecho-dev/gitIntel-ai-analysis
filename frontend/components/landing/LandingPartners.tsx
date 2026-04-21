"use client";

import React from "react";

export const LandingPartners = () => (
  <div className="py-20 border-y border-white/5">
    <div className="max-w-7xl mx-auto px-6">
      <p className="text-center text-[10px] uppercase tracking-[0.5em] text-slate-600 mb-12">
        Trusted by engineering teams at
      </p>
      <div className="flex flex-wrap justify-center items-center gap-16 md:gap-32 grayscale opacity-20 hover:grayscale-0 hover:opacity-100 transition-all">
        <span className="font-bold text-2xl tracking-tighter">NEURAL_CORE</span>
        <span className="font-bold text-xl tracking-[0.2em]">CYBERFLOW</span>
        <span className="font-medium text-2xl">DATAVOID</span>
        <span className="font-light text-2xl tracking-tight italic">VOID_NULL</span>
      </div>
    </div>
  </div>
);
