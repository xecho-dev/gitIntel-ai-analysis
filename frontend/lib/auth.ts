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

const githubClientId =
  process.env.AUTH_GITHUB_ID ?? process.env.GITHUB_CLIENT_ID;
const githubClientSecret =
  process.env.AUTH_GITHUB_LOGIN ?? process.env.GITHUB_CLIENT_SECRET;

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    githubClientId && githubClientSecret
      ? GitHub({ clientId: githubClientId, clientSecret: githubClientSecret })
      : GitHub({}),
  ],
  callbacks: {
    async jwt({ token, account, profile }) {
      if (account?.provider === "github" && profile) {
        // GitHub profile 使用 snake_case（与数据库字段对齐）
        token.login = profile.login;
        token.avatarUrl = profile.avatar_url;
        token.githubId = account.providerAccountId;
        token.bio = profile.bio;
        token.company = profile.company;
        token.location = profile.location;
        token.blog = profile.blog;
        token.publicRepos = profile.public_repos;
        token.followers = profile.followers;
        token.following = profile.following;
      }
      return token;
    },
    async session({ session, token }) {
      if (token.sub) {
        session.user.id = token.sub;
        session.user.sub = token.sub;
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
