// 术语表导入 —— 纯逻辑（无 xlsx 依赖，方便单测）
// 输入：从 Excel/CSV 读出的二维数组(AOA)；输出：规范化词条 + 问题汇总。

export interface ParsedRow {
  source_lang: string;
  target_lang: string;
  source_term: string;
  target_term: string;
  domain: string;
  note: string;
}

export interface ParseResult {
  rows: ParsedRow[]; // 已去重（同键取最后一条）
  skipped: number; // 空行/缺必填而跳过的行数
  errors: string[]; // 人类可读的问题（含行号）
  fatal?: string; // 致命错误（表头缺失等），有则整份不导入
}

// 语言别名 → 规范码。键统一小写。
const LANG_ALIASES: Record<string, string> = {
  ja: "ja", jp: "ja", jpn: "ja", japanese: "ja",
  日: "ja", 日本語: "ja", 日文: "ja", 日语: "ja", 日本语: "ja", 日本: "ja",
  en: "en", eng: "en", english: "en",
  英: "en", 英文: "en", 英语: "en", 英語: "en",
  zh: "zh", cn: "zh", chi: "zh", chinese: "zh", "zh-cn": "zh",
  中: "zh", 中文: "zh", 汉语: "zh", 漢語: "zh", 中国語: "zh", 简体: "zh", 简体中文: "zh",
};

export function normalizeLang(v: string): string | null {
  const k = String(v ?? "").trim().toLowerCase();
  if (!k) return null;
  return LANG_ALIASES[k] ?? null;
}

// 表头识别（模糊）：把某个表头字符串映射到字段。
const HEADER_MAP: { field: keyof ParsedRow; names: string[] }[] = [
  { field: "source_lang", names: ["源语言", "来源语言", "源語言", "source_lang", "sourcelang", "source lang", "source language"] },
  { field: "target_lang", names: ["目标语言", "目標語言", "目标语", "target_lang", "targetlang", "target lang", "target language"] },
  { field: "source_term", names: ["原文", "原词", "原詞", "source", "source_term", "term", "词条", "詞條"] },
  { field: "target_term", names: ["中文译文", "译文", "譯文", "翻译", "翻譯", "target", "target_term", "translation", "中文"] },
  { field: "domain", names: ["领域", "領域", "domain", "category", "分类", "分類"] },
  { field: "note", names: ["备注", "備注", "備考", "備註", "note", "remark", "comment", "说明", "說明"] },
];

const REQUIRED: (keyof ParsedRow)[] = ["source_lang", "target_lang", "source_term", "target_term"];

function headerToField(h: string): keyof ParsedRow | null {
  const s = String(h ?? "").trim().toLowerCase().replace(/\s+/g, " ");
  for (const { field, names } of HEADER_MAP) {
    if (names.some((n) => n.toLowerCase() === s)) return field;
  }
  return null;
}

export function keyOf(r: {
  source_lang: string;
  target_lang: string;
  source_term: string;
  domain: string;
}): string {
  return `${r.source_lang}|${r.target_lang}|${r.source_term}|${r.domain || ""}`;
}

export function parseAoa(aoa: string[][]): ParseResult {
  const errors: string[] = [];
  if (!aoa || aoa.length === 0) return { rows: [], skipped: 0, errors: [], fatal: "文件为空。" };

  const header = aoa[0].map((c) => String(c ?? ""));
  const idx: Partial<Record<keyof ParsedRow, number>> = {};
  header.forEach((h, i) => {
    const f = headerToField(h);
    if (f && idx[f] === undefined) idx[f] = i;
  });

  const missing = REQUIRED.filter((f) => idx[f] === undefined);
  if (missing.length) {
    const label: Record<string, string> = {
      source_lang: "源语言",
      target_lang: "目标语言",
      source_term: "原文",
      target_term: "中文译文",
    };
    return {
      rows: [],
      skipped: 0,
      errors: [],
      fatal: `缺少必需列：${missing.map((m) => label[m]).join("、")}。请用「下载模板」对照表头。`,
    };
  }

  const get = (row: string[], f: keyof ParsedRow): string => {
    const i = idx[f];
    if (i === undefined) return "";
    return String(row[i] ?? "").trim();
  };

  const byKey = new Map<string, ParsedRow>();
  let skipped = 0;

  for (let r = 1; r < aoa.length; r++) {
    const row = aoa[r];
    const rowNo = r + 1; // 表头是第 1 行
    const st = get(row, "source_term");
    const tt = get(row, "target_term");
    const slRaw = get(row, "source_lang");
    const tlRaw = get(row, "target_lang");

    // 完全空行：静默跳过
    if (!st && !tt && !slRaw && !tlRaw) {
      skipped++;
      continue;
    }
    if (!st || !tt) {
      skipped++;
      if (errors.length < 12) errors.push(`第${rowNo}行：原文或译文为空，已跳过`);
      continue;
    }
    const sl = normalizeLang(slRaw);
    const tl = normalizeLang(tlRaw);
    if (!sl) {
      skipped++;
      if (errors.length < 12) errors.push(`第${rowNo}行：无法识别源语言「${slRaw}」，已跳过`);
      continue;
    }
    if (!tl) {
      skipped++;
      if (errors.length < 12) errors.push(`第${rowNo}行：无法识别目标语言「${tlRaw}」，已跳过`);
      continue;
    }
    if (sl === tl) {
      skipped++;
      if (errors.length < 12) errors.push(`第${rowNo}行：源语言与目标语言相同，已跳过`);
      continue;
    }

    const parsed: ParsedRow = {
      source_lang: sl,
      target_lang: tl,
      source_term: st,
      target_term: tt,
      domain: get(row, "domain"),
      note: get(row, "note"),
    };
    byKey.set(keyOf(parsed), parsed); // 文件内同键取最后一条
  }

  return { rows: [...byKey.values()], skipped, errors };
}

// 「下载模板」用的二维数组
export function buildTemplateAoa(): string[][] {
  return [
    ["源语言", "目标语言", "原文", "中文译文", "领域", "备注"],
    ["日本語", "中文", "壁面", "墙面", "材料", ""],
    ["English", "中文", "CROWN", "顶角线", "", ""],
  ];
}
