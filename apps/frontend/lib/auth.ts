import NextAuth from "next-auth";
import GitHub from "next-auth/providers/github";

declare module "next-auth" {
  interface Session {
    accessToken?: string;
    user: {
      id?: string;
      name?: string | null;
      email?: string | null;
      image?: string | null;
      login?: string;
      sub?: string;
      bio?: string | null;
      company?: string | null;
      location?: string | null;
      blog?: string | null;
      public_repos?: number;
      followers?: number;
      following?: number;
    };
  }
}

const githubClientId = process.env.AUTH_GITHUB_ID;
const githubClientSecret = process.env.AUTH_GITHUB_SECRET;

export const { handlers, auth, signIn, signOut } = NextAuth({
  trustHost: true,
  providers: [
    GitHub({
      clientId: githubClientId,
      clientSecret: githubClientSecret,
      authorization: {
        params: {
          scope: "read:user user:email repo",
        },
      },
      // GitHub OAuth 不完全遵循 OIDC 规范，手动覆盖验证逻辑
      checks: ["none"],
    }),
  ],
  callbacks: {
    async jwt({ token, account, profile }) {
      if (account?.provider === "github") {
        // 保存 GitHub access_token 用于后续 API 操作
        token.accessToken = account.access_token;
        token.githubId = account.providerAccountId;

        if (profile) {
          token.login = profile.login;
          token.avatarUrl = profile.avatar_url;
          token.bio = profile.bio;
          token.company = profile.company;
          token.location = profile.location;
          token.blog = profile.blog;
          token.publicRepos = profile.public_repos;
          token.followers = profile.followers;
          token.following = profile.following;
        }
      }
      return token;
    },
    async session({ session, token }) {
      if (token.sub) {
        session.user.id = token.sub;
        session.user.sub = token.sub;
      }
      // 将 GitHub access_token 传递到前端 session
      if (token.accessToken) {
        session.accessToken = token.accessToken as string;
      }
      if (token.login) session.user.login = token.login as string;
      if (token.avatarUrl) session.user.image = token.avatarUrl as string;
      if (token.bio) session.user.bio = token.bio as string;
      if (token.company) session.user.company = token.company as string;
      if (token.location) session.user.location = token.location as string;
      if (token.blog) session.user.blog = token.blog as string;
      if (token.publicRepos) session.user.public_repos = token.publicRepos as number;
      if (token.followers) session.user.followers = token.followers as number;
      if (token.following) session.user.following = token.following as number;
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
