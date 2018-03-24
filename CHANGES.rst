CHANGELOG
=========

2.0 (2018-03-24)
****************

- BREAKING CHANGE: Please read the migration path from version 1 to version 2:
    BTRFS volumes and snapshots are now stored by default in different directories under ``/var/lib/buttervolume``
- Configuration possible through environment variables or a ``config.ini`` file
- implemented ``VolumeDriver.Capabilities`` and just return ``'local'``
- other minor fixes and improvements

1.4 (2018-02-01)
****************

- Add clone command
- replace sync by `btrfs filesystem sync`

1.3.1 (2017-10-22)
******************

- fixed packaging (missing README)

1.3 (2017-07-30)
****************

- fixed the cli for the restore command

1.2 (2017-07-16)
****************

- fixed the purge algorithm

1.1 (2017-07-13)
****************

- allow to restore a snapshot to a different volume name

1.0 (2017-05-24)
****************

- initial release, used in production

