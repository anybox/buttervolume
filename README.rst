BTRFS Volume plugin for Docker
==============================

This package provides a Docker volume plugin that creates a BTRFS subvolume for
each container volume.

Introduction
************

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

Build
*****

You can build a docker image with provided Dockerfile::

    $ cd docker
    $ docker build -t buttervolume .

Run
***

Make sure the directory `/var/lib/docker/volumes` is living in a BTRFS
filesystem. It can be a BTRFS mountpoint or a BTRFS subvolume or both.
You should also create the directory for the unix socket of the plugin::

    $ sudo mkdir /run/docker/plugins

Then create a container for buttervolume with access to the host volumes and
the unix socket

Either from the image you just built::

    $ sudo docker create --privileged -v /var/lib/docker/volumes:/var/lib/docker/volumes -v /run/docker/plugins/:/run/docker/plugins/ --name buttervolume buttervolume
    $ docker start buttervolume

Or directly by pulling a `prebaked image <https://hub.docker.com/r/anybox/buttervolume/>`_ from the Docker hub::

    $ docker run --privileged -v /var/lib/docker/volumes:/var/lib/docker/volumes -v /run/docker/plugins:/run/docker/plugins anybox/buttervolume

Usage
*****

Creating and deleting volumes
-----------------------------

Once the plugin is running, whenever you create a container you can specify the
volume driver with ``docker create --volume-driver=btrfs --name <name> <image>``.
You can also manually create a BTRFS volume with ``docker volume create -d
btrfs``.

When you delete the volume with ``docker rm -v <container>`` or ``docker volume
rm <volume>``, the BTRFS subvolume is deleted. If you snapshotted the volume
elsewhere in the meantime, the snapshots won't be deleted.

Disabling copy-on-write
-----------------------

With `buttervolume` you can disable copy-on-write in a volume by creating a ``.nocow`` file at the
root of the volume. The `buttervolume` plugin will detect it at mount-time and apply ``chattr +C`` on the volume root.

Why disabling copy-on-write? If your docker volume stores databases such as
PostgreSQL or MariaDB, the copy-on-write feature may hurt performance a lot.
The good news is that disabling copy-on-write does not prevent from doing
snaphots, so we get the best of both world: good performances with the ability
to do snapshots.

Creating such a ``.nocow`` file can easily be done in a Dockerfile, before the
``VOLUME`` command:

.. code:: Dockerfile

    RUN mkdir -p /var/lib/postgresql/data \
        && chown -R postgres: /var/lib/postgresql/data \
        && touch /var/lib/postgresql/data/.nocow
    VOLUME /var/lib/postgresql/data

Alternatively you can create the ``.nocow`` file just after the ``docker
create`` command, by inspecting the location of the created volumes with
``docker inspect container | grep volumes``.

Test
****

If your volumes directory is a BTRFS partition or volume, tests can be run with::

    $ sudo python setup.py test

TODO
****

- btrfs send/receive to/from another host
- readonly volumes?
