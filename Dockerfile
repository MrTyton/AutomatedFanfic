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
    # Cleanup Calibre: keep only calibredb and calibre-parallel CLI runners
    find /opt/calibre/bin -type f ! -name "calibredb" ! -name "calibre-parallel" -delete 2>/dev/null || true && \
    find /opt/calibre -maxdepth 1 -type f ! -name "calibredb" ! -name "calibre-parallel" -delete 2>/dev/null || true && \
    # Remove unused top-level Calibre directories (translations, speech data, GUI/multimedia plugins)
    rm -rf /opt/calibre/translations \
    /opt/calibre/share \
    /opt/calibre/plugins 2>/dev/null || true && \
    # Remove unused resources (viewer, editor, fonts, news recipes, WebEngine assets; keeps locales.zip)
    rm -rf /opt/calibre/resources/viewer \
    /opt/calibre/resources/editor \
    /opt/calibre/resources/content-server \
    /opt/calibre/resources/images \
    /opt/calibre/resources/fonts/liberation \
    /opt/calibre/resources/dictionaries \
    /opt/calibre/resources/hyphenation \
    /opt/calibre/resources/mathjax \
    /opt/calibre/resources/rapydscript 2>/dev/null || true && \
    rm -f /opt/calibre/resources/qtwebengine* \
    /opt/calibre/resources/icudtl.dat \
    /opt/calibre/resources/v8_context_snapshot.bin \
    /opt/calibre/resources/builtin_recipes.* \
    /opt/calibre/resources/viewer.* \
    /opt/calibre/resources/editor.* \
    /opt/calibre/resources/stylelint-bundle.* \
    /opt/calibre/resources/ebook-convert-complete.* \
    /opt/calibre/resources/icons.rcc 2>/dev/null || true && \
    # Remove unused shared libraries in /opt/calibre/lib (TTS, media, unused formats, non-Core Qt6; keeps libstemmer)
    rm -f /opt/calibre/lib/libcrypto.so* /opt/calibre/lib/libssl.so* /opt/calibre/lib/qt-plugins 2>/dev/null || true && \
    rm -f /opt/calibre/lib/libonnxruntime* /opt/calibre/lib/libespeak-ng* /opt/calibre/lib/libpiper* 2>/dev/null || true && \
    rm -f /opt/calibre/lib/libavcodec* /opt/calibre/lib/libavfilter* /opt/calibre/lib/libavformat* \
    /opt/calibre/lib/libdav1d* /opt/calibre/lib/libavutil* /opt/calibre/lib/libswscale* \
    /opt/calibre/lib/libswresample* /opt/calibre/lib/libpostproc* /opt/calibre/lib/libyuv* \
    /opt/calibre/lib/libaom* /opt/calibre/lib/libvpx* /opt/calibre/lib/libopus* \
    /opt/calibre/lib/libvorbis* /opt/calibre/lib/libogg* /opt/calibre/lib/libmp3lame* \
    /opt/calibre/lib/libmpg123* /opt/calibre/lib/libsndfile* /opt/calibre/lib/libFLAC* 2>/dev/null || true && \
    rm -f /opt/calibre/lib/libpodofo* /opt/calibre/lib/libpoppler* /opt/calibre/lib/libhunspell* \
    /opt/calibre/lib/libhyphen* /opt/calibre/lib/libuchardet* /opt/calibre/lib/libwebp* \
    /opt/calibre/lib/libopenjp2* /opt/calibre/lib/libjpeg* /opt/calibre/lib/libpng* \
    /opt/calibre/lib/libtiff* /opt/calibre/lib/libfreetype* /opt/calibre/lib/libharfbuzz* \
    /opt/calibre/lib/libfontconfig* /opt/calibre/lib/liblcms2* /opt/calibre/lib/libjbig* \
    /opt/calibre/lib/libdeflate* /opt/calibre/lib/libLerc* 2>/dev/null || true && \
    rm -f /opt/calibre/lib/libQt6Multimedia* /opt/calibre/lib/libQt6SpatialAudio* /opt/calibre/lib/libQt6Wayland* \
    /opt/calibre/lib/libQt6Network* /opt/calibre/lib/libQt6DBus* /opt/calibre/lib/libQt6OpenGL* \
    /opt/calibre/lib/libQt6Svg* /opt/calibre/lib/libQt6PrintSupport* /opt/calibre/lib/libQt6Sql* \
    /opt/calibre/lib/libQt6Test* /opt/calibre/lib/libQt6Sensors* /opt/calibre/lib/libQt6Positioning* \
    /opt/calibre/lib/libQt6WebChannel* /opt/calibre/lib/libQt6StateMachine* /opt/calibre/lib/libQt6ShaderTools* 2>/dev/null || true && \
    # Remove unused C-extensions in /opt/calibre/lib/calibre-extensions
    rm -f /opt/calibre/lib/calibre-extensions/PyQt6.QtQuick* \
    /opt/calibre/lib/calibre-extensions/PyQt6.QtQml* \
    /opt/calibre/lib/calibre-extensions/PyQt6.QtOpenGL* \
    /opt/calibre/lib/calibre-extensions/PyQt6.QtNetwork* \
    /opt/calibre/lib/calibre-extensions/PyQt6.QtMultimedia* \
    /opt/calibre/lib/calibre-extensions/PyQt6.QtWebEngine* \
    /opt/calibre/lib/calibre-extensions/PyQt6.QtSql* \
    /opt/calibre/lib/calibre-extensions/PyQt6.QtSvg* \
    /opt/calibre/lib/calibre-extensions/PyQt6.QtDBus* \
    /opt/calibre/lib/calibre-extensions/PyQt6.QtPrintSupport* \
    /opt/calibre/lib/calibre-extensions/PyQt6.QtSensors* \
    /opt/calibre/lib/calibre-extensions/PyQt6.QtPositioning* \
    /opt/calibre/lib/calibre-extensions/PyQt6.QtWebChannel* \
    /opt/calibre/lib/calibre-extensions/PyQt6.QtStateMachine* \
    /opt/calibre/lib/calibre-extensions/PyQt6.QtTest* \
    /opt/calibre/lib/calibre-extensions/podofo* \
    /opt/calibre/lib/calibre-extensions/hunspell* \
    /opt/calibre/lib/calibre-extensions/piper* \
    /opt/calibre/lib/calibre-extensions/pictureflow* \
    /opt/calibre/lib/calibre-extensions/imageops* \
    /opt/calibre/lib/calibre-extensions/libmtp* \
    /opt/calibre/lib/calibre-extensions/libusb* \
    /opt/calibre/lib/calibre-extensions/wpd* \
    /opt/calibre/lib/calibre-extensions/_test* 2>/dev/null || true

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
    pip install --prefix=/install --no-warn-script-location -r /tmp/requirements.txt && \
    find /install -type d -name "tests" -path "*/apsw/*" -exec rm -rf {} + 2>/dev/null || true && \
    find /install -type d -name "sqlite_extra_binaries" -path "*/apsw/*" -exec rm -rf {} + 2>/dev/null || true && \
    find /install -type f -name "*.so*" -exec strip --strip-unneeded {} + 2>/dev/null || true

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
    --extra-index-url https://test.pypi.org/simple/ "${PACKAGE_SPEC}" && \
    find /install-fff -type f -name "*.so*" -exec strip --strip-unneeded {} + 2>/dev/null || true

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

# Copy Frontend build - changes INFREQUENTLY (~0.2 MB)
COPY --from=frontend-builder /build/dist /web-ui/dist

# Copy Calibre - changes MONTHLY (new Calibre releases)
# Largest layer (187 MB). Placed before dependencies and app code so that
# daily FanFicFare updates and app code commits never invalidate Calibre.
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
    calibredb --version && \
    # Functional smoke test: verify calibredb add/list/search/set_metadata/export/remove
    python3 -c 'import zipfile; z = zipfile.ZipFile("/tmp/test.epub", "w"); z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED); z.writestr("META-INF/container.xml", "<container version=\"1.0\" xmlns=\"urn:oasis:names:tc:opendocument:xmlns:container\"><rootfiles><rootfile full-path=\"content.opf\" media-type=\"application/oebps-package+xml\"/></rootfiles></container>"); z.writestr("content.opf", "<package xmlns=\"http://www.idpf.org/2007/opf\" unique-identifier=\"B\" version=\"2.0\"><metadata xmlns:dc=\"http://purl.org/dc/elements/1.1/\"><dc:title>Test Story</dc:title><dc:creator>Author</dc:creator><dc:identifier id=\"B\">1</dc:identifier><dc:language>en</dc:language></metadata><manifest><item id=\"c\" href=\"c.html\" media-type=\"application/xhtml+xml\"/></manifest><spine><itemref idref=\"c\"/></spine></package>"); z.writestr("ch.html", "<html><body><p>Test</p></body></html>"); z.close()' && \
    mkdir -p /tmp/smoke-lib /tmp/smoke-export && \
    calibredb add /tmp/test.epub --library-path /tmp/smoke-lib > /dev/null && \
    calibredb list --library-path /tmp/smoke-lib > /dev/null && \
    calibredb search "title:Test" --library-path /tmp/smoke-lib > /dev/null && \
    calibredb set_metadata 1 --field title:"Smoke Title" --library-path /tmp/smoke-lib > /dev/null && \
    calibredb export 1 --to-dir /tmp/smoke-export --library-path /tmp/smoke-lib > /dev/null && \
    calibredb remove 1 --library-path /tmp/smoke-lib > /dev/null && \
    rm -rf /tmp/test.epub /tmp/smoke-lib /tmp/smoke-export

# Copy Python dependencies - changes WEEKLY (dependabot) (~25 MB)
COPY --from=python-deps /install /usr/local

# Copy default configuration - changes RARELY (~0.04 MB)
COPY root/config.default/ /config.default/

# Copy FanFicFare - changes DAILY (automated updates) (~1.1 MB)
COPY --from=fanficfare-installer /install-fff /usr/local

# Copy Application Code - changes on commits and daily version bumps (~0.11 MB)
COPY --chown=abc:abc --chmod=755 root/app/ /app/

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
ENV MALLOC_ARENA_MAX=2
EXPOSE 8080
VOLUME /config
VOLUME /data
WORKDIR /app

CMD ["/app/entrypoint.sh"]
