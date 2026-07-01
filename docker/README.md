# docker

- **`Dockerfile.api`** —— 后端镜像。装 LibreOffice / poppler-utils / weasyprint(+libpango/cairo) / 中日 CJK 字体 / ImageMagick + Python 依赖（PyMuPDF/openpyxl/pillow/numpy/reportlab/pypdf/anthropic/supabase/fastapi…）。决定各 skill 机械脚本能否跑。
- **`Dockerfile.web`** —— 前端镜像（Next.js 构建/运行）。
- **`docker-compose.yml`** —— 本地一键起 web+api（连云端 Supabase，不本地起 Postgres）。

（在 T9 落地；需先装 Docker Desktop。）
