FROM debian:bullseye
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
    && mkdir -p /run/docker/plugins \
    && mkdir -p /var/lib/buttervolume/volumes \
    && mkdir -p /var/lib/buttervolume/snapshots \
    && mkdir /etc/buttervolume /root/.ssh

ENV VERSION master
RUN curl -o buttervolume.zip -SL https://github.com/anybox/buttervolume/archive/${VERSION}.zip \
    && unzip buttervolume.zip \
    && rm buttervolume.zip \
    && mv buttervolume-${VERSION} buttervolume \
    && cd buttervolume \
    && python3 setup.py install \
    && cd .. \
    && rm -rf buttervolume

# add tini to avoid sshd zombie processes
ENV TINI_VERSION v0.19.0
ADD https://github.com/krallin/tini/releases/download/${TINI_VERSION}/tini /tini
RUN chmod +x /tini

COPY entrypoint.sh /
ENTRYPOINT ["/entrypoint.sh"]
CMD ["run"]
