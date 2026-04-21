"use client";

import React, { useEffect } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import {
  LandingNavbar,
  LandingHero,
  LandingPartners,
  LandingFeatures,
  LandingLiveLab,
  LandingPricing,
  LandingFooter,
} from "@/components/landing";

export default function LandingPage() {
  const { data: session, status } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (status === "authenticated") {
      router.push("/workspace");
    }
  }, [status, router]);

  if (status === "loading") {
    return (
      <div className="min-h-screen bg-[#10141a] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-blue-400/20 rounded-full border-t-blue-400 animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#10141a]">
      <LandingNavbar />
      <main>
        <LandingHero />
        <LandingPartners />
        <LandingFeatures />
        <LandingLiveLab />
        <LandingPricing />
      </main>
      <LandingFooter />
    </div>
  );
}
