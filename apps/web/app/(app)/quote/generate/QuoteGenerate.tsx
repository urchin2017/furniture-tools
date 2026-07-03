"use client";

import { useEffect, useRef, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import Hint from "@/components/Hint";

const supabase = createClient();
const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/** 千分位格式化 token 数；缺失/未知显示 —。 */
function fmtTok(n?: number): string {
  return typeof n === "number" ? n.toLocaleString("en-US") : "—";
}

/** fetch + 网络错误重试（本机网络抖动）；连不上时给出可操作的中文报错。 */
async function fetchRetry(url: string, init: RequestInit, tries = 3): Promise<Response> {
  let lastErr: unknown;
  for (let i = 0; i < tries; i++) {
    try {
      return await fetch(url, init);
    } catch (e) {
      lastErr = e;
      await new Promise((r) => setTimeout(r, 1500 * (i + 1)));
    }
  }
  throw new Error(
    `无法连接后端服务（${API}）：${lastErr instanceof Error ? lastErr.message : String(lastErr)}。` +
      `请确认后端已启动（uvicorn，端口 8000）后重试。`,
  );
}

type JobFile = {
  bucket: string;
  path: string;
  name: string;
  display_name?: string;
  content_type: string;
  size: number;
};
type ProductRow = {
  row_code: string;
  page: number;
  W: number | null;
  D: number | null;
  H: number | null;
  qty: number | null;
  dim_source: string;
  confirm_dims?: string[];
};
type JobResult = {
  files: JobFile[];
  summary: {
    project: string;
    rows: number;
    raster_pages: number[];
    unconfirmed: string[];
    missing: string[];
    cost_usd: number;
    model?: string;
    input_tokens?: number;
    output_tokens?: number;
    cache_read_input_tokens?: number;
    cache_creation_input_tokens?: number;
    vision_calls?: number;
    warnings: string[];
    products: ProductRow[];
  };
};
type Job = {
  id: string;
  status: string;
  progress: number;
  output_files: JobResult | null;
  error: string | null;
};

type Phase = "idle" | "uploading" | "running" | "done" | "error";

export default function QuoteGenerate() {
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [templateFile, setTemplateFile] = useState<File | null>(null);
  const [project, setProject] = useState("");
  const [skipPages, setSkipPages] = useState("1");
  const [startRow, setStartRow] = useState(18);
  const [lastRow, setLastRow] = useState(50);
  const [requireVisual, setRequireVisual] = useState(false);

  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<JobResult | null>(null);
  const [links, setLinks] = useState<Record<string, string>>({});
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => stopPoll(), []);
  function stopPoll() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  async function signLinks(files: JobFile[]) {
    const out: Record<string, string> = {};
    for (const f of files) {
      const { data } = await supabase.storage.from(f.bucket).createSignedUrl(f.path, 3600);
      if (data?.signedUrl) out[f.path] = data.signedUrl;
    }
    setLinks(out);
  }

  function startPoll(jobId: string, token: string) {
    stopPoll();
    // 本机网络有 TLS 抖动，单次轮询失败很常见——连续多次失败才放弃，
    // 401/404 这类确定性错误则立刻停。
    let misses = 0;
    const MAX_MISSES = 8;
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${API}/api/jobs/${jobId}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.status === 401 || res.status === 404) {
          throw Object.assign(new Error(`查询任务失败（HTTP ${res.status}）`), { fatal: true });
        }
        if (!res.ok) throw new Error(`查询任务失败（HTTP ${res.status}）`);
        misses = 0;
        const job: Job = await res.json();
        setProgress(job.progress ?? 0);
        if (job.status === "done") {
          stopPoll();
          setResult(job.output_files);
          setPhase("done");
          if (job.output_files?.files) await signLinks(job.output_files.files);
        } else if (job.status === "error") {
          stopPoll();
          setErr(job.error || "任务执行失败");
          setPhase("error");
        }
      } catch (e) {
        const fatal = typeof e === "object" && e !== null && (e as { fatal?: boolean }).fatal;
        misses += 1;
        if (!fatal && misses < MAX_MISSES) return; // 偶发失败：继续下一轮
        stopPoll();
        setErr(e instanceof Error ? e.message : String(e));
        setPhase("error");
      }
    }, 2500);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!pdfFile || !templateFile) {
      setErr("请同时选择图纸 PDF 和报价模板 Excel");
      return;
    }
    // Supabase 存储桶单文件上限 50MB，超限上传会被掐断（表现为 Failed to fetch）
    const MAX_MB = 50;
    for (const f of [pdfFile, templateFile]) {
      if (f.size > MAX_MB * 1024 * 1024) {
        setErr(
          `文件「${f.name}」有 ${(f.size / 1024 / 1024).toFixed(1)}MB，超过存储上限 ${MAX_MB}MB。` +
            `图纸 PDF 请先压缩（位图图纸可无损保留文字层、只压图片）再上传。`,
        );
        return;
      }
    }
    setErr(null);
    setResult(null);
    setLinks({});
    setPhase("uploading");
    setProgress(0);
    try {
      const { data: sessionData } = await supabase.auth.getSession();
      const token = sessionData.session?.access_token;
      if (!token) throw new Error("登录状态失效，请重新登录");

      // 走后端中转上传：浏览器直传 Supabase 在慢上行/抖动网络下大文件会断，
      // 本地 API 内网秒传，storage 那一跳由服务端带重试完成。
      const uploadOne = async (file: File): Promise<string> => {
        const fd = new FormData();
        fd.append("file", file);
        fd.append("purpose", "quote");
        const res = await fetchRetry(`${API}/api/uploads`, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
          body: fd,
        });
        if (!res.ok) {
          const detail = await res.text();
          throw new Error(`上传失败（HTTP ${res.status}）：${detail}`);
        }
        return (await res.json()).path as string;
      };
      const pdfKey = await uploadOne(pdfFile);
      const tplKey = await uploadOne(templateFile);

      const params = {
        pdf_path: pdfKey,
        template_path: tplKey,
        project: project.trim(),
        skip_pages: skipPages
          .split(/[,，\s]+/)
          .filter((s) => /^\d+$/.test(s))
          .map(Number),
        start_row: startRow,
        last_row: lastRow,
        require_visual: requireVisual,
      };
      const res = await fetchRetry(`${API}/api/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ feature: "quote_generate", params }),
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(`创建任务失败（HTTP ${res.status}）：${detail}`);
      }
      const job: Job = await res.json();
      setPhase("running");
      startPoll(job.id, token);
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : String(e2));
      setPhase("error");
    }
  }

  const busy = phase === "uploading" || phase === "running";
  const xlsxFile = result?.files.find((f) => f.name.endsWith(".xlsx"));
  const checkPngs = result?.files.filter((f) => f.content_type === "image/png") ?? [];

  return (
    <div className="space-y-4 max-w-4xl">
      <div className="flex items-center gap-2">
        <h1 className="text-xl font-semibold text-ink">报价单生成</h1>
        <Hint text="上传 PDF 技术图纸 + Excel 报价模板 → 自动提取产品、AI 看图定「外形/全体寸法」、填表、渲染验证。尺寸拿不准的行会标 ⚠ 淡黄高亮，务必人工复核后再发客户。" />
      </div>

      <form onSubmit={onSubmit} className="bg-surface border border-border rounded-xl p-6 space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <label
            className={`flex w-full items-center gap-2 rounded-lg border border-border bg-bg px-3 py-2 text-sm ${
              busy ? "pointer-events-none opacity-50" : "cursor-pointer"
            }`}
          >
            <span className="whitespace-nowrap rounded-md border border-border bg-surface px-2.5 py-1 text-ink">
              选择图纸 PDF
            </span>
            <span className="truncate text-muted">{pdfFile?.name ?? ""}</span>
            <input
              type="file"
              accept=".pdf,application/pdf"
              disabled={busy}
              onChange={(e) => setPdfFile(e.target.files?.[0] ?? null)}
              className="hidden"
            />
          </label>
          <label
            className={`flex w-full items-center gap-2 rounded-lg border border-border bg-bg px-3 py-2 text-sm ${
              busy ? "pointer-events-none opacity-50" : "cursor-pointer"
            }`}
          >
            <span className="whitespace-nowrap rounded-md border border-border bg-surface px-2.5 py-1 text-ink">
              选择模板 Excel
            </span>
            <span className="truncate text-muted">{templateFile?.name ?? ""}</span>
            <input
              type="file"
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              disabled={busy}
              onChange={(e) => setTemplateFile(e.target.files?.[0] ?? null)}
              className="hidden"
            />
          </label>
        </div>
        <div className="grid gap-4 sm:grid-cols-4">
          <label className="block text-sm sm:col-span-2">
            <span className="inline-flex items-center gap-1 text-ink">
              项目名 <Hint text="写入报价模板的 C11 单元格" />
            </span>
            <input
              type="text"
              value={project}
              disabled={busy}
              onChange={(e) => setProject(e.target.value)}
              placeholder="如：石垣島美咲町ビル"
              className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-1.5 text-ink"
            />
          </label>
          <label className="block text-sm">
            <span className="inline-flex items-center gap-1 text-ink">
              跳过页 <Hint text="封面等无品番的页码，逗号分隔（默认 1）" />
            </span>
            <input
              type="text"
              value={skipPages}
              disabled={busy}
              onChange={(e) => setSkipPages(e.target.value)}
              placeholder="1"
              className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-1.5 text-ink"
            />
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label className="block text-sm">
              <span className="text-ink">起始行</span>
              <input
                type="number"
                value={startRow}
                disabled={busy}
                onChange={(e) => setStartRow(Number(e.target.value))}
                className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-1.5 text-ink"
              />
            </label>
            <label className="block text-sm">
              <span className="text-ink">末行</span>
              <input
                type="number"
                value={lastRow}
                disabled={busy}
                onChange={(e) => setLastRow(Number(e.target.value))}
                className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-1.5 text-ink"
              />
            </label>
          </div>
        </div>
        <label className="inline-flex items-center gap-2 text-sm text-ink">
          <input
            type="checkbox"
            checked={requireVisual}
            disabled={busy}
            onChange={(e) => setRequireVisual(e.target.checked)}
          />
          终版闸门
          <Hint text="勾选后：有未确认 / 缺尺寸的项时拒绝出文件。不勾 = 允许出带 ⚠ 的草稿版。" />
        </label>
        <button
          type="submit"
          disabled={busy}
          className="rounded-lg bg-brand text-brand-ink px-4 py-2 text-sm font-medium disabled:opacity-50"
        >
          {phase === "uploading" ? "上传中…" : phase === "running" ? "生成中…" : "开始生成"}
        </button>
      </form>

      {busy && (
        <div className="bg-surface border border-border rounded-xl p-6 space-y-2">
          <div className="text-sm text-ink">
            {phase === "uploading" ? "正在上传文件…" : `正在生成（骨架 → AI 看图定尺寸 → 填表 → 渲染验证）… ${progress}%`}
          </div>
          <div className="h-2 rounded bg-bg overflow-hidden">
            <div className="h-full bg-accent transition-all" style={{ width: `${progress}%` }} />
          </div>
        </div>
      )}

      {err && (
        <div className="border border-red-300 bg-red-50 text-red-700 rounded-xl p-4 text-sm whitespace-pre-wrap">
          {err}
        </div>
      )}

      {phase === "done" && result && (
        <div className="space-y-4">
          <div className="bg-surface border border-border rounded-xl p-6 space-y-3">
            <h2 className="font-medium text-ink">生成完成 · {result.summary.rows} 行</h2>
            {xlsxFile && (
              <a
                href={links[xlsxFile.path]}
                download={xlsxFile.display_name || xlsxFile.name}
                className="inline-block rounded-lg bg-brand text-brand-ink px-4 py-2 text-sm font-medium"
              >
                下载 {xlsxFile.display_name || xlsxFile.name}
              </a>
            )}
            <div className="border-t border-border pt-3 text-xs">
              <div className="font-medium text-ink mb-1.5">
                AI 成本明细 <span className="text-muted">（下载前先过目）</span>
              </div>
              <dl className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-1 text-muted">
                <dt>模型</dt>
                <dd className="text-ink">{result.summary.model || "—"}</dd>
                {result.summary.vision_calls != null && (
                  <>
                    <dt>看图调用次数</dt>
                    <dd className="text-ink">{result.summary.vision_calls} 次（每页一次）</dd>
                  </>
                )}
                <dt>输入 tokens</dt>
                <dd className="text-ink">{fmtTok(result.summary.input_tokens)}</dd>
                <dt>输出 tokens</dt>
                <dd className="text-ink">{fmtTok(result.summary.output_tokens)}</dd>
                {(result.summary.cache_read_input_tokens ?? 0) +
                  (result.summary.cache_creation_input_tokens ?? 0) >
                  0 && (
                  <>
                    <dt>缓存 tokens（读 / 写）</dt>
                    <dd className="text-ink">
                      {fmtTok(result.summary.cache_read_input_tokens)} /{" "}
                      {fmtTok(result.summary.cache_creation_input_tokens)}
                    </dd>
                  </>
                )}
                <dt className="font-medium text-ink">合计成本</dt>
                <dd className="font-medium text-ink">US${result.summary.cost_usd}</dd>
              </dl>
              {result.summary.raster_pages.length > 0 && (
                <div className="text-muted mt-2">
                  光栅图纸页：{result.summary.raster_pages.join(", ")}（几何测量不可用，已走看图协议）
                </div>
              )}
            </div>
            {(result.summary.unconfirmed.length > 0 || result.summary.missing.length > 0) && (
              <div className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3">
                ⚠ 待人工复核：
                {result.summary.unconfirmed.length > 0 && ` 未确认 ${result.summary.unconfirmed.join("、")}；`}
                {result.summary.missing.length > 0 && ` 缺尺寸 ${result.summary.missing.join("、")}`}
              </div>
            )}
            {result.summary.warnings.length > 0 && (
              <ul className="text-xs text-muted list-disc pl-4 space-y-0.5">
                {result.summary.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            )}
          </div>

          <div className="bg-surface border border-border rounded-xl p-6 overflow-x-auto">
            <h3 className="font-medium text-ink mb-3">尺寸摘要（发出前与图纸逐项核对）</h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted border-b border-border">
                  <th className="py-1.5 pr-3">品番</th>
                  <th className="py-1.5 pr-3">页</th>
                  <th className="py-1.5 pr-3">W</th>
                  <th className="py-1.5 pr-3">D</th>
                  <th className="py-1.5 pr-3">H</th>
                  <th className="py-1.5 pr-3">数量</th>
                  <th className="py-1.5">尺寸来源</th>
                </tr>
              </thead>
              <tbody>
                {result.summary.products.map((p, i) => (
                  <tr key={`${p.row_code}-${i}`} className="border-b border-border/50 text-ink">
                    <td className="py-1.5 pr-3 font-medium">
                      {p.dim_source === "PENDING" ? "⚠ " : ""}
                      {p.row_code || "(空)"}
                    </td>
                    <td className="py-1.5 pr-3">{p.page}</td>
                    {(["W", "D", "H"] as const).map((dim) => (
                      <td
                        key={dim}
                        className="py-1.5 pr-3"
                        title={p.confirm_dims?.includes(dim) ? "待人工复核" : undefined}
                      >
                        {p.confirm_dims?.includes(dim) ? (
                          <span className="rounded bg-amber-100 px-1 text-amber-900">{p[dim] ?? "—"}</span>
                        ) : (
                          (p[dim] ?? "—")
                        )}
                      </td>
                    ))}
                    <td className="py-1.5 pr-3">{p.qty ?? "—"}</td>
                    <td className="py-1.5">{p.dim_source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {checkPngs.length > 0 && (
            <div className="bg-surface border border-border rounded-xl p-6 space-y-3">
              <h3 className="font-medium text-ink">渲染验证图（目视检查无溢出/对齐/⚠高亮）</h3>
              {checkPngs.map(
                (f) =>
                  links[f.path] && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      key={f.path}
                      src={links[f.path]}
                      alt={f.name}
                      className="w-full border border-border rounded-lg"
                    />
                  ),
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
