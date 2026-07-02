"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { LANGS, langLabel, type GlossaryEntry } from "@/lib/types";
import { parseAoa, buildTemplateAoa, keyOf } from "@/lib/glossaryImport";

const supabase = createClient();

export default function GlossaryManager() {
  const [entries, setEntries] = useState<GlossaryEntry[]>([]);
  const [userId, setUserId] = useState<string | null>(null);
  const [dir, setDir] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  // 新增表单
  const [nSource, setNSource] = useState("ja");
  const [nTarget, setNTarget] = useState("zh");
  const [nSourceTerm, setNSourceTerm] = useState("");
  const [nTargetTerm, setNTargetTerm] = useState("");
  const [nDomain, setNDomain] = useState("");
  const [adding, setAdding] = useState(false);

  // 行内编辑 / 行内删除确认
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  // 导入
  const [importing, setImporting] = useState(false);
  const [importMsg, setImportMsg] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    // Supabase(PostgREST) 单次最多返回 1000 行，故分页取全
    const pageSize = 1000;
    const acc: GlossaryEntry[] = [];
    for (let from = 0; ; from += pageSize) {
      const { data, error } = await supabase
        .from("glossary")
        .select("*")
        .order("source_term", { ascending: true })
        .order("id", { ascending: true })
        .range(from, from + pageSize - 1);
      if (error) {
        setErr(error.message);
        break;
      }
      const batch = (data as GlossaryEntry[]) ?? [];
      acc.push(...batch);
      if (batch.length < pageSize) break;
    }
    setEntries(acc);
    setLoading(false);
  }, []);

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => setUserId(data.user?.id ?? null));
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  // 数据里实际存在的语向（源→目标），用于筛选下拉
  const directions = useMemo(() => {
    const seen = new Map<string, { source: string; target: string }>();
    for (const e of entries)
      seen.set(`${e.source_lang}:${e.target_lang}`, {
        source: e.source_lang,
        target: e.target_lang,
      });
    return [...seen.values()].sort((a, b) =>
      `${a.source}${a.target}`.localeCompare(`${b.source}${b.target}`),
    );
  }, [entries]);

  const filtered = useMemo(() => {
    let list = entries;
    if (dir !== "all") {
      const [s, t] = dir.split(":");
      list = list.filter((e) => e.source_lang === s && e.target_lang === t);
    }
    const q = search.trim().toLowerCase();
    if (q)
      list = list.filter(
        (e) =>
          e.source_term.toLowerCase().includes(q) ||
          e.target_term.toLowerCase().includes(q) ||
          e.domain.toLowerCase().includes(q),
      );
    return list;
  }, [entries, dir, search]);

  async function onAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!nSourceTerm.trim() || !nTargetTerm.trim()) return;
    if (nSource === nTarget) {
      setErr("源语言与目标语言不能相同");
      return;
    }
    setAdding(true);
    setErr(null);
    const { error } = await supabase.from("glossary").insert({
      source_lang: nSource,
      target_lang: nTarget,
      source_term: nSourceTerm.trim(),
      target_term: nTargetTerm.trim(),
      domain: nDomain.trim(),
      created_by: userId,
    });
    setAdding(false);
    if (error) {
      setErr(error.message);
      return;
    }
    setNSourceTerm("");
    setNTargetTerm("");
    setNDomain("");
    load();
  }

  async function doDelete(id: string) {
    setErr(null);
    const { error } = await supabase.from("glossary").delete().eq("id", id);
    if (error) {
      setErr(error.message);
      return;
    }
    setEntries((prev) => prev.filter((e) => e.id !== id));
    setConfirmingId(null);
  }

  function startEdit(entry: GlossaryEntry) {
    setEditingId(entry.id);
    setEditValue(entry.target_term);
  }
  async function saveEdit(id: string) {
    const v = editValue.trim();
    if (!v) return;
    setErr(null);
    const { error } = await supabase
      .from("glossary")
      .update({ target_term: v })
      .eq("id", id);
    if (error) {
      setErr(error.message);
      return;
    }
    setEntries((prev) =>
      prev.map((e) => (e.id === id ? { ...e, target_term: v } : e)),
    );
    setEditingId(null);
  }

  async function onDownloadTemplate() {
    const XLSX = await import("xlsx");
    const ws = XLSX.utils.aoa_to_sheet(buildTemplateAoa());
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "术语表");
    XLSX.writeFile(wb, "术语表导入模板.xlsx");
  }

  async function onImportFile(ev: React.ChangeEvent<HTMLInputElement>) {
    const file = ev.target.files?.[0];
    if (!file) return;
    setImporting(true);
    setImportMsg(null);
    setErr(null);
    try {
      const XLSX = await import("xlsx");
      const buf = await file.arrayBuffer();
      const wb = XLSX.read(buf, { type: "array" });
      const ws = wb.Sheets[wb.SheetNames[0]];
      const raw = XLSX.utils.sheet_to_json(ws, {
        header: 1,
        blankrows: false,
        defval: "",
      }) as unknown[][];
      const aoa = raw.map((row) => row.map((c) => (c == null ? "" : String(c))));
      const res = parseAoa(aoa);
      if (res.fatal) {
        setErr(res.fatal);
        return;
      }
      if (res.rows.length === 0) {
        setImportMsg(
          `没有可导入的有效行${res.skipped ? `，跳过 ${res.skipped} 行` : ""}。`,
        );
        return;
      }
      // 统计新增 vs 替换
      const srcLangs = [...new Set(res.rows.map((r) => r.source_lang))];
      const { data: existing } = await supabase
        .from("glossary")
        .select("source_lang,target_lang,source_term,domain")
        .in("source_lang", srcLangs)
        .limit(100000);
      const seen = new Set(
        (existing ?? []).map((e) =>
          keyOf(e as unknown as Parameters<typeof keyOf>[0]),
        ),
      );
      let added = 0;
      let replaced = 0;
      for (const r of res.rows) {
        if (seen.has(keyOf(r))) replaced++;
        else added++;
      }
      // 分批 upsert（命中「源+目标+原文+领域」唯一键则替换译文/备注，否则新增）
      const payload = res.rows.map((r) => ({
        ...r,
        note: r.note || null,
        created_by: userId,
      }));
      for (let i = 0; i < payload.length; i += 500) {
        const chunk = payload.slice(i, i + 500);
        const { error } = await supabase
          .from("glossary")
          .upsert(chunk, {
            onConflict: "source_lang,target_lang,source_term,domain",
          });
        if (error) {
          setErr(`导入失败：${error.message}`);
          return;
        }
      }
      const tail =
        res.errors.length > 0
          ? `。问题 ${res.errors.length} 处：${res.errors.slice(0, 5).join("；")}${res.errors.length > 5 ? " …" : ""}`
          : "";
      setImportMsg(
        `导入完成：新增 ${added} 条，替换 ${replaced} 条${res.skipped ? `，跳过 ${res.skipped} 行` : ""}${tail}`,
      );
      await load();
    } catch (e) {
      setErr(`导入出错：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setImporting(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-semibold text-ink">术语表</h1>
          <p className="text-sm text-muted mt-1">
            单一真相源 · 报价翻译与图纸翻译共用 · 所有登录同事可增删改
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onDownloadTemplate}
            className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink hover:bg-bg"
          >
            下载模板
          </button>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={importing}
            className="rounded-lg bg-brand text-brand-ink px-3 py-2 text-sm font-medium disabled:opacity-60"
          >
            {importing ? "导入中…" : "⇪ 导入 Excel / CSV"}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx,.xls,.csv"
            onChange={onImportFile}
            className="hidden"
          />
          <span className="text-sm text-muted ml-1">
            共 <span className="text-ink font-medium">{filtered.length}</span> 条
            {dir !== "all"
              ? `（${langLabel(dir.split(":")[0])}→${langLabel(dir.split(":")[1])}）`
              : "（全部语向）"}
          </span>
        </div>
      </div>

      {/* 筛选 */}
      <div className="flex gap-3 flex-wrap">
        <select
          value={dir}
          onChange={(e) => setDir(e.target.value)}
          className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink"
        >
          <option value="all">全部语向</option>
          {directions.map((d) => (
            <option key={`${d.source}:${d.target}`} value={`${d.source}:${d.target}`}>
              {langLabel(d.source)}→{langLabel(d.target)}
            </option>
          ))}
        </select>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="搜索原文 / 译文 / 领域…"
          className="flex-1 min-w-[200px] rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-brand"
        />
      </div>

      {/* 新增 */}
      <form
        onSubmit={onAdd}
        className="bg-surface border border-border rounded-xl p-4 grid grid-cols-1 md:grid-cols-7 gap-3 items-end"
      >
        <div className="md:col-span-1">
          <label className="block text-xs text-muted mb-1">源语言</label>
          <select
            value={nSource}
            onChange={(e) => setNSource(e.target.value)}
            className="w-full rounded-lg border border-border bg-white px-2 py-2 text-sm"
          >
            {LANGS.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </select>
        </div>
        <div className="md:col-span-1">
          <label className="block text-xs text-muted mb-1">目标语言</label>
          <select
            value={nTarget}
            onChange={(e) => setNTarget(e.target.value)}
            className="w-full rounded-lg border border-border bg-white px-2 py-2 text-sm"
          >
            {LANGS.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </select>
        </div>
        <div className="md:col-span-2">
          <label className="block text-xs text-muted mb-1">原文</label>
          <input
            value={nSourceTerm}
            onChange={(e) => setNSourceTerm(e.target.value)}
            className="w-full rounded-lg border border-border bg-white px-2 py-2 text-sm outline-none focus:border-brand"
            placeholder="如 壁面 / 墙面"
          />
        </div>
        <div className="md:col-span-2">
          <label className="block text-xs text-muted mb-1">译文</label>
          <input
            value={nTargetTerm}
            onChange={(e) => setNTargetTerm(e.target.value)}
            className="w-full rounded-lg border border-border bg-white px-2 py-2 text-sm outline-none focus:border-brand"
            placeholder="如 墙面 / wall"
          />
        </div>
        <div className="md:col-span-1">
          <label className="block text-xs text-muted mb-1">领域（可空）</label>
          <input
            value={nDomain}
            onChange={(e) => setNDomain(e.target.value)}
            className="w-full rounded-lg border border-border bg-white px-2 py-2 text-sm outline-none focus:border-brand"
            placeholder="如 材料"
          />
        </div>
        <div className="md:col-span-7">
          <button
            type="submit"
            disabled={adding}
            className="rounded-lg bg-brand text-brand-ink px-4 py-2 text-sm font-medium disabled:opacity-60"
          >
            {adding ? "添加中…" : "＋ 添加词条"}
          </button>
        </div>
      </form>

      {err && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          {err}
        </p>
      )}
      {importMsg && (
        <p className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2">
          {importMsg}
        </p>
      )}

      {/* 表格 */}
      <div className="bg-surface border border-border rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-bg text-muted">
            <tr>
              <th className="text-left font-medium px-4 py-2 w-24">语向</th>
              <th className="text-left font-medium px-4 py-2">原文</th>
              <th className="text-left font-medium px-4 py-2">译文</th>
              <th className="text-left font-medium px-4 py-2 w-32">领域</th>
              <th className="text-right font-medium px-4 py-2 w-32">操作</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-muted">
                  加载中…
                </td>
              </tr>
            ) : filtered.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-muted">
                  没有词条
                </td>
              </tr>
            ) : (
              filtered.map((e) => (
                <tr key={e.id} className="border-t border-border">
                  <td className="px-4 py-2 text-muted whitespace-nowrap">
                    {langLabel(e.source_lang)}→{langLabel(e.target_lang)}
                  </td>
                  <td className="px-4 py-2 text-ink">{e.source_term}</td>
                  <td className="px-4 py-2 text-ink">
                    {editingId === e.id ? (
                      <input
                        value={editValue}
                        onChange={(ev) => setEditValue(ev.target.value)}
                        autoFocus
                        className="w-full rounded border border-brand px-2 py-1"
                      />
                    ) : (
                      e.target_term
                    )}
                  </td>
                  <td className="px-4 py-2 text-muted">{e.domain || "—"}</td>
                  <td className="px-4 py-2 text-right whitespace-nowrap">
                    {editingId === e.id ? (
                      <>
                        <button
                          onClick={() => saveEdit(e.id)}
                          className="text-brand hover:underline mr-3"
                        >
                          保存
                        </button>
                        <button
                          onClick={() => setEditingId(null)}
                          className="text-muted hover:underline"
                        >
                          取消
                        </button>
                      </>
                    ) : confirmingId === e.id ? (
                      <>
                        <span className="text-muted mr-2">确认删除？</span>
                        <button
                          onClick={() => doDelete(e.id)}
                          className="text-red-600 hover:underline mr-3"
                        >
                          确认
                        </button>
                        <button
                          onClick={() => setConfirmingId(null)}
                          className="text-muted hover:underline"
                        >
                          取消
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          onClick={() => {
                            setConfirmingId(e.id);
                            setEditingId(null);
                          }}
                          className="text-red-600 hover:underline ml-3 float-right"
                        >
                          删除
                        </button>
                        <button
                          onClick={() => startEdit(e)}
                          className="text-brand hover:underline"
                        >
                          编辑
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
