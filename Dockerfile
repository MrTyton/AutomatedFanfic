# Use a multi-stage build optimized for change frequency
FROM python:3.12-slim AS python-base

# Set up environment variables early
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONOPTIMIZE=2 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PUID="911" \
    PGID="911" \
    VERBOSE=false \
    DEBIAN_FRONTEND=noninteractive

# Stage 1: Install minimal runtime system dependencies (rarely change)
FROM python-base AS system-deps

# Install only essential dependencies (no GUI components for calibredb-only)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    dbus \
    jq \
    # Minimal font support (calibredb might need basic text processing)
    fonts-dejavu-core \
    # Essential libraries only
    libnss3 \
    poppler-utils \
    uuid-runtime \
    xz-utils && \
    # Aggressive cleanup
    apt-get autoremove -y && \
    apt-get autoclean && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* \
    /tmp/* \
    /var/tmp/* \
    /var/cache/apt/* \
    /var/log/* && \
    echo "*** Generating machine ID ***" && \
    dbus-uuidgen > /etc/machine-id

# Stage 2: Create user (rarely changes)
FROM system-deps AS user-setup

# Create user and basic setup
RUN groupadd --gid "$PGID" abc && \
    useradd --create-home --shell /bin/bash --uid "$PUID" --gid abc abc

# Stage 3: Application code (rarely changes for you!)
FROM user-setup AS app-code

# Copy application files
COPY root/ /
RUN chmod -R +x /app/ && \
    chown -R abc:abc /app/

# Stage 4: Install stable Python dependencies (rarely change)
FROM app-code AS python-stable-deps

# Install stable Python packages from requirements.txt with cleanup
COPY requirements.txt /tmp/requirements.txt
RUN echo "*** Install Stable Python Packages ***" && \
    pip install --no-cache-dir --no-compile -r /tmp/requirements.txt && \
    rm -f /tmp/requirements.txt && \
    # Clean up Python cache and temporary files
    find /usr/local/lib/python3.12/site-packages -name "*.pyc" -delete && \
    find /usr/local/lib/python3.12/site-packages -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true && \
    rm -rf /root/.cache /tmp/*

# Stage 5: Minimal Calibre installation (changes monthly) - only calibredb
FROM python-stable-deps AS calibre-installer

# Set version labels
ARG VERSION
ARG CALIBRE_RELEASE
LABEL build_version="FFDL-Auto version:- ${VERSION} Calibre: ${CALIBRE_RELEASE}"

# Download and extract only essential Calibre components
RUN echo "**** install minimal calibre (calibredb only) ****" && \
    ARCH=$(uname -m) && \
    echo "Detected architecture: ${ARCH}" && \
    mkdir -p /opt/calibre && \
    if [ "${ARCH}" = "x86_64" ]; then \
    echo "Installing minimal Calibre from official binaries for x86_64" && \
    if [ -z "${CALIBRE_RELEASE}" ]; then \
    CALIBRE_RELEASE_TAG=$(curl -sX GET "https://api.github.com/repos/kovidgoyal/calibre/releases/latest" | jq -r .tag_name); \
    CALIBRE_VERSION=$(echo "${CALIBRE_RELEASE_TAG}" | sed 's/^v//'); \
    else \
    CALIBRE_VERSION=$(echo "${CALIBRE_RELEASE}" | sed 's/^v//'); \
    fi && \
    echo "Using Calibre version: ${CALIBRE_VERSION}" && \
    CALIBRE_URL="https://download.calibre-ebook.com/${CALIBRE_VERSION}/calibre-${CALIBRE_VERSION}-x86_64.txz" && \
    echo "Downloading from ${CALIBRE_URL}" && \
    curl -o /tmp/calibre-tarball.txz -L "${CALIBRE_URL}" && \
    # Extract only essential components for calibredb
    tar xf /tmp/calibre-tarball.txz -C /opt/calibre \
    --wildcards \
    "*/calibredb" \
    "*/lib/python*" \
    "*/resources/*" \
    --exclude="*/bin/calibre" \
    --exclude="*/bin/ebook-*" \
    --exclude="*/bin/fetch-ebook-metadata" \
    --exclude="*/bin/lrf*" \
    --exclude="*/bin/web2disk" \
    --exclude="*/bin/markdown-calibre" && \
    rm -f /tmp/calibre-tarball.txz && \
    # Remove unnecessary GUI and conversion components
    find /opt/calibre -name "*qt*" -type f -delete 2>/dev/null || true && \
    find /opt/calibre -name "*gui*" -type f -delete 2>/dev/null || true && \
    find /opt/calibre -name "*conversion*" -type d -exec rm -rf {} \; 2>/dev/null || true && \
    # Create symlink for calibredb only
    find /opt/calibre -name "calibredb" -type f -executable -exec ln -sf {} /usr/local/bin/calibredb \; ; \
    else \
    echo "Architecture ${ARCH} not supported by official Calibre binaries, installing minimal system package" && \
    apt-get update && \
    # Install only calibre-bin package if available, otherwise full calibre
    (apt-get install -y --no-install-recommends calibre-bin || \
    apt-get install -y --no-install-recommends calibre) && \
    # Remove unnecessary calibre binaries, keep only calibredb
    rm -f /usr/bin/calibre /usr/bin/ebook-* /usr/bin/fetch-ebook-metadata \
    /usr/bin/lrf* /usr/bin/web2disk /usr/bin/markdown-calibre && \
    ln -sf /usr/bin/calibredb /usr/local/bin/calibredb && \
    rm -rf /var/lib/apt/lists/*; \
    fi && \
    echo "*** Testing calibredb installation ***" && \
    calibredb --version && \
    echo "✅ calibredb is working correctly" && \
    echo "*** Minimal Calibre setup complete (calibredb only) ***"

# Stage 6: FanFicFare installation (changes weekly)
FROM calibre-installer AS fanficfare-installer

ARG FANFICFARE_VERSION
RUN echo "*** Install FanFicFare from TestPyPI ***" && \
    if [ -n "${FANFICFARE_VERSION}" ]; then \
    echo "Installing FanFicFare==${FANFICFARE_VERSION}" && \
    pip install --no-cache-dir --no-compile -i https://test.pypi.org/simple/ "FanFicFare==${FANFICFARE_VERSION}"; \
    else \
    echo "Installing latest FanFicFare" && \
    pip install --no-cache-dir --no-compile -i https://test.pypi.org/simple/ FanFicFare; \
    fi && \
    # Clean up Python cache and temporary files after FanFicFare installation
    find /usr/local/lib/python3.12/site-packages -name "*.pyc" -delete && \
    find /usr/local/lib/python3.12/site-packages -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true && \
    rm -rf /root/.cache /tmp/*

# Final runtime stage - minimal, just sets labels and runtime configuration
FROM fanficfare-installer AS runtime

# Set version labels
ARG VERSION
ARG CALIBRE_RELEASE
LABEL build_version="FFDL-Auto version:- ${VERSION} Calibre: ${CALIBRE_RELEASE}"

# Runtime configuration
ENV VERBOSE=false

VOLUME /config
WORKDIR /config

CMD ["/app/entrypoint.sh"]