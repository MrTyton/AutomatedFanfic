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

RUN echo "*** Install FFF ***" && \
    if [ -z ${FFF_RELEASE} ]; then \
		echo "FFF Using Default Release"; \
        python3 -m pip --no-cache-dir install FanFicFare; \
    else \
		echo "FF Using ${FFF_RELEASE} Release"; \
        python3 -m pip --no-cache-dir install --extra-index-url https://testpypi.python.org/pypi FanFicFare==${FFF_RELEASE}; \
    fi

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
