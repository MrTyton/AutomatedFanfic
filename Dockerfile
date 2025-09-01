# Use a multi-stage build for better layer caching and smaller final image
FROM python:3.12-slim as python-base

# Set up environment variables early
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build stage for Calibre installation
FROM python-base as calibre-installer

# Set version labels
ARG VERSION
ARG CALIBRE_RELEASE
LABEL build_version="FFDL-Auto version:- ${VERSION} Calibre: ${CALIBRE_RELEASE}"

ENV DEBIAN_FRONTEND=noninteractive

# Install only what's needed for Calibre download and extraction
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    jq \
    xz-utils && \
    rm -rf /var/lib/apt/lists/*

# Download and extract Calibre in build stage
RUN echo "**** install calibre ****" && \
    mkdir -p /opt/calibre && \
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
    rm -f /tmp/calibre-tarball.txz

# Final runtime stage
FROM python-base as runtime

# Set version labels
ARG VERSION
ARG CALIBRE_RELEASE
LABEL build_version="FFDL-Auto version:- ${VERSION} Calibre: ${CALIBRE_RELEASE}"

ENV PUID="911" \
    PGID="911" \
    VERBOSE=false \
    DEBIAN_FRONTEND=noninteractive

# Install runtime dependencies in a single layer
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    dbus \
    fcitx-rime \
    fonts-wqy-microhei \
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
    xdg-utils \
    uuid-runtime && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Copy Calibre from build stage
COPY --from=calibre-installer /opt/calibre /opt/calibre

# Set up Calibre environment and check dependencies
RUN echo "*** Setting up Calibre ***" && \
    find /opt/calibre -name "calibre_postinstall" -exec ls -la {} \; && \
    chmod +x /opt/calibre/calibre_postinstall && \
    echo "*** Checking calibre_postinstall dependencies ***" && \
    ldd /opt/calibre/calibre_postinstall || echo "ldd failed, trying file command" && \
    file /opt/calibre/calibre_postinstall && \
    echo "*** Attempting to run Calibre post-install ***" && \
    (/opt/calibre/calibre_postinstall || echo "Post-install failed, continuing without it") && \
    echo "*** Generating machine ID ***" && \
    dbus-uuidgen > /etc/machine-id && \
    echo "*** Setting up Calibre symlinks manually ***" && \
    find /opt/calibre -name "calibre" -type f -executable -exec ln -sf {} /usr/local/bin/calibre \; && \
    find /opt/calibre -name "ebook-convert" -type f -executable -exec ln -sf {} /usr/local/bin/ebook-convert \; && \
    find /opt/calibre -name "calibredb" -type f -executable -exec ln -sf {} /usr/local/bin/calibredb \; && \
    echo "*** Calibre setup complete ***"

# Install Python dependencies
COPY requirements.txt /tmp/requirements.txt
RUN echo "*** Install Python Packages ***" && \
    pip install --no-cache-dir -r /tmp/requirements.txt && \
    echo "*** Install FanFicFare from TestPyPI ***" && \
    pip install --no-cache-dir -i https://test.pypi.org/simple/ FanFicFare && \
    rm -f /tmp/requirements.txt

# Copy application files
COPY root/ /

# Create user and set permissions
RUN groupadd --gid "$PGID" abc && \
    useradd --create-home --shell /bin/bash --uid "$PUID" --gid abc abc && \
    chmod -R +x /app/ && \
    chown -R abc:abc /app/

VOLUME /config
WORKDIR /config

CMD ["/app/entrypoint.sh"]