# Builder Pattern Strategy:
# 1. 'builder-base': Common build tools (curl, jq, xz)
# 2. 'calibre-downloader': Downloads and prunes Calibre. CACHED until CALIBRE_RELEASE changes.
# 3. 'python-deps': Installs Python libs. CACHED until requirements.txt changes.
# 4. 'runtime': Final image. Copies artifacts from previous stages. Small, clean, secure.

# Base Stage: Common python base
FROM python:3.12-slim AS base
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
    "linux/amd64") \
    if [ -z "${CALIBRE_RELEASE}" ]; then \
    CALIBRE_RELEASE_TAG=$(curl -sX GET "https://api.github.com/repos/kovidgoyal/calibre/releases/latest" | jq -r .tag_name); \
    CALIBRE_VERSION=$(echo "${CALIBRE_RELEASE_TAG}" | sed 's/^v//'); \
    else \
    CALIBRE_VERSION=$(echo "${CALIBRE_RELEASE}" | sed 's/^v//'); \
    fi && \
    echo "Using Calibre version: ${CALIBRE_VERSION}" && \
    CALIBRE_URL="https://download.calibre-ebook.com/${CALIBRE_VERSION}/calibre-${CALIBRE_VERSION}-x86_64.txz" && \
    CALIBRE_CACHE_FILE="/tmp/calibre-cache/calibre-${CALIBRE_VERSION}-x86_64.txz" && \
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
    find /opt/calibre -path "*/PyQt*/Qt*" -delete 2>/dev/null || true \
    ;; \
    *) \
    # ARM/Other fallback - strictly for file structure consistency if needed
    # But actually, for ARM, we usually install via APT in runtime.
    # This stage might be empty for ARM or we handle it differently.
    # For this optimization, we assume the user's primary concern is the heavy AMD64 binary.
    echo "Non-AMD64 build: Calibre will be installed via APT in runtime stage." \
    ;; \
    esac

# Python Dependencies Stage
FROM builder-tools AS python-deps
COPY requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefix=/install --no-warn-script-location --no-cache-dir -r /tmp/requirements.txt

# FanFicFare Installer Stage
FROM builder-tools AS fanficfare-installer
ARG FANFICFARE_VERSION
RUN --mount=type=cache,target=/root/.cache/pip \
    echo "*** Install FanFicFare from TestPyPI ***" && \
    INDEX_URL="https://test.pypi.org/simple/" && \
    if [ -n "${FANFICFARE_VERSION}" ]; then \
    PACKAGE_SPEC="FanFicFare==${FANFICFARE_VERSION}"; \
    else \
    PACKAGE_SPEC="FanFicFare"; \
    fi && \
    pip install --prefix=/install --no-warn-script-location --no-cache-dir -i "${INDEX_URL}" --extra-index-url https://pypi.org/simple "${PACKAGE_SPEC}"

# Runtime Stage: The final image
FROM base AS runtime

ARG PUID="911"
ARG PGID="911"
# Version ARGs for labels
ARG VERSION
ARG CALIBRE_RELEASE
# Re-declare for runtime usage if needed (rare) or just for logic
ARG TARGETPLATFORM

# Install minimalistic runtime deps
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    # ARM builds might need calibre from apt
    $(if [ "${TARGETPLATFORM}" != "linux/amd64" ]; then echo "calibre"; fi) && \
    apt-get clean && \
    rm -rf /tmp/* /var/tmp/*

# Create user
RUN groupadd --gid "$PGID" abc && \
    useradd --create-home --shell /bin/bash --uid "$PUID" --gid abc abc

# Copy Python dependencies from builder
COPY --from=python-deps /install /usr/local
COPY --from=fanficfare-installer /install /usr/local

# Copy Calibre from builder (AMD64 only)
# For ARM, this directory will be empty or not copied if we logic'd it right, but `COPY --from` fails if src missing.
# We'll use a trick: Check if /opt/calibre exists in source.
# Actually, simpler: We always create /opt/calibre in builder, even if empty.
COPY --from=calibre-downloader /opt/calibre /opt/calibre

# Final Setup
RUN echo "*** Setting up Env ***" && \
    # Fix library paths for Calibre (AMD64)
    if [ -d "/opt/calibre/lib" ]; then \
    echo "/opt/calibre/lib" > /etc/ld.so.conf.d/calibre.conf && \
    ldconfig; \
    fi && \
    # Symlink calibredb
    if [ -f "/opt/calibre/calibredb" ]; then \
    ln -sf /opt/calibre/calibredb /usr/local/bin/calibredb; \
    elif [ -f "/usr/bin/calibredb" ]; then \
    ln -sf /usr/bin/calibredb /usr/local/bin/calibredb; \
    fi && \
    # Verify calibredb works
    calibredb --version

# Copy Application Code (Frequent changes)
COPY root/ /
RUN chmod -R +x /app/ && \
    chown -R abc:abc /app/

# Runtime Config
LABEL build_version="FFDL-Auto version:- ${VERSION} Calibre: ${CALIBRE_RELEASE}"
ENV VERBOSE=false
ENV LD_LIBRARY_PATH="/opt/calibre/lib"
VOLUME /config
WORKDIR /config

CMD ["/app/entrypoint.sh"]
