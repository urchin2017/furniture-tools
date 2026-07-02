import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { cookies } from "next/headers";

// 服务端组件/Route Handler 用的 Supabase 客户端，携带用户会话 cookie。
export function createClient() {
  const cookieStore = cookies();
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet: { name: string; value: string; options: CookieOptions }[]) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options),
            );
          } catch {
            // 在 Server Component 里 set 会抛错，可忽略（由 middleware 负责刷新 cookie）。
          }
        },
      },
    },
  );
}
