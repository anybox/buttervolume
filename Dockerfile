FROM debian:stretch
MAINTAINER Christophe Combelles. <ccomb@anybox.fr>

RUN set -x; \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        btrfs-progs \
        ca-certificates \
        python3-setuptools

COPY . /buttervolume
RUN cd /buttervolume \
    && python3 setup.py install \
    && cd .. \
    && rm -rf buttervolume \
    && mkdir -p /run/docker/plugins \
    && rm -rf /var/lib/apt/lists/*

VOLUME /etc/buttervolume
ENTRYPOINT ["buttervolume"]
CMD ["run"]
