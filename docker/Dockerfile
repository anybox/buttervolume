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
    && update-rc.d ssh enable \
    && curl -o buttervolume.zip -SL https://github.com/anybox/buttervolume/archive/master.zip \
    && unzip buttervolume.zip \
    && rm buttervolume.zip \
    && mv buttervolume-master buttervolume \
    && cd buttervolume \
    && python3 setup.py install \
    && cd .. \
    && rm -rf buttervolume \
    && mkdir -p /run/docker/plugins \
    && rm -rf /var/lib/apt/lists/*

VOLUME /etc/buttervolume
COPY entrypoint.sh /
ENTRYPOINT ["/entrypoint.sh"]
CMD ["run"]
