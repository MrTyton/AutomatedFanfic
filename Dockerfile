# Builder Pattern Strategy:
# 1. 'builder-base': Common build tools (curl, jq, xz)
# 2. 'calibre-downloader': Downloads and prunes Calibre. CACHED until CALIBRE_RELEASE changes.
# 3. 'python-deps': Installs Python libs. CACHED until requirements.txt changes.
# 4. 'runtime': Final image. Copies artifacts from previous stages. Small, clean, secure.

# Base Stage: Common python base
FROM python:3.15-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONOPTIMIZE=2 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

# Builder Tools Stage: Install tools needed for building/downloading
FROM base AS builder-tools
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    jq \
    xz-utils && \
    pip install --no-cache-dir --upgrade pip setuptools wheel

# Calibre Downloader Stage: Downloads and prunes Calibre
FROM builder-tools AS calibre-downloader

ARG TARGETPLATFORM
ARG CALIBRE_RELEASE

# Download and extract Calibre
RUN --mount=type=cache,target=/tmp/calibre-cache \
    echo "**** install calibre ****" && \
    mkdir -p /opt/calibre && \
    case "${TARGETPLATFORM:-linux/amd64}" in \
    "linux/amd64") CALIBRE_ARCH="x86_64" ;; \
    "linux/arm64") CALIBRE_ARCH="arm64" ;; \
    *) echo "Unsupported platform: ${TARGETPLATFORM}" && exit 1 ;; \
    esac && \
    if [ -z "${CALIBRE_RELEASE}" ]; then \
    CALIBRE_RELEASE_TAG=$(curl -sX GET "https://api.github.com/repos/kovidgoyal/calibre/releases/latest" | jq -r .tag_name); \
    CALIBRE_VERSION=$(echo "${CALIBRE_RELEASE_TAG}" | sed 's/^v//'); \
    else \
    CALIBRE_VERSION=$(echo "${CALIBRE_RELEASE}" | sed 's/^v//'); \
    fi && \
    echo "Using Calibre version: ${CALIBRE_VERSION} (${CALIBRE_ARCH})" && \
    CALIBRE_URL="https://download.calibre-ebook.com/${CALIBRE_VERSION}/calibre-${CALIBRE_VERSION}-${CALIBRE_ARCH}.txz" && \
    CALIBRE_CACHE_FILE="/tmp/calibre-cache/calibre-${CALIBRE_VERSION}-${CALIBRE_ARCH}.txz" && \
    if [ ! -f "${CALIBRE_CACHE_FILE}" ] || [ ! -s "${CALIBRE_CACHE_FILE}" ]; then \
    echo "Downloading fresh copy..." && \
    curl -o "${CALIBRE_CACHE_FILE}" -L "${CALIBRE_URL}"; \
    else \
    echo "Using cached binary..."; \
    fi && \
    tar xf "${CALIBRE_CACHE_FILE}" -C /opt/calibre && \
    # Cleanup Calibre (Aggressive)
    rm -f /opt/calibre/calibre /opt/calibre/ebook-viewer /opt/calibre/ebook-edit \
    /opt/calibre/ebook-convert /opt/calibre/ebook-meta /opt/calibre/ebook-polish \
    /opt/calibre/calibre-server /opt/calibre/calibre-smtp /opt/calibre/web2disk \
    /opt/calibre/lrf2lrs /opt/calibre/lrfviewer /opt/calibre/markdown-calibre \
    /opt/calibre/calibre-debug /opt/calibre/fetch-ebook-metadata 2>/dev/null || true && \
    rm -rf /opt/calibre/lib/python*/site-packages/calibre/gui2 \
    /opt/calibre/lib/python*/site-packages/calibre/srv \
    /opt/calibre/lib/python*/site-packages/calibre/ebooks/oeb/display \
    /opt/calibre/resources/viewer /opt/calibre/resources/editor \
    /opt/calibre/resources/content-server /opt/calibre/resources/images \
    /opt/calibre/resources/fonts/liberation \
    /opt/calibre/lib/libcrypto.so* /opt/calibre/lib/libssl.so* \
    /opt/calibre/lib/qt-plugins 2>/dev/null || true && \
    # Pruning Qt/PyQt completely requires more tailored `find` which we can do here
    find /opt/calibre -name "*Gui*" -type f -delete 2>/dev/null || true && \
    find /opt/calibre -name "*Widget*" -type f -delete 2>/dev/null || true && \
    find /opt/calibre -path "*/PyQt*/Qt*" -delete 2>/dev/null || true && \
    find /opt/calibre -name "*Qt6WebEngine*" -delete 2>/dev/null || true && \
    find /opt/calibre -name "*Qt6Qml*" -delete 2>/dev/null || true && \
    find /opt/calibre -name "*Qt6Quick*" -delete 2>/dev/null || true && \
    find /opt/calibre -name "*Qt6Pdf*" -delete 2>/dev/null || true && \
    rm -rf /opt/calibre/resources/localization/locales \
    /opt/calibre/resources/dictionaries \
    /opt/calibre/resources/hyphenation \
    /opt/calibre/resources/mathjax \
    /opt/calibre/resources/rapydscript 2>/dev/null || true

# Python Dependencies Stage
FROM builder-tools AS python-deps
# Install build tools and common dev libs for C extensions that may not yet
# have pre-built wheels for the current Python version (e.g. Brotli, uvloop,
# Pillow on a freshly-released Python release).
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
    libfreetype6-dev \
    libwebp-dev \
    libopenjp2-7-dev
COPY requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefix=/install --no-warn-script-location -r /tmp/requirements.txt

# FanFicFare Installer Stage
# Inherits from python-deps with PYTHONPATH pointing at /install's site-packages
# so pip sees all requirements.txt packages as already satisfied (avoiding
# duplicate downloads/compilations) while still resolving any missing or newly
# added FanFicFare transitive dependencies into /install-fff without --no-deps.
FROM python-deps AS fanficfare-installer
ARG FANFICFARE_VERSION
RUN --mount=type=cache,target=/root/.cache/pip \
    echo "*** Install FanFicFare from PyPI + TestPyPI ***" && \
    if [ -n "${FANFICFARE_VERSION}" ]; then \
    PACKAGE_SPEC="FanFicFare==${FANFICFARE_VERSION}"; \
    else \
    PACKAGE_SPEC="FanFicFare"; \
    fi && \
    SITE_PKGS="$(python -c 'import sysconfig; print(sysconfig.get_path("purelib", vars={"base": "/install", "platbase": "/install"}))')" && \
    PYTHONPATH="${SITE_PKGS}" pip install --prefix=/install-fff --no-warn-script-location \
    --extra-index-url https://test.pypi.org/simple/ "${PACKAGE_SPEC}"

# Frontend Builder Stage: Build React SPA
FROM node:22-slim AS frontend-builder
WORKDIR /build
COPY root/web-ui/package.json root/web-ui/package-lock.json* ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund
COPY root/web-ui/ ./
RUN npm run build

# Runtime Stage: The final image
FROM base AS runtime

ARG PUID="911"
ARG PGID="911"
# TARGETPLATFORM declared early as it's used in apt-get conditional below
ARG TARGETPLATFORM

# Install minimalistic runtime deps
# NOTE: ARG VERSION and ARG CALIBRE_RELEASE are declared AFTER these stable layers
# so that a version bump does NOT invalidate these cached layers.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    bash \
    ca-certificates && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Create user and data directory
RUN groupadd --gid "$PGID" abc && \
    useradd --create-home --shell /bin/bash --uid "$PUID" --gid abc abc && \
    mkdir -p /data && chown abc:abc /data

# Copy Application Code - changes RARELY (manual commits, infrequent)
# Placed first so the more frequent calibre/deps/FFF layers below are not
# invalidated when code changes.
COPY --chown=abc:abc root/app/ /app/
COPY root/config.default/ /config.default/
COPY --from=frontend-builder /build/dist /web-ui/dist
RUN chmod -R +x /app/

# Copy Calibre - changes MONTHLY (new Calibre releases)
COPY --from=calibre-downloader /opt/calibre /opt/calibre

# Final Setup (depends on Calibre being present)
RUN echo "*** Setting up Env ***" && \
    # Fix library paths for Calibre
    if [ -d "/opt/calibre/lib" ]; then \
    echo "/opt/calibre/lib" > /etc/ld.so.conf.d/calibre.conf && \
    ldconfig; \
    fi && \
    # Symlink calibredb
    ln -sf /opt/calibre/calibredb /usr/local/bin/calibredb && \
    # Verify calibredb works
    calibredb --version

# Copy Python dependencies - changes WEEKLY (dependabot)
COPY --from=python-deps /install /usr/local

# Copy FanFicFare - changes DAILY (automated updates)
# Placed last so the most common update only invalidates this single layer.
COPY --from=fanficfare-installer /install-fff /usr/local

# Verify Python runtime dependencies and entrypoint imports inside the final image
RUN python /app/fanficdownload.py --help > /dev/null && \
    PYTHONPATH=/app python -c "import fanficfare.adapters, fanficfare.cli, fanficfare.configurable, fanficfare.geturls, web.server"

# Version ARGs declared here (after all stable layers) so version bumps
# do NOT invalidate the cached apt, user, pip, or calibre layers above.
ARG VERSION
ARG CALIBRE_RELEASE

# Runtime Config
LABEL build_version="FFDL-Auto version:- ${VERSION} Calibre: ${CALIBRE_RELEASE}"
ENV VERBOSE=false
ENV LD_LIBRARY_PATH="/opt/calibre/lib"
EXPOSE 8080
VOLUME /config
VOLUME /data
WORKDIR /app

CMD ["/app/entrypoint.sh"]
