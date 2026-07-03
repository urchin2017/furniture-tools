import Hint from "@/components/Hint";

export default function Placeholder({
  title,
  items,
}: {
  title: string;
  items: string[];
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <h1 className="text-xl font-semibold text-ink">{title}</h1>
        <span className="text-xs rounded px-1.5 py-0.5 bg-bg text-muted">开发中</span>
        <Hint text={`将包含：${items.join("；")}`} />
      </div>
    </div>
  );
}
