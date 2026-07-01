# supabase

- **`migrations/`** —— SQL 迁移：
  - `0001` profiles + 角色（sales/admin）
  - `0002` glossary（术语表，单一真相源，共享读写）
  - `0003` factory_profiles（工厂 profile，共享只读 + admin 写）
  - `0004` jobs（私有任务，按 user_id 隔离）
  - `0005` storage buckets（uploads/outputs，私有）
  - `0006` seed（627 条术语 + 创明 profile）
- **`seed/`** —— `glossary_seed.json`（从 `drawing-translator` 的 EN_DICT/JP_DICT + `drawing-to-quotation` 的 translations.md 抽出）。

（迁移内容与 seed 在 T3/T7 落地。）
