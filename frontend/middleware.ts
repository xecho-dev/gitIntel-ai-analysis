export { auth as middleware } from "@/lib/auth";

export const config = {
  matcher: [
    "/((?!api/auth|login|/$|login|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
