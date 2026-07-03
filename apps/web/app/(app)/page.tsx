import Link from "next/link";
import Hint from "@/components/Hint";

const CARDS = [
  {
    href: "/quote",
    title: "报价",
    desc: "报价单生成、报价单对比",
    ready: false,
  },
  {
    href: "/drawings",
    title: "图纸",
    desc: "图纸翻译、改版差异对比",
    ready: false,
  },
  {
    href: "/shipping-marks",
    title: "唛头",
    desc: "唛头生成",
    ready: false,
  },
  {
    href: "/glossary",
    title: "术语表",
    desc: "日→中术语，报价与翻译共用",
    ready: true,
  },
];

export default function Dashboard() {
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <h1 className="text-xl font-semibold text-ink">工作台</h1>
        <Hint text="阶段 0 · 地基已就绪。术语表可用，其余模块开发中。" />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {CARDS.map((c) => (
          <Hint key={c.href} text={c.desc} className="block">
            <Link
              href={c.href}
              className="block w-full bg-surface border border-border rounded-xl p-5 hover:border-brand transition-colors"
            >
              <div className="flex items-center justify-between">
                <span className="font-medium text-ink">{c.title}</span>
                <span
                  className={`text-xs rounded px-1.5 py-0.5 ${
                    c.ready ? "bg-green-100 text-green-700" : "bg-bg text-muted"
                  }`}
                >
                  {c.ready ? "可用" : "开发中"}
                </span>
              </div>
            </Link>
          </Hint>
        ))}
      </div>
    </div>
  );
}
