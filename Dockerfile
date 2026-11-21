# DanmakuRender 容器镜像
#
# 基于 Debian slim（而非 Alpine）：quickjs / lxml / Pillow 等依赖可以直接使用
# manylinux wheel，不需要在最终镜像里保留编译工具链；biliup-rs 也同时提供
# x86_64 / aarch64 的 glibc 预编译版本。
#
# 构建：
#   docker build -t danmakurender .
#   docker build --build-arg BILIUP_VERSION=1.1.28 -t danmakurender .
#
# 运行（按需挂载配置/日志/登录信息/回放目录）：
#   docker run -d --name danmakurender \
#     -v $PWD/configs:/app/configs \
#     -v $PWD/logs:/app/logs \
#     -v $PWD/.login_info:/app/.login_info \
#     -v $PWD/直播回放:/app/直播回放 \
#     danmakurender
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

#: biliup-rs 版本（与 tools/toolsmgr.py 中引用的版本保持一致）。
#: 启动时 tools/toolsmgr.py 会检查 biliup，缺失会直接退出，因此镜像内必须提供；
#: 可通过 --build-arg 覆盖。
ARG BILIUP_VERSION=1.1.28
#: biliup 下载地址前缀（GitHub 访问受限时可换成镜像地址）。
ARG BILIUP_BASE_URL=https://github.com/biliup/biliup/releases/download
#: BuildKit 自动注入的构建架构（amd64 / arm64）；旧版构建器下回退为 amd64。
ARG TARGETARCH=amd64

# 运行依赖：
#   ffmpeg/ffprobe —— 录制、转码、弹幕渲染
#   nodejs         —— 斗鱼/抖音弹幕的 JavaScript 解释器
#   tzdata         —— 让日志与文件名使用本地时区
#   curl/xz-utils  —— 下载并解压 biliup-rs
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ffmpeg \
        nodejs \
        ca-certificates \
        tzdata \
        curl \
        xz-utils \
        findutils \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依赖单独一层：只有 requirements.txt 变化时才需要重新安装。
# amd64 下依赖都有预编译 wheel；arm64 的 quickjs 没有 wheel，仅在 arm64 构建时
# 临时安装编译工具链，装完立即删除，不进入最终镜像。
COPY requirements.txt ./
RUN set -eux; \
    if [ "${TARGETARCH}" = "arm64" ]; then \
        apt-get update; \
        apt-get install -y --no-install-recommends build-essential; \
    fi; \
    pip install --no-cache-dir -r requirements.txt; \
    if [ "${TARGETARCH}" = "arm64" ]; then \
        apt-get purge -y --auto-remove build-essential; \
        rm -rf /var/lib/apt/lists/*; \
    fi

# biliup-rs（B站 biliuprs 上传引擎依赖）。放到 PATH 里，toolsmgr 会自动发现。
RUN set -eux; \
    case "${TARGETARCH}" in \
        amd64) biliup_asset="x86_64-linux" ;; \
        arm64) biliup_asset="aarch64-linux" ;; \
        *) echo "不支持的构建架构: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    mkdir -p /tmp/biliup; \
    curl -fsSL -o /tmp/biliup.tar.xz \
        "${BILIUP_BASE_URL}/v${BILIUP_VERSION}/biliupR-v${BILIUP_VERSION}-${biliup_asset}.tar.xz"; \
    tar -xJf /tmp/biliup.tar.xz -C /tmp/biliup; \
    biliup_bin="$(find /tmp/biliup -type f -name biliup -print -quit)"; \
    test -n "${biliup_bin}"; \
    install -m 0755 "${biliup_bin}" /usr/local/bin/biliup; \
    rm -rf /tmp/biliup /tmp/biliup.tar.xz; \
    biliup upload -help >/dev/null

# 源码放在最后：改代码不会让上面的依赖层失效。
COPY . .

# WebUI 插件（webservice_kernel_args）默认端口。
EXPOSE 5000

ENTRYPOINT ["python3", "-u", "main.py"]
