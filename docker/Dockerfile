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
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /run/docker/plugins \
    && echo "Port 1122" >> /etc/ssh/sshd_config

RUN curl -o buttervolume.zip -SL https://github.com/anybox/buttervolume/archive/master.zip \
    && unzip buttervolume.zip \
    && rm buttervolume.zip \
    && mv buttervolume-master buttervolume \
    && cd buttervolume \
    && python3 setup.py install \
    && cd .. \
    && rm -rf buttervolume

VOLUME /etc/buttervolume
COPY entrypoint.sh /
ENTRYPOINT ["/entrypoint.sh"]
CMD ["run"]
