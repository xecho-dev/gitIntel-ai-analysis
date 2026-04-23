import { NextResponse } from "next/server";
import { auth } from "@/lib/auth";

/**
 * GET /api/auth/session-full
 * 返回完整的 session（包含 accessToken 等自定义字段）
 * NextAuth 默认的 /api/auth/session 只返回基本字段
 */
export async function GET() {
  const session = await auth();

  if (!session) {
    return NextResponse.json({ accessToken: null, user: null });
  }

  return NextResponse.json({
    accessToken: session.accessToken ?? null,
    user: session.user,
  });
}
