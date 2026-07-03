# 后端镜像：Python 3.11 + LibreOffice（报价渲染验证图/唛头用）+ shared/py 依赖。
# 构建上下文是仓库根（见 docker-compose.yml 的 context: .），以便同时拷 shared/py。
FROM python:3.11-slim

# LibreOffice(calc/writer) 供 render_check 把 xlsx 渲成目视验证 PNG；
# fonts-noto-cjk 保证日/中字符不豆腐块。
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-calc \
        libreoffice-writer \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖（利用层缓存）：shared/py + apps/api 两份 requirements 叠加。
COPY shared/py/requirements.txt shared/py/requirements.txt
COPY apps/api/requirements.txt apps/api/requirements.txt
RUN pip install --no-cache-dir \
        -r shared/py/requirements.txt \
        -r apps/api/requirements.txt

# 再拷源码：shared/py 供后端 import（glossary/claude_client/supabase_client/settings/skills）。
COPY shared/py shared/py
COPY apps/api apps/api

# config.py 会自向上找 shared/py，这里显式设 PYTHONPATH 更稳。
ENV PYTHONPATH=/app/shared/py
WORKDIR /app/apps/api

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
