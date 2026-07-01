import LogoutButton from "./LogoutButton";

export default function Topbar({
  email,
  role,
}: {
  email: string;
  role: string;
}) {
  return (
    <header className="h-14 shrink-0 bg-surface border-b border-border flex items-center justify-end gap-4 px-6">
      <span className="text-sm text-muted">
        {email}
        {role === "admin" && (
          <span className="ml-2 rounded bg-accent/15 text-accent px-1.5 py-0.5 text-xs">
            管理员
          </span>
        )}
      </span>
      <LogoutButton />
    </header>
  );
}
