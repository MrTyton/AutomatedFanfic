#!/usr/bin/env bash
# slim-analyze.sh
# Local SlimToolkit analysis for automated-ffdl.
#
# Usage:
#   ./scripts/slim-analyze.sh [xray|build|both]  [image_tag]
#
# Arguments:
#   mode       xray  – static layer analysis only (default, no config needed)
#              build – dynamic analysis using production config (see below)
#              both  – run xray, then build
#   image_tag  Local image tag to analyze (default: automated-ffdl:local)
#              Pass an existing DockerHub tag (e.g. latest) to skip local build.
#
# Production config for dynamic analysis:
#   Place your config.toml (and optionally defaults.ini / personal.ini) in:
#     root/config.default/Actual Configs/ffdl/
#   These files are git-ignored and will never be committed.
#   slim build mounts that directory to /config inside the analysis container.
#
# Requirements:
#   - Docker (running)
#   - slim binary in PATH  OR  docker image dslim/slim available
#     Install: curl -sL https://raw.githubusercontent.com/slimtoolkit/slim/master/scripts/install-slim.sh | sudo -E bash -
#
# Examples:
#   ./scripts/slim-analyze.sh                     # xray on freshly built local image
#   ./scripts/slim-analyze.sh build               # dynamic analysis with production config
#   ./scripts/slim-analyze.sh both latest         # both modes against DockerHub :latest
# ---------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

MODE="${1:-xray}"
IMAGE_TAG="${2:-automated-ffdl:local}"
CONFIG_DIR="$REPO_ROOT/root/config.default/Actual Configs/ffdl"
DOCKERHUB_IMAGE="mrtyton/automated-ffdl"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*" >&2; }
error() { echo "[ERROR] $*" >&2; exit 1; }

have_slim() { command -v slim &>/dev/null; }

run_slim() {
    # Run slim either natively or via Docker container
    if have_slim; then
        slim "$@"
    else
        info "slim binary not found – falling back to dslim/slim container"
        docker run --rm \
            -v /var/run/docker.sock:/var/run/docker.sock \
            dslim/slim "$@"
    fi
}

# ---------------------------------------------------------------------------
# Build local image if the tag doesn't already exist and isn't a remote ref
# ---------------------------------------------------------------------------
ensure_image() {
    local tag="$1"
    if docker image inspect "$tag" &>/dev/null; then
        info "Image '$tag' already present locally – skipping build."
        return
    fi

    # If user passed e.g. "latest" or a version number, try pulling from DockerHub
    if [[ "$tag" != *":"* ]] || [[ "$tag" == *"automated-ffdl"* && "$tag" != "automated-ffdl:local" ]]; then
        local pull_tag="$tag"
        [[ "$tag" != *"/"* ]] && pull_tag="$DOCKERHUB_IMAGE:$tag"
        info "Pulling '$pull_tag' from DockerHub..."
        docker pull "$pull_tag"
        # Re-tag to the requested local name for consistency
        [[ "$pull_tag" != "$tag" ]] && docker tag "$pull_tag" "$tag"
        return
    fi

    # Fall back to local build
    info "Building '$tag' from local Dockerfile..."
    docker build -t "$tag" "$REPO_ROOT"
}

# ---------------------------------------------------------------------------
# xray – static layer analysis
# ---------------------------------------------------------------------------
do_xray() {
    local tag="$1"
    info "=== slim xray: static analysis of '$tag' ==="
    run_slim xray \
        --changes all \
        --add-image-manifest \
        --add-image-config \
        --show-special-perms \
        --detect-duplicates \
        "$tag"
}

# ---------------------------------------------------------------------------
# build – dynamic analysis
# ---------------------------------------------------------------------------
do_build() {
    local tag="$1"
    local slim_tag="${tag}.slim"

    info "=== slim build: dynamic analysis of '$tag' ==="

    # Verify production config exists
    if [[ ! -f "$CONFIG_DIR/config.toml" ]]; then
        error "Production config not found at: $CONFIG_DIR/config.toml
Place your config.toml in:
  root/config.default/Actual Configs/ffdl/config.toml
This directory is git-ignored."
    fi

    info "Using production config from: $CONFIG_DIR"
    info "Slim will start the app for ~45 seconds to observe file access patterns."
    info "Resulting slimmed image will be tagged: $slim_tag"
    info ""

    # Notes:
    # --http-probe=false     this is a daemon, not an HTTP service
    # --mount                inject production config as /config volume
    # --continue-after=45    observe the running app for 45 s before slimming
    # --show-clogs           stream app container logs so you can verify startup
    # --include-shell        keep /bin/sh in the slimmed image for debugging
    run_slim build \
        --http-probe=false \
        --mount "$CONFIG_DIR:/config" \
        --continue-after=45 \
        --show-clogs \
        --include-shell \
        --tag "$slim_tag" \
        "$tag"

    echo ""
    info "=== Size comparison ==="
    docker images "$tag"     --format "Original  {{.Repository}}:{{.Tag}}  →  {{.Size}}"
    docker images "$slim_tag" --format "Slimmed   {{.Repository}}:{{.Tag}}  →  {{.Size}}" || true
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
ensure_image "$IMAGE_TAG"

case "$MODE" in
    xray)
        do_xray "$IMAGE_TAG"
        ;;
    build)
        do_build "$IMAGE_TAG"
        ;;
    both)
        do_xray "$IMAGE_TAG"
        echo ""
        do_build "$IMAGE_TAG"
        ;;
    *)
        error "Unknown mode '$MODE'. Use: xray | build | both"
        ;;
esac
