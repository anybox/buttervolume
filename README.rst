.. image:: https://travis-ci.org/anybox/buttervolume.svg?branch=master
   :target: https://travis-ci.org/anybox/buttervolume
   :alt: Travis state


BTRFS Volume plugin for Docker
==============================

This package provides a Docker volume plugin that creates a BTRFS subvolume for
each container volume.

Please note this is **not** a BTRFS storage driver for Docker, but a plugin to manage only
volumes. It means you can use any storage driver, such as AUFS, this is independant topic.

.. contents::


Introduction
************

`BTRFS <https://btrfs.wiki.kernel.org/>`_ is a next-generation copy-on-write
filesystem with subvolume and snapshot support. A BTRFS `subvolume
<https://btrfs.wiki.kernel.org/index.php/SysadminGuide#Subvolumes>`_ can be
seen as an independant file namespace that can live in a directory and can be
mounted as a filesystem and snapshotted individually.

On the other hand, `Docker volumes
<https://docs.docker.com/engine/tutorials/dockervolumes/>`_ are commonly used
to store persistent data of stateful containers, such as a MySQL/PostgreSQL
database or an upload directory of a CMS. By default, Docker volumes are just a
dumb directory in the host filesystem.  A number of `Volume plugins
<https://docs.docker.com/engine/extend/legacy_plugins/#/volume-plugins>`_
already exist for various storage backends, including distributed filesystems,
but small clusters often can't afford to deploy a distributed filesystem.

We believe BTRFS subvolumes are a powerful and lightweight storage solution for
Docker volumes, allowing fast and easy replication (and backup) across several
nodes of a small cluster.


Build
*****

You can build a docker image with the provided Dockerfile::

    $ cd docker
    $ docker build -t buttervolume .


Install and run
***************

Make sure the directory ``/var/lib/buttervolume/`` is living in a BTRFS
filesystem. It can be a BTRFS mountpoint or a BTRFS subvolume or both.
You should also create the directory for the unix socket of the plugin::

    $ sudo mkdir /run/docker/plugins

Then create a container for buttervolume with access to the host volumes and
the unix socket

Either from the image you just built::

    $ sudo docker create --privileged -v /var/lib/docker:/var/lib/docker -v /run/docker/plugins/:/run/docker/plugins/ --name buttervolume buttervolume
    $ docker start buttervolume

Or directly by pulling a `prebaked image <https://hub.docker.com/r/anybox/buttervolume/>`_ from the Docker hub::

    $ docker run --privileged -v /var/lib/buttervolume/volumes:/var/lib/buttervolume/volumes -v /run/docker/plugins:/run/docker/plugins anybox/buttervolume

You can also locally install and run the plugin with::

    $ virtualenv venv
    $ ./venv/bin/python setup.py develop
    $ sudo ./venv/bin/buttervolume run


Configure
*********

You can configure the following variables:

    * ``VOLUMES_PATH``: the path were the BTRFS volumes are located
    * ``SNAPSHOTS_PATH``: the path were the BTRFS snapshots are located
    * ``TEST_REMOTE_PATH``: the path during unit tests were the remote BTRFS snapshots are located
    * ``SCHEDULE``: the path of the scheduler configuration
    * ``SOCKET``: the path of the unix socket were buttervolume listen
    * ``TIMER``: the number of seconds between two runs of the scheduler
    * ``DTFORMAT``: the format of the datetime in the logs
    * ``LOGLEVEL``: the Python log level (INFO, DEBUG, etc.)

The configuration can be done in this order of priority:

    #. from an environment variable prefixed with ``BUTTERVOLUME_`` (ex: ``BUTTERVOLUME_TIMER=120``)
    #. from the ``/etc/buttervolume/config.ini`` file in the [DEFAULT] section

Example of ``config.ini`` file::

    [DEFAULT]
    TIMER = 120

If none of this is configured, the following default values are taken:

    * ``VOLUMES_PATH = /var/lib/buttervolume/volumes/``
    * ``SNAPSHOTS_PATH = /var/lib/buttervolume/snapshots/``
    * ``TEST_REMOTE_PATH = /var/lib/buttervolume/received/``
    * ``SCHEDULE = /etc/buttervolume/schedule.csv``
    * ``SOCKET = /run/docker/plugins/btrfs.sock``
    * ``TIMER = 60``
    * ``DTFORMAT = %Y-%m-%dT%H:%M:%S.%f``
    * ``LOGLEVEL = INFO``


Usage
*****

Running the plugin
------------------

If you installed it locally, You can start the plugin with::

    $ sudo buttervolume run

If you're running it in a privileged container, it will be automatically started.

When started it will create a unix socket ``/var/run/docker/plugins/btrfs.sock`` for use by
Docker. The name of the socket file is actually the name of the plugin you can
use with ``docker volume create -d <driver>`` or ``docker create --volume-driver=<driver>``.  when started, the plugin will also start
its own scheduler to run periodic jobs (such as a snapshot, replication, purge or synchronization)


Creating and deleting volumes
-----------------------------

Once the plugin is running, whenever you create a container you can specify the
volume driver with ``docker create --volume-driver=btrfs --name <name>
<image>``.  You can also manually create a BTRFS volume with ``docker volume
create -d btrfs``. It also works with docker-compose, by specifying the
``btrfs`` driver in the ``volumes`` section of the compose file.

When you delete the volume with ``docker rm -v <container>`` or ``docker volume
rm <volume>``, the BTRFS subvolume is deleted. If you snapshotted the volume
elsewhere in the meantime, the snapshots won't be deleted.


Managing volumes and snapshots
------------------------------

When buttervolume is installed, it provides a command line tool
``buttervolume``, with the following subcommands::

    run                 Run the plugin in foreground
    snapshot            Snapshot a volume
    snapshots           List snapshots
    schedule            (un)Schedule a snapshot, replication or purge
    scheduled           List scheduled actions
    restore             Restore a snapshot (optionally to a different volume)
    clone               Clone a volume as new volume
    send                Send a snapshot to another host
    sync                Synchronise a volume from a remote host volume
    rm                  Delete a snapshot
    purge               Purge old snapshot using a purge pattern


Create a snapshot
-----------------

You can create a readonly snapshot of the volume with::

    $ buttervolume snapshot <volume>

The volumes are currently expected to live in ``/var/lib/buttervolume/volumes`` and
the snapshot will be created in ``/var/lib/docker/snapshots``, by appending the
datetime to the name of the volume, separated with ``@``.


List the snapshots
------------------

You can list all the snapshots::

    $ buttervolume snapshots

or just the snapshots corresponding to a volume with::

    $ buttervolume snapshots <volume>

``<volume>`` is the name of the volume, not the full path. It is expected
to live in ``/var/lib/buttervolume/volumes``.


Restore a snapshot
------------------

You can restore a snapshot as a volume. The current volume will first
be snapshotted, deleted, then replaced with the snapshot.  If you provide a
volume name instead of a snapshot, the **latest snapshot** is restored. So no
data is lost if you do something wrong. Please take care of stopping the
container before restoring a snapshot::

    $ buttervolume restore <snapshot>

``<snapshot>`` is the name of the snapshot, not the full path. It is expected
to live in ``/var/lib/docker/snapshots``.

By default, the volume name corresponds to the volume the snapshot was created
from. But you can optionally restore the snapshot to a different volume name by
adding the target as the second argument::

    $ buttervolume restore <snapshot> <volume>


Clone a volume
------------------

You can clone a volume as a new volume. The current volume will be cloned
as a new volume name given as parameter. Please take care of stopping the
container before clonning a volume::

    $ buttervolume clone <volume> <new_volume>

``<volume>`` is the name of the volume to be cloned, not the full path. It is expected
to live in ``/var/lib/buttervolume/volumes``.
``<new_volume>`` is the name of the new volume to be created as clone of previous one,
not the full path. It is expected to be created in ``/var/lib/buttervolume/volumes``.


Delete a snapshot
-----------------

You can delete a snapshot with::

    $ buttervolume rm <snapshot>

``<snapshot>`` is the name of the snapshot, not the full path. It is expected
to live in ``/var/lib/docker/snapshots``.


Replicate a snapshot to another host
------------------------------------

You can incrementally send snapshots to another host, so that data is
replicated to several machines, allowing to quickly move a stateful docker
container to another host. The first snapshot is first sent as a whole, then
the next snapshots are used to only send the difference between the current one
and the previous one. This allows to replicate snapshots very often without
consuming a lot of bandwith or disk space::

    $ buttervolume send <host> <snapshot>

``<snapshot>`` is the name of the snapshot, not the full path. It is expected
to live in ``/var/lib/docker/snapshots`` and is replicated to the same path on
the remote host.


``<host>`` is the hostname or IP address of the remote host. The snapshot is
currently sent using BTRFS send/receive through ssh. This requires that ssh
keys be present and already authorized on the target host, and that the
``StrictHostKeyChecking no`` option be enabled in ``~/.ssh/config``.


Synchronize a volume from another host volume
---------------------------------------------

You can receive data from a remote volume, so in case there is a volume on
the remote host with the **same name**, it will get new and most recent data
from the distantant volume and replace in the local volume. Before running the
``rsync`` command a snapshot is made on the locale machine to manage recovery::

    $ buttervolume sync <volume> <host1> [<host2>][...]

The intent is to synchronize a volume between multi hosts on running
containers, so you should schedule that action on each nodes from all remote
hosts.

.. note::

   As we are pulling data from multiple hosts we never remove data, consider
   removing scheduled actions before removing data on each hosts.

.. warning::

   Make sure your application is able to handle such synchronisation


Purge old snapshots
-------------------

You can purge old snapshot corresponding to the specified volume, using a retention pattern::

    $ buttervolume purge <pattern> <volume>

If you're unsure whether you retention pattern is correct, you can run the
purge with the ``--dryrun`` option, to inspect what snapshots would be deleted,
without deleting them::

    $ buttervolume purge --dryrun <pattern> <volume>

``<volume>`` is the name of the volume, not the full path. It is expected
to live in ``/var/lib/buttervolume/volumes``.

``<pattern>`` is the snapshot retention pattern. It is a semicolon-separated
list of time length specifiers with a unit. Units can be ``m`` for minutes,
``h`` for hours, ``d`` for days, ``w`` for weeks, ``y`` for years. The pattern
should have at least 2 items.

Here are a few examples of retention patterns:

- ``4h:1d:2w:2y``
    Keep all snapshots in the last four hours, then keep only one snapshot
    every four hours during the first day, then one snapshot per day during
    the first two weeks, then one snapshot every two weeks during the first
    two years, then delete everything after two years.

- ``4h:1w``
    keep all snapshots during the last four hours, then one snapshot every
    four hours during the first week, then delete older snapshots.

- ``2h:2h``
    keep all snapshots during the last two hours, then delete older snapshots.


Schedule a job
--------------

You can schedule a periodic job, such as a snapshot, a replication, a
synchronization or a purge. The schedule it self is stored in
``/etc/buttervolume/schedule.csv``.

**Schedule a snapshot** of a volume every 60 minutes::

    $ buttervolume schedule snapshot 60 <volume>

Remove the same schedule by specifying a timer of 0 min::

    $ buttervolume schedule snapshot 0 <volume>

**Schedule a replication** of volume ``foovolume`` to ``remote_host``::

    $ buttervolume schedule replicate:remote_host 3600 foovolume

Remove the same schedule::

    $ buttervolume schedule replicate:remote_host 0 foovolume

**Schedule a purge** every hour of the snapshots of volume ``foovolume``, but
keep all the snapshots in the last 4 hours, then only one snapshot every 4
hours during the first week, then one snapshot every week during one year, then
delete all snapshots after one year::

    $ buttervolume schedule purge:4h:1w:1y 60 foovolume

Remove the same schedule::

    $ buttervolume schedule purge:4h:1w:1y 0 foovolume

Using the right combination of snapshot schedule timer, purge schedule timer
and purge retention pattern, you can create you own backup strategy, from the
simplest ones to more elaborate ones. A common one is the following::

    $ buttervolume schedule snapshot 1440 <volume>
    $ buttervolume schedule purge:1d:4w:1y 1440 <volume>

It should create a snapshot every day, then purge snapshots everydays while
keeping all snapshots in the last 24h, then one snapshot per day during one
month, then one snapshot per month during only one year.

**Schedule a syncrhonization** of volume ``foovolume`` from ``remote_host1``
abd ``remote_host2``::

    $ buttervolume schedule synchronize:remote_host1,remote_host2 60 foovolume

Remove the same schedule::

    $ buttervolume schedule synchronize:remote_host1,remote_host2 0 foovolume


List scheduled jobs
-------------------

You can list all the scheduled job with::

    $ buttervolume scheduled

It will display the schedule in the same format used for adding the schedule,
which is convenient to remove an existing schedule or add a similar one.


Copy-on-write
-------------

Copy-On-Write is disabled by default.

Why disabling copy-on-write? If your docker volume stores databases such as
PostgreSQL or MariaDB, the copy-on-write feature may hurt performance a lot.
The good news is that disabling copy-on-write does not prevent from doing
snaphots, so we get the best of both world: good performances with the ability
to do snapshots.


Test
****

If your volumes directory is a BTRFS partition or volume, tests can be run
with::

    $ sudo SSH_PORT=22 python3 setup.py test

22 being the port of your running ssh server with authorized key,
or using and testing the docker image (with python >= 3.5)::

    $ docker build -t anybox/buttervolume docker/
    $ sudo docker run -it --rm --privileged \
        -v /var/lib/docker:/var/lib/docker \
        -v "$PWD":/usr/src/buttervolume \
        -w /usr/src/buttervolume \
        anybox/buttervolume test

If you have no BTRFS partitions or volumes you can setup a virtual partition
in a file as follows (tested on Debian 8):

* Setup BTRFS virtual partition::

    $ sudo qemu-img create /var/lib/docker/btrfs.img 10G
    Formatting '/var/lib/docker/btrfs.img', fmt=raw size=10737418240
    $ sudo mkfs.btrfs /var/lib/docker/btrfs.img
    Btrfs v3.17
    See http://btrfs.wiki.kernel.org for more information.

    Turning ON incompat feature 'extref': increased hardlink limit per file to 65536
    ERROR: device scan failed '/var/lib/docker/btrfs.img' - Block device required
    fs created label (null) on /var/lib/docker/btrfs.img
        nodesize 16384 leafsize 16384 sectorsize 4096 size 10.00GiB

.. note::

   you can ignore the error, in fact the new FS is formatted

* Mount the partition somewhere temporarily to create 3 new BTRFS subvolumes::

    $ sudo mkdir /tmp/btrfs_mount_point \
        && sudo mount -o loop /var/lib/docker/btrfs.img /tmp/btrfs_mount_point/ \
        && sudo btrfs subvolume create /tmp/btrfs_mount_point/snapshots \
        && sudo btrfs subvolume create /tmp/btrfs_mount_point/volumes \
        && sudo btrfs subvolume create /tmp/btrfs_mount_point/received \
        && sudo umount /tmp/btrfs_mount_point/ \
        && sudo rm -r /tmp/btrfs_mount_point/

* Stop docker, create required mount point and restart docker::

    $ sudo systemctl stop docker \
        && sudo mkdir -p /var/lib/buttervolume/volumes \
        && sudo mkdir -p /var/lib/docker/snapshots \
        && sudo mkdir -p /var/lib/docker/received \
        && sudo mount -o loop,subvol=volumes /var/lib/docker/btrfs.img /var/lib/buttervolume/volumes \
        && sudo mount -o loop,subvol=snapshots /var/lib/docker/btrfs.img /var/lib/buttervolume/snapshots \
        && sudo mount -o loop,subvol=received /var/lib/docker/btrfs.img /var/lib/buttervolume/received \
        && sudo systemctl start docker

* once you are done with your test when you can umount those volume and you will
  find back your previous docker volumes::


    $ sudo systemctl stop docker \
        && sudo umount /var/lib/buttervolume/volumes \
        && sudo umount /var/lib/docker/snapshots \
        && sudo umount /var/lib/docker/received \
        && sudo systemctl start docker \
        && sudo rm /var/lib/docker/btrfs.img


Migrate from version 1.x to version 2.x
***************************************

If you used version 1, the ``volumes`` and ``snapshots`` folders were located in
``/var/lib/docker/``. They have been moved to ``/var/lib/buttervolume`` by default in
version 2, but it is now configurable.

You have two options :

    * **Option 1**: you keep everything at the same place but you should add a
      ``/etc/buttervolume/config.ini`` file in the buttervolume container with the
      following contents::

        [DEFAULT]
        VOLUMES_PATH = /var/lib/docker/volumes
        SNAPSHOTS_PATH = /var/lib/docker/snapshots

      This is actually not the recommended option because of `issue 16 <https://github.com/anybox/buttervolume/issues/16>`_

    * **Option 2** (recommended): you stop everything and you move the two folders ``/var/lib/docker/volumes`` and ``/var/lib/docker/snapshots`` into ``/var/lib/buttervolume``.

            * Stop docker (systemctl stop docker)
            * Make a backup of your ``/etc/buttervolume/schedule.csv`` from the buttervolume config volume
            * Depending on your setup, move ``/var/lib/docker/snapshots`` and
              ``/var/lib/docker/volumes`` into ``/var/lib/buttervolume/``. WARNING: take care
              of separating ``btrfs`` volumes, which should be in ``/var/lib/buttervolume/``
              and ``local`` volumes which should be in ``/var/lib/docker/volumes``
            * Restart docker, delete, rebuild and restart the buttervolume container
            * Restart all other services


Credits
*******

- Christophe Combelles
- Pierre Verkest

