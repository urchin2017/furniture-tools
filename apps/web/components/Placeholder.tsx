export default function Placeholder({
  title,
  items,
}: {
  title: string;
  items: string[];
}) {
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-ink">{title}</h1>
      <div className="bg-surface border border-border rounded-xl p-6">
        <p className="text-sm text-muted">本模块开发中，将包含：</p>
        <ul className="mt-3 space-y-1">
          {items.map((i) => (
            <li key={i} className="text-sm text-ink flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-accent" />
              {i}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
