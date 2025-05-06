FROM python:3-slim

# set version label
ARG VERSION
ARG CALIBRE_RELEASE
LABEL build_version="FFDL-Auto version:- ${VERSION} Calibre: ${CALIBRE_RELEASE}"

ENV PUID="911" \
    PGID="911" \
    VERBOSE=false

RUN set -ex && \
    apt-get update && \
    apt-get install -y --upgrade \
    bash \
    ca-certificates \
    gcc \
    wget \
    xdg-utils \
    curl \
    dbus \
    jq \
    python3

RUN addgroup --gid "$PGID" abc && \
    adduser \
    --gecos "" \
    --disabled-password \
    --no-create-home \
    --uid "$PUID" \
    --ingroup abc \
    --shell /bin/bash \
    abc 

RUN echo "**** install calibre ****" && \
    apt-get install -y calibre && \
    dbus-uuidgen > /etc/machine-id


RUN echo "*** Install Other Python Packages ***"
COPY requirements.txt /tmp/
RUN python3 -m pip install --no-cache-dir -r /tmp/requirements.txt

RUN echo "*** Install FFF ***" && \
    echo "FF Using Test Release"; \
    python3 -m pip install --no-cache-dir -i https://test.pypi.org/simple/ FanFicFare

RUN echo "**** cleanup ****" && \
    rm -rf \
    /tmp/* \
    /var/lib/apt/lists/* \
    /var/tmp/*

COPY root/ /

RUN chmod -R +777 /app/

VOLUME /config

WORKDIR /config

#ENTRYPOINT ["/init"]
CMD sh -c 'if [ "$VERBOSE" = "true" ]; then python -u /app/fanficdownload.py --config="/config/config.toml" --verbose; else python -u /app/fanficdownload.py --config="/config/config.toml"; fi'