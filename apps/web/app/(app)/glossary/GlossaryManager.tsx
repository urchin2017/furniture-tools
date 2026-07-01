"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { LANGS, langLabel, type GlossaryEntry } from "@/lib/types";

const supabase = createClient();

export default function GlossaryManager() {
  const [entries, setEntries] = useState<GlossaryEntry[]>([]);
  const [userId, setUserId] = useState<string | null>(null);
  const [sourceLang, setSourceLang] = useState<string>("ja");
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

  // 行内编辑
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    let q = supabase
      .from("glossary")
      .select("*")
      .order("source_term", { ascending: true })
      .limit(2000);
    if (sourceLang !== "all") q = q.eq("source_lang", sourceLang);
    const { data, error } = await q;
    if (error) setErr(error.message);
    else setEntries((data as GlossaryEntry[]) ?? []);
    setLoading(false);
  }, [sourceLang]);

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => setUserId(data.user?.id ?? null));
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  const filtered = useMemo(() => {
    const s = search.trim().toLowerCase();
    if (!s) return entries;
    return entries.filter(
      (e) =>
        e.source_term.toLowerCase().includes(s) ||
        e.target_term.toLowerCase().includes(s) ||
        e.domain.toLowerCase().includes(s),
    );
  }, [entries, search]);

  async function onAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!nSourceTerm.trim() || !nTargetTerm.trim()) return;
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
    if (nSource === sourceLang || sourceLang === "all") load();
  }

  async function onDelete(id: string) {
    if (!confirm("确定删除这条词条？")) return;
    setErr(null);
    const { error } = await supabase.from("glossary").delete().eq("id", id);
    if (error) {
      setErr(error.message);
      return;
    }
    setEntries((prev) => prev.filter((e) => e.id !== id));
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

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-semibold text-ink">术语表</h1>
          <p className="text-sm text-muted mt-1">
            单一真相源 · 报价翻译与图纸翻译共用 · 所有登录同事可增删改
          </p>
        </div>
        <div className="text-sm text-muted">
          共 <span className="text-ink font-medium">{filtered.length}</span> 条
          {sourceLang !== "all" ? `（${langLabel(sourceLang)}→中）` : ""}
        </div>
      </div>

      {/* 筛选 */}
      <div className="flex gap-3 flex-wrap">
        <select
          value={sourceLang}
          onChange={(e) => setSourceLang(e.target.value)}
          className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink"
        >
          <option value="all">全部语向</option>
          {LANGS.map((l) => (
            <option key={l.value} value={l.value}>
              {l.label}→中
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
        className="bg-surface border border-border rounded-xl p-4 grid grid-cols-1 md:grid-cols-6 gap-3 items-end"
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
        <div className="md:col-span-2">
          <label className="block text-xs text-muted mb-1">原文</label>
          <input
            value={nSourceTerm}
            onChange={(e) => setNSourceTerm(e.target.value)}
            className="w-full rounded-lg border border-border bg-white px-2 py-2 text-sm outline-none focus:border-brand"
            placeholder="如 壁面"
          />
        </div>
        <div className="md:col-span-2">
          <label className="block text-xs text-muted mb-1">中文译文</label>
          <input
            value={nTargetTerm}
            onChange={(e) => setNTargetTerm(e.target.value)}
            className="w-full rounded-lg border border-border bg-white px-2 py-2 text-sm outline-none focus:border-brand"
            placeholder="如 墙面"
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
        <div className="md:col-span-6">
          <button
            type="submit"
            disabled={adding}
            className="rounded-lg bg-brand text-brand-ink px-4 py-2 text-sm font-medium disabled:opacity-60"
          >
            {adding ? "添加中…" : "＋ 添加词条"}
          </button>
          <input type="hidden" value={nTarget} readOnly />
        </div>
      </form>

      {err && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          {err}
        </p>
      )}

      {/* 表格 */}
      <div className="bg-surface border border-border rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-bg text-muted">
            <tr>
              <th className="text-left font-medium px-4 py-2 w-24">语向</th>
              <th className="text-left font-medium px-4 py-2">原文</th>
              <th className="text-left font-medium px-4 py-2">中文译文</th>
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
                    ) : (
                      <>
                        <button
                          onClick={() => startEdit(e)}
                          className="text-brand hover:underline mr-3"
                        >
                          编辑
                        </button>
                        <button
                          onClick={() => onDelete(e.id)}
                          className="text-red-600 hover:underline"
                        >
                          删除
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
