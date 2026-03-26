import NextAuth from "next-auth";
import GitHub from "next-auth/providers/github";

declare module "next-auth" {
  interface Session {
    user: {
      id?: string;
      name?: string | null;
      email?: string | null;
      image?: string | null;
      login?: string;
      sub?: string;
    };
  }
}

const githubClientId =
  process.env.AUTH_GITHUB_ID ?? process.env.GITHUB_CLIENT_ID;
const githubClientSecret =
  process.env.AUTH_GITHUB_SECRET ?? process.env.GITHUB_CLIENT_SECRET;

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    // NextAuth 默认读 AUTH_GITHUB_*；显式传入仅当两套变量里至少凑齐一对，避免空字符串覆盖默认值
    githubClientId && githubClientSecret
      ? GitHub({ clientId: githubClientId, clientSecret: githubClientSecret })
      : GitHub({}),
  ],
  callbacks: {
    async jwt({ token, account, profile }) {
      if (account?.provider === "github") {
        token.login = (profile as { login?: string }).login;
        token.avatarUrl = (profile as { avatar_url?: string }).avatar_url;
        token.githubId = account.providerAccountId;
      }
      return token;
    },
    async session({ session, token }) {
      if (token.sub) {
        session.user.sub = token.sub;
      }
      if (token.login) {
        session.user.login = token.login as string;
      }
      if (token.avatarUrl) {
        session.user.image = token.avatarUrl as string;
      }
      return session;
    },
  },
  pages: {
    signIn: "/login",
    error: "/login",
  },
  session: {
    strategy: "jwt",
  },
});
