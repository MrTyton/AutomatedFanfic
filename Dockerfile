FROM python:3-slim

# set version label
ARG VERSION
ARG CALIBRE_RELEASE
ARG FFF_RELEASE
ARG S6_OVERLAY_VERSION
LABEL build_version="FFDL-Auto version:- ${VERSION} Calibre: ${CALIBRE_RELEASE} FFF: ${FFF_RELEASE} S6_OVERLAY_VERSION: ${S6_OVERLAY_VERSION}"

ENV PUID="911" \
    PGID="911"

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
    if [ -z ${FFF_RELEASE} ]; then \
		echo "FFF Using Default Release"; \
        python3 -m pip --no-cache-dir install FanFicFare; \
	else \
		echo "FF Using ${FFF_RELEASE} Release"; \
        python3 -m pip --no-cache-dir install --extra-index-url https://testpypi.python.org/pypi FanFicFare==${FFF_RELEASE}; \
    fi
	
ADD https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz /tmp
RUN tar -C / -Jxpf /tmp/s6-overlay-noarch.tar.xz
ADD https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-x86_64.tar.xz /tmp
RUN tar -C / -Jxpf /tmp/s6-overlay-x86_64.tar.xz
ADD https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-symlinks-noarch.tar.xz /tmp
RUN tar -C / -Jxpf /tmp/s6-overlay-symlinks-noarch.tar.xz 
ADD https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-symlinks-arch.tar.xz /tmp
RUN tar -C / -Jxpf /tmp/s6-overlay-symlinks-arch.tar.xz

RUN echo "**** cleanup ****" && \
 rm -rf \
	/tmp/* \
	/var/lib/apt/lists/* \
	/var/tmp/*

COPY root/ /

RUN chmod -R +777 /etc/cont-init.d/
RUN chmod -R +777 /etc/s6-overlay/

VOLUME /config

WORKDIR /config

ENTRYPOINT ["/init"]
