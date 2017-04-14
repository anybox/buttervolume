FROM debian:stretch
MAINTAINER Christophe Combelles. <ccomb@anybox.fr>

RUN set -x; \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        btrfs-progs \
        curl \
        ca-certificates \
        python3-setuptools \
        ssh \
        unzip \
        rsync \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/docker/plugins

ENV VERSION master
RUN curl -o buttervolume.zip -SL https://github.com/anybox/buttervolume/archive/${VERSION}.zip \
    && unzip buttervolume.zip \
    && rm buttervolume.zip \
    && mv buttervolume-${VERSION} buttervolume \
    && cd buttervolume \
    && python3 setup.py install \
    && cd .. \
    && rm -rf buttervolume

VOLUME /etc/buttervolume
COPY entrypoint.sh /
ENTRYPOINT ["/entrypoint.sh"]
CMD ["run"]
