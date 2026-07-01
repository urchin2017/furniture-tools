"use client";

import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

export default function LogoutButton() {
  const router = useRouter();
  async function onLogout() {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/login");
    router.refresh();
  }
  return (
    <button
      onClick={onLogout}
      className="text-sm text-muted hover:text-ink border border-border rounded-lg px-3 py-1.5"
    >
      退出
    </button>
  );
}
