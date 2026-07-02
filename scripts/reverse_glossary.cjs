#!/usr/bin/env node
/*
 * 把现有「→中文」词条批量反转成「中→日 / 中→英」初始候选（待人工校对）。
 * 读入：Supabase 导出的 JSON 数组（含 source_lang,target_lang,source_term,target_term,domain,note）。
 * 输出：两个 CSV（import 模板格式：源语言,目标语言,原文,译文,领域,备注），带 UTF-8 BOM。
 *
 * 处理要点：
 *  - 只反转 target_lang='zh' 的行；zh→<原源语言>。
 *  - 多个外文词映射到同一中文词时会「撞键」，合并为一行：译文取第 1 个候选，
 *    备注里列出全部候选供校对（不丢信息）。
 *  - 所有行 备注 标注来源，方便校对与后续筛选。
 *
 * 用法：IN=dump.json OUTDIR=/some/dir node reverse_glossary.cjs
 */
const fs = require("fs");
const path = require("path");

const IN = process.env.IN;
const OUTDIR = process.env.OUTDIR;
if (!IN || !OUTDIR) {
  console.error("需要环境变量 IN（输入 JSON）和 OUTDIR（输出目录）");
  process.exit(1);
}

const rows = JSON.parse(fs.readFileSync(IN, "utf8"));
const norm = (s) => String(s == null ? "" : s).trim();
const csvCell = (s) => {
  const v = String(s == null ? "" : s);
  return /[",\n\r]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
};

function reverse(origSourceLang, targetLabel) {
  const groups = new Map(); // zhTerm||domain -> { zhTerm, domain, candidates:[] }
  for (const r of rows) {
    if (norm(r.target_lang) !== "zh") continue;
    if (norm(r.source_lang) !== origSourceLang) continue;
    const zh = norm(r.target_term);
    const foreign = norm(r.source_term);
    const domain = norm(r.domain);
    if (!zh || !foreign) continue;
    const key = zh + "||" + domain;
    if (!groups.has(key)) groups.set(key, { zhTerm: zh, domain, candidates: [] });
    const g = groups.get(key);
    if (!g.candidates.includes(foreign)) g.candidates.push(foreign);
  }
  let collisions = 0;
  const out = [];
  for (const g of groups.values()) {
    const primary = g.candidates[0];
    let note;
    if (g.candidates.length > 1) {
      collisions++;
      note = `候选${g.candidates.length}个：${g.candidates.join(" / ")}｜已选第1个，待校对`;
    } else {
      note = "自动反转，待校对";
    }
    out.push(["中文", targetLabel, g.zhTerm, primary, g.domain, note]);
  }
  return { out, collisions };
}

function writeCsv(file, dataRows) {
  const header = ["源语言", "目标语言", "原文", "译文", "领域", "备注"];
  const lines = [header, ...dataRows].map((r) => r.map(csvCell).join(","));
  fs.writeFileSync(file, "﻿" + lines.join("\r\n") + "\r\n", "utf8");
}

const ja = reverse("ja", "日本語");
const en = reverse("en", "English");
const jaFile = path.join(OUTDIR, "reverse_zh_ja.csv");
const enFile = path.join(OUTDIR, "reverse_zh_en.csv");
writeCsv(jaFile, ja.out);
writeCsv(enFile, en.out);

console.log(
  JSON.stringify(
    {
      input_rows: rows.length,
      zh_ja: { generated: ja.out.length, collisions_merged: ja.collisions, file: jaFile },
      zh_en: { generated: en.out.length, collisions_merged: en.collisions, file: enFile },
    },
    null,
    2,
  ),
);
