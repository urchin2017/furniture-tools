import Link from "next/link";
import Hint from "@/components/Hint";

export default function QuotePage() {
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-ink">报价</h1>
      <div className="grid gap-4 sm:grid-cols-2">
        <Hint
          text="上传 PDF 技术图纸 + Excel 报价模板，自动提取产品、看图定外形尺寸、填表并渲染验证。"
          className="block"
        >
          <Link
            href="/quote/generate"
            className="block w-full bg-surface border border-border rounded-xl p-6 hover:border-accent transition-colors"
          >
            <div className="font-medium text-ink">报价单生成</div>
          </Link>
        </Hint>
        <Hint text="开发中：两份报价 Excel 逐项对比出报告。" className="block">
          <div className="w-full bg-surface border border-border rounded-xl p-6 opacity-60">
            <div className="flex items-center justify-between">
              <span className="font-medium text-ink">报价单对比</span>
              <span className="text-xs rounded px-1.5 py-0.5 bg-bg text-muted">开发中</span>
            </div>
          </div>
        </Hint>
      </div>
    </div>
  );
}
