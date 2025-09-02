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

# Stage 1: Install runtime system dependencies (rarely change)
FROM python-base AS system-deps

# Install runtime dependencies in a single layer
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    dbus \
    fcitx-rime \
    fonts-wqy-microhei \
    jq \
    libnss3 \
    libopengl0 \
    libxkbcommon-x11-0 \
    libxcb-cursor0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render-util0 \
    libxcb-xinerama0 \
    poppler-utils \
    python3-xdg \
    ttf-wqy-zenhei \
    uuid-runtime \
    xdg-utils \
    xz-utils && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* && \
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

# Install stable Python packages from requirements.txt
COPY requirements.txt /tmp/requirements.txt
RUN echo "*** Install Stable Python Packages ***" && \
    pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm -f /tmp/requirements.txt

# Stage 5: Calibre installation (changes monthly)
FROM python-stable-deps AS calibre-installer

# Set version labels
ARG VERSION
ARG CALIBRE_RELEASE
LABEL build_version="FFDL-Auto version:- ${VERSION} Calibre: ${CALIBRE_RELEASE}"

# Download and extract Calibre (multi-architecture)
RUN echo "**** install calibre ****" && \
    ARCH=$(uname -m) && \
    echo "Detected architecture: ${ARCH}" && \
    mkdir -p /opt/calibre && \
    if [ "${ARCH}" = "x86_64" ]; then \
    echo "Installing Calibre from official binaries for x86_64" && \
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
    tar xf /tmp/calibre-tarball.txz -C /opt/calibre && \
    rm -f /tmp/calibre-tarball.txz; \
    else \
    echo "Architecture ${ARCH} not supported by official Calibre binaries, using system package" && \
    apt-get update && \
    apt-get install -y --no-install-recommends calibre && \
    ln -sf /usr/bin/calibre /opt/calibre/calibre && \
    ln -sf /usr/bin/ebook-convert /opt/calibre/ebook-convert && \
    ln -sf /usr/bin/calibredb /opt/calibre/calibredb && \
    rm -rf /var/lib/apt/lists/*; \
    fi && \
    echo "*** Setting up Calibre ***" && \
    if [ "${ARCH}" = "x86_64" ]; then \
    echo "Setting up official Calibre binaries for x86_64" && \
    if [ -f "/opt/calibre/calibre_postinstall" ]; then \
    chmod +x /opt/calibre/calibre_postinstall && \
    echo "*** Running Calibre post-install ***" && \
    (/opt/calibre/calibre_postinstall || echo "Post-install failed, continuing without it"); \
    fi && \
    echo "*** Setting up Calibre symlinks ***" && \
    find /opt/calibre -name "calibre" -type f -executable -exec ln -sf {} /usr/local/bin/calibre \; && \
    find /opt/calibre -name "ebook-convert" -type f -executable -exec ln -sf {} /usr/local/bin/ebook-convert \; && \
    find /opt/calibre -name "calibredb" -type f -executable -exec ln -sf {} /usr/local/bin/calibredb \; ; \
    else \
    echo "Using system Calibre installation for ${ARCH}" && \
    ln -sf /opt/calibre/calibre /usr/local/bin/calibre && \
    ln -sf /opt/calibre/ebook-convert /usr/local/bin/ebook-convert && \
    ln -sf /opt/calibre/calibredb /usr/local/bin/calibredb; \
    fi && \
    echo "*** Calibre setup complete ***"

# Stage 4: FanFicFare installation (changes weekly)
FROM calibre-installer AS fanficfare-installer

ARG FANFICFARE_VERSION
RUN echo "*** Install FanFicFare from TestPyPI ***" && \
    if [ -n "${FANFICFARE_VERSION}" ]; then \
    echo "Installing FanFicFare==${FANFICFARE_VERSION}" && \
    pip install --no-cache-dir -i https://test.pypi.org/simple/ "FanFicFare==${FANFICFARE_VERSION}"; \
    else \
    echo "Installing latest FanFicFare" && \
    pip install --no-cache-dir -i https://test.pypi.org/simple/ FanFicFare; \
    fi

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