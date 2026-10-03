FROM python:3.13-slim

# 强制 apt 走 IPv4，避免容器内解析到 AAAA 后无 IPv6 出口导致 apt-get update 挂死
RUN echo 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99forceipv4

# 容器内直连 deb.debian.org 会挂死（无 IPv6 出口 / 出网受限），改用腾讯云 Debian 镜像
# Debian trixie(13) 默认用 deb822 格式，源在 /etc/apt/sources.list.d/*.sources；
# 旧版则仍是 /etc/apt/sources.list。两种都覆盖。
RUN for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.sources; do \
      [ -f "$f" ] && sed -i 's#deb.debian.org#mirrors.tencent.com#g' "$f"; done

RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# pip 改用腾讯云 PyPI 镜像（容器内直连 pypi.org 不稳）
ENV PIP_INDEX_URL=https://mirrors.tencent.com/pypi/simple

COPY requirements.txt .
# 先升级 pip，避免旧基础镜像内 pip 不识别新版 wheel 标签（如 cryptography cp313）导致 "from versions: none"
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY . .

# 创建非 root 用户并切换
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
