BTRFS Volume plugin for Docker
==============================

This package provides a Docker volume plugin that creates a BTRFS subvolume for
each container volume.

Introduction
------------

`BTRFS <https://btrfs.wiki.kernel.org/>`_ is a next-generation copy-on-write
filesystem with subvolume and snapshot support. A BTRFS `subvolume
<https://btrfs.wiki.kernel.org/index.php/SysadminGuide#Subvolumes>`_ can be
seen as an independant file namespace that can live in a directory and can be
mounted as a filesystem and snapshotted individually.

On the other hand, `Docker volumes
<https://docs.docker.com/engine/tutorials/dockervolumes/>`_ are commonly used
to store persistent data of stateful containers. By default, Docker volumes are
just a dumb directory in the host filesystem.  A number of `Volume plugins
<https://docs.docker.com/engine/extend/legacy_plugins/#/volume-plugins>`_
already exist for various storage backends, including distributed filesystems,
but small clusters often can't afford to deploy a distributed filesystem.

We believe BTRFS subvolumes are a powerful and lightweight storage solution for
Docker volumes, allowing fast and easy replication (and backup) across several
nodes of a small cluster.

Install and run
---------------

First make sure the directory `/var/lib/docker/volumes` is living in a BTRFS filesystem. It can be a BTRFS mountpoint or a BTRFS subvolume or both.

Build and run the provided Dockerfile::

    $ sudo mkdir /run/docker/plugins
    $ docker build -t buttervolume .

Then create a container for buttervolume with access to the host volumes and the unix socket::

    $ sudo docker create -v /var/lib/docker/volumes:/var/lib/docker/volumes -v /run/docker/plugins/:/run/docker/plugins/ --name buttervolume buttervolume
    $ docker start buttervolume

TODO
----

- btrfs send/receive to/from another host
- `nocow` as a plugin option for storing databases
