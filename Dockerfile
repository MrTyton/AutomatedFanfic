FROM lscr.io/linuxserver/calibre:latest

# set version label
ARG VERSION
ARG CALIBRE_RELEASE
ARG FFF_RELEASE
LABEL build_version="FFDL-Auto version:- ${VERSION} Calibre: ${CALIBRE_RELEASE} FFF: ${FFF_RELEASE}"

ENV PUID="911" \
    PGID="911" \
	GUIAUTOSTART="false"

RUN set -x && \
    apk update && \
    apk add --no-cache --upgrade \
    bash \
    ca-certificates \
    gcc \
    mesa-gl \
    qt5-qtbase-x11 \
    wget \
    xdg-utils \
    xz \
    curl \
    dbus \
	jq \
	python3.9 \
	shadow
	

RUN echo *** Install Packages *** && \
	set -x && \
	apt-get install --upgrade py-pillow && \
    if [ -z ${FFF_RELEASE+x} ]; then \
        python3.9 -m pip --no-cache-dir install FanFicFare; \
    else \
        python3.9 -m pip --no-cache-dir install --extra-index-url https://testpypi.python.org/pypi FanFicFare==${FFF_RELEASE}; \
    fi && \
	python3.9 -m pip --no-cache-dir install pushbullet.py && \
    ln -s /opt/calibre/calibredb /bin/calibredb

RUN echo "**** cleanup ****" && \
 apt-get clean && \
 rm -rf \
	/tmp/* \
	/var/lib/apt/lists/* \
	/var/tmp/*

COPY root/ /

VOLUME /config

WORKDIR /config

ENTRYPOINT ["/init"]
