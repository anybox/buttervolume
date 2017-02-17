FROM debian:stretch
MAINTAINER Christophe Combelles. <ccomb@anybox.fr>

RUN set -x; \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        btrfs-progs \
        ca-certificates \
        git \
        python3-setuptools

RUN git clone http://github.com/anybox/buttervolume \
    && cd buttervolume \
    && python3 setup.py install \
    && cd .. \
    && rm -rf buttervolume \
    && mkdir -p /run/docker/plugins \
    && apt-get remove -y git \
    && rm -rf /var/lib/apt/lists/*

ENTRYPOINT ["buttervolume"]
CMD ["run"]
