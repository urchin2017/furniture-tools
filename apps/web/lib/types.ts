// 与 Supabase glossary 表对齐的类型
export interface GlossaryEntry {
  id: string;
  source_lang: string;
  target_lang: string;
  source_term: string;
  target_term: string;
  domain: string;
  note: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export const LANGS: { value: string; label: string }[] = [
  { value: "ja", label: "日本語" },
  { value: "en", label: "English" },
  { value: "zh", label: "中文" },
];

export function langLabel(code: string): string {
  return LANGS.find((l) => l.value === code)?.label ?? code;
}
