"use client";

import { SessionProvider, useSession } from "next-auth/react";
import { useEffect, useRef } from "react";

function ProfileSync() {
  const { data: session, status } = useSession();
  const syncedRef = useRef(false);

  useEffect(() => {
    if (
      status === "authenticated" &&
      session?.user?.login &&
      !syncedRef.current
    ) {
      syncedRef.current = true;
      fetch("/api/user/profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          login: session.user.login,
          name: session.user.name ?? null,
          email: session.user.email ?? null,
          avatar_url: session.user.image ?? null,
          bio: session.user.bio ?? undefined,
          location: session.user.location ?? undefined,
          company: session.user.company ?? undefined,
          blog: session.user.blog ?? undefined,
          public_repos: session.user.public_repos ?? 0,
          followers: session.user.followers ?? 0,
          following: session.user.following ?? 0,
        }),
      }).catch((err) => {
        console.error("[ProfileSync] 自动同步 GitHub 资料失败:", err);
      });
    }
  }, [status, session]);

  return null;
}

export default function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <ProfileSync />
      {children}
    </SessionProvider>
  );
}
