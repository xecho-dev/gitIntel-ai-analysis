import React from "react";
import { cn } from "@/lib/utils";

interface GlassCardProps {
  children: React.ReactNode;
  className?: string;
  glow?: boolean;
}

export const GlassCard = ({ children, className, glow = false }: GlassCardProps) => (
  <div
    className={cn(
      "bg-[#1c2026]/40 backdrop-blur-xl border border-white/5 rounded-xl overflow-hidden",
      glow && "shadow-[0_0_20px_rgba(172,199,255,0.05)]",
      className
    )}
  >
    {children}
  </div>
);
