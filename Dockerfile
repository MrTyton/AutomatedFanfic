FROM python:3-slim

# set version label
ARG VERSION
ARG CALIBRE_RELEASE
LABEL build_version="FFDL-Auto version:- ${VERSION} Calibre: ${CALIBRE_RELEASE}"

ENV PUID="911" \
    PGID="911" \
    VERBOSE=false \
    DEBIAN_FRONTEND=noninteractive


RUN set -ex && \
    echo "**** install dependencies ****" && \
      apt-get update && \
      apt-get install -y --upgrade --no-install-recommends \
        bash \
        ca-certificates \
        gcc \
        wget \
        xdg-utils \
        curl \
        dbus \
        jq \
        python3 \
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
        xz-utils && \
    echo "**** cleaning up ****" && \
      apt-get clean && \
      rm -rf \
        /tmp/* \
        /var/lib/apt/lists/* \
        /var/tmp/*
	
RUN echo "**** install calibre ****" && \
      mkdir -p \
        /opt/calibre && \
      if [ -z ${CALIBRE_RELEASE+x} ]; then \
        CALIBRE_RELEASE=$(curl -sX GET "https://api.github.com/repos/kovidgoyal/calibre/releases/latest" \
        | jq -r .tag_name); \
      fi && \
      CALIBRE_VERSION="$(echo ${CALIBRE_RELEASE} | cut -c2-)" && \
      CALIBRE_URL="https://download.calibre-ebook.com/${CALIBRE_VERSION}/calibre-${CALIBRE_VERSION}-x86_64.txz" && \
      curl -o \
        /tmp/calibre-tarball.txz -L \
        "$CALIBRE_URL" && \
      tar xvf /tmp/calibre-tarball.txz -C \
        /opt/calibre && \
      /opt/calibre/calibre_postinstall && \
      dbus-uuidgen > /etc/machine-id && \
      rm -rf /tmp/calibre-tarball.txz

COPY requirements.txt /tmp/
RUN echo "*** Install Other Python Packages ***" && \
      python3 -m pip install --no-cache-dir -r /tmp/requirements.txt && \
    echo "*** Install FFF ***" && \
    echo "FF Using Test Release" && \
      python3 -m pip install --no-cache-dir -i https://test.pypi.org/simple/ FanFicFare && \
    echo "**** cleaning up ****" && \
      rm -rf /tmp/*

COPY root/ /

RUN addgroup --gid "$PGID" abc && \
    adduser \
    --gecos "" \
    --disabled-password \
    --no-create-home \
    --uid "$PUID" \
    --ingroup abc \
    --shell /bin/bash \
    abc && \
    chmod -R +777 /app/

VOLUME /config

WORKDIR /config

#ENTRYPOINT ["/init"]
CMD ["/app/entrypoint.sh"]
