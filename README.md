# 家具出口内部工具

把公司已有的几个 Claude Skill 组装成一个网页工具，给销售同事用。他们不需要 API key，所有 AI 调用走服务端。

## 这个项目由几块组成
- `apps/web` —— 网页界面（销售看到的部分）
- `apps/api` —— 后端程序（处理图纸/Excel、调 AI）
- `supabase` —— 数据库（术语表、任务、账号）
- `shared` —— 前后端共用的代码
- `docker` —— 打包运行用

## 功能（分三大模块）
- **A 报价**：报价单生成、报价单对比
- **B 图纸**：图纸翻译、图纸改版差异对比
- **C 唛头**：唛头生成（先占位）

## 怎么备份到 GitHub（大白话）
整个项目就是一个 GitHub 私有仓库。要备份/上传时，直接对助手说"帮我上传"，它会替你执行：
1. `git add -A` —— 收集改动
2. `git commit -m "说明"` —— 存一个本地存档点
3. `git push` —— 上传到 GitHub

换电脑或文件丢了：`git clone <仓库地址>` 就能全部拿回。

> ⚠️ `.env` 里放着密钥，**绝不会上传**（已被 `.gitignore` 挡住）。

## 运行（开发阶段，后续完善）
- 前端：`cd apps/web && npm run dev`
- 后端：`cd apps/api && uvicorn app.main:app --reload`
- 一键（需 Docker Desktop）：`docker compose -f docker/docker-compose.yml up`
