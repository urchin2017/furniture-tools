# 前端镜像：Node 20 + Next.js dev。构建上下文是仓库根（npm workspaces 需要整仓）。
# 用 dev 模式跑：NEXT_PUBLIC_* 在 dev 下运行时读取，改 .env 后重启容器即可生效，无需重建。
FROM node:20-bookworm-slim

WORKDIR /repo

# 先按 lockfile 装依赖（含 apps/web + shared/ts 两个 workspace），利用层缓存。
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
COPY shared/ts/package.json shared/ts/package.json
RUN npm ci

# 再拷源码（.dockerignore 已排除 node_modules/.next/.env 等）。
COPY . .

WORKDIR /repo/apps/web
EXPOSE 3000
# -H 0.0.0.0 让容器外（宿主浏览器）能访问。
CMD ["npm", "run", "dev", "--", "-H", "0.0.0.0", "-p", "3000"]
