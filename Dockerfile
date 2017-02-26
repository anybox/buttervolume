FROM debian:stretch
MAINTAINER Christophe Combelles. <ccomb@anybox.fr>

RUN set -x; \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        btrfs-progs \
        ca-certificates \
        python3-setuptools \
        ssh \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/docker/plugins

COPY . /buttervolume
RUN cd /buttervolume \
    && python3 setup.py install \
    && cd .. \
    && rm -rf buttervolume


VOLUME /etc/buttervolume
COPY entrypoint.sh /
ENTRYPOINT ["/entrypoint.sh"]
CMD ["run"]
