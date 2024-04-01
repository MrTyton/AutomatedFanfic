FROM python:3-slim

# set version label
ARG VERSION
ARG CALIBRE_RELEASE
ARG FFF_RELEASE
LABEL build_version="FFDL-Auto version:- ${VERSION} Calibre: ${CALIBRE_RELEASE} FFF: ${FFF_RELEASE}"

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
 

RUN echo "**** s6 omsta;; ****" && \
    ARCH=`uname -m` && \
    if [ "$ARCH" = "x86_64" ]; then \
        s6_package="s6-overlay-amd64.tar.gz" ; \
    elif [ "$ARCH" = "aarch64" ]; then \
        s6_package="s6-overlay-aarch64.tar.gz" ; \
    else \
        echo "unknown arch: ${ARCH}" && \
        exit 1 ; \
    fi && \
    wget -P /tmp/ https://github.com/just-containers/s6-overlay/releases/download/v2.2.0.3/${s6_package} && \
    tar -xzf /tmp/${s6_package} -C /

RUN echo "FF Using ${FFF_RELEASE} Release"; && \
    python3 -m pip --no-cache-dir install --extra-index-url https://testpypi.python.org/pypi FanFicFare==${FFF_RELEASE}
	

RUN echo "*** Install Other Python Packages ***" && \
	python3 -m pip --no-cache-dir install pushbullet.py pillow

RUN echo "*** SymLink Calibredb ***" && \
	ln -s /opt/calibre/calibredb /bin/calibredb
	
RUN echo "**** cleanup ****" && \
 rm -rf \
	/tmp/* \
	/var/lib/apt/lists/* \
	/var/tmp/*

COPY root/ /

VOLUME /config

WORKDIR /config

ENTRYPOINT ["/init"]
