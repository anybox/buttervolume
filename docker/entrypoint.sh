#!/bin/bash

SSH_PORT=${SSH_PORT:-1122}

echo "Port 1122" >> /etc/ssh/sshd_config
service ssh start

if [[ $1 == 'test' ]]; then
    set -e
    set -x
    # create ssh key which let root users to access to localhost
    # to test send btrfs sends methods over ssh
    ssh-keygen -f /root/.ssh/id_rsa -N ""
    cat /root/.ssh/id_rsa.pub >> /root/.ssh/authorized_keys
    chmod 600 /root/.ssh/authorized_keys
    ssh-keyscan -p 1122 localhost >> /root/.ssh/known_hosts

    exec python3 setup.py $@
else
    exec buttervolume $@
fi
