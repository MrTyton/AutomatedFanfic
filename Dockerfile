FROM python:3.9-alpine

# set version label
ARG VERSION
ARG CALIBRE_RELEASE
ARG FFF_RELEASE
LABEL build_version="FFDL-Auto version:- ${VERSION} Calibre: ${CALIBRE_RELEASE} FFF: ${FFF_RELEASE}"

ENV PUID="911" \
    PGID="911"

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
	python3
	
RUN set -x && \
    addgroup --gid "$PGID" abc && \
    adduser \
        --gecos "" \
        --disabled-password \
        --no-create-home \
        --uid "$PUID" \
        --ingroup abc \
        --shell /bin/bash \
        abc 
		
RUN echo "**** install calibre ****" && \
 set -x && \
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
 dbus-uuidgen > /etc/machine-id
 
RUN echo "**** cleanup ****" && \
 rm -rf \
	/tmp/* \
	/var/lib/apt/lists/* \
	/var/tmp/*
	
RUN echo "**** s6 omsta;; ****" && \
	set -ex && \
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
    tar -xzf /tmp/${s6_package} -C / && \
    rm -rf /tmp/*

RUN echo *** Install Packages *** && \
	set -x && \
	apk add --no-cache --upgrade py-pillow && \
    if [ -z ${FFF_RELEASE+x} ]; then \
        python3 -m pip --no-cache-dir install FanFicFare; \
    else \
        python3 -m pip --no-cache-dir install --extra-index-url https://testpypi.python.org/pypi FanFicFare==${FFF_RELEASE}; \
    fi && \
	python3 -m pip --no-cache-dir install pushbullet.py && \
    ln -s /opt/calibre/calibredb /bin/calibredb

COPY root/ /

RUN chmod +x /app/run.sh

VOLUME /config

WORKDIR /config

ENTRYPOINT ["/init"]
