import json
import os
import unittest
import uuid
import tempfile
from buttervolume import btrfs, cli
from buttervolume import plugin
from buttervolume.cli import scheduler
from buttervolume.plugin import VOLUMES_PATH, SNAPSHOTS_PATH, jsonloads
from datetime import datetime, timedelta
from os.path import join
from subprocess import check_output
from webtest import TestApp

# check that the target dir is btrfs
SCHEDULE = plugin.SCHEDULE = tempfile.mkstemp()[1]
SCHEDULE_LOG = plugin.SCHEDULE_LOG


class TestCase(unittest.TestCase):

    def setUp(self):
        self.app = TestApp(cli.app)
        # check we have a btrfs
        btrfs.Filesystem(VOLUMES_PATH).label()

    def test(self):
        """first basic scenario
        """
        # list
        resp = jsonloads(self.app.post('/VolumeDriver.List', '{}').body)
        self.assertEqual(resp, {'Volumes': [], 'Err': ''})

        # create a volume
        name = 'buttervolume-test-' + uuid.uuid4().hex
        path = join(VOLUMES_PATH, name)
        resp = jsonloads(self.app.post('/VolumeDriver.Create',
                                       json.dumps({'Name': name})).body)
        self.assertEqual(resp, {'Err': ''})

        # get
        resp = jsonloads(self.app.post('/VolumeDriver.Get',
                                       json.dumps({'Name': name})).body)
        self.assertEqual(resp['Volume']['Name'], name)
        self.assertEqual(resp['Volume']['Mountpoint'], path)
        self.assertEqual(resp['Err'], '')

        # create the same volume
        resp = jsonloads(self.app.post('/VolumeDriver.Create',
                                       json.dumps({'Name': name})).body)
        self.assertEqual(resp, {'Err': ''})

        # list
        resp = jsonloads(self.app.post('/VolumeDriver.List').body)
        self.assertEqual(resp['Volumes'], [{u'Name': name}])

        # mount
        resp = jsonloads(self.app.post('/VolumeDriver.Mount',
                                       json.dumps({'Name': name})).body)
        self.assertEqual(resp['Mountpoint'], join(VOLUMES_PATH, name))
        resp = jsonloads(self.app.post('/VolumeDriver.Mount',
                                       json.dumps({'Name': name})).body)
        self.assertEqual(resp['Mountpoint'], join(VOLUMES_PATH, name))
        # not existing path
        name2 = 'buttervolume-test-' + uuid.uuid4().hex
        resp = jsonloads(self.app.post(
            '/VolumeDriver.Mount',
            json.dumps({'Name': name2})).body)
        self.assertTrue(resp['Err'].endswith('no such volume'))

        # path
        resp = jsonloads(self.app.post(
            '/VolumeDriver.Path',
            json.dumps({'Name': name})).body)
        self.assertEqual(resp['Mountpoint'], join(VOLUMES_PATH, name))
        # not existing path
        resp = jsonloads(self.app.post(
            '/VolumeDriver.Path',
            json.dumps({
                'Name': 'buttervolume-test-' + uuid.uuid4().hex})).body)
        self.assertTrue(resp['Err'].endswith('no such volume'))

        # unmount
        resp = jsonloads(self.app.post(
            '/VolumeDriver.Unmount',
            json.dumps({'Name': name})).body)
        self.assertEqual(resp, {'Err': ''})
        resp = jsonloads(self.app.post(
            '/VolumeDriver.Unmount',
            json.dumps({
                'Name': 'buttervolume-test-' + uuid.uuid4().hex})).body)
        self.assertEqual(resp, {'Err': ''})

        # remove
        resp = jsonloads(self.app.post(
            '/VolumeDriver.Remove',
            json.dumps({'Name': name})).body)
        self.assertEqual(resp, {'Err': ''})
        # remove again
        resp = jsonloads(self.app.post(
            '/VolumeDriver.Remove',
            json.dumps({'Name': name})).body)
        self.assertTrue(resp['Err'].endswith("no such volume"))

        # get
        resp = jsonloads(self.app.post('/VolumeDriver.Get',
                                       json.dumps({'Name': name})).body)
        self.assertTrue(resp['Err'].endswith("no such volume"))

        # list
        resp = jsonloads(self.app.post('/VolumeDriver.List',
                                       '{}').body)
        self.assertEqual(resp['Volumes'], [])

    def test_disable_cow(self):
        """Putting a .nocow file in the volume creation should disable cow
        """
        # create a volume
        name = 'buttervolume-test-' + uuid.uuid4().hex
        path = join(VOLUMES_PATH, name)
        self.app.post('/VolumeDriver.Create', json.dumps({'Name': name}))

        # put the nocow command
        os.system('touch {}'.format(join(path, '_data', '.nocow')))
        os.system('touch {}'.format(join(path, '.nocow')))

        # mount
        self.app.post('/VolumeDriver.Mount', json.dumps({'Name': name}))
        # check the nocow
        self.assertTrue(b'-C-' in check_output(
                "lsattr -d '{}'".format(path), shell=True).split()[0])
        self.app.post('/VolumeDriver.Remove', json.dumps({'Name': name}))

    def test_send(self):
        """We can send a snapshot incrementally to another host
        """
        # create a volume with a file
        name = 'buttervolume-test-' + uuid.uuid4().hex
        path = join(VOLUMES_PATH, name)
        self.app.post('/VolumeDriver.Create', json.dumps({'Name': name}))
        with open(join(path, 'foobar'), 'w') as f:
            f.write('foobar')
        # snapshot
        resp = self.app.post('/VolumeDriver.Snapshot',
                             json.dumps({'Name': name}))
        snapshot = json.loads(resp.body.decode())['Snapshot']
        snapshot_path = join(SNAPSHOTS_PATH, snapshot)
        # send the snapshot (to the same host with another name)
        self.app.post('/VolumeDriver.Snapshot.Send', json.dumps({
            'Name': snapshot,
            'Host': 'localhost',
            'Test': True,
            'RemotePath': '/var/lib/docker/received'}))
        remote_path = join('/var/lib/docker/received', snapshot)
        # check the volumes have the same content
        with open(join(snapshot_path, 'foobar')) as x:
            with open(join(remote_path, 'foobar')) as y:
                self.assertEqual(x.read(), y.read())
        # change files in the master volume
        with open(join(path, 'foobar'), 'w') as f:
            f.write('changed foobar')
        # send again to the other volume
        resp = self.app.post('/VolumeDriver.Snapshot',
                             json.dumps({'Name': name}))
        snapshot2 = json.loads(resp.body.decode())['Snapshot']
        snapshot2_path = join(SNAPSHOTS_PATH, snapshot2)
        self.app.post('/VolumeDriver.Snapshot.Send', json.dumps({
            'Name': snapshot2,
            'Host': 'localhost',
            'Test': True,
            'RemotePath': '/var/lib/docker/received'}))
        remote_path2 = join('/var/lib/docker/received', snapshot2)
        # check the files are the same
        with open(join(snapshot2_path, 'foobar')) as x:
            with open(join(remote_path2, 'foobar')) as y:
                self.assertEqual(x.read(), y.read())
        # check the second snapshot is a child of the first one
        self.assertEqual(btrfs.Subvolume(remote_path).show()['UUID'],
                         btrfs.Subvolume(remote_path2).show()['Parent UUID'])
        # clean up
        self.app.post('/VolumeDriver.Remove', json.dumps({'Name': name}))
        btrfs.Subvolume(join('/var/lib/docker/snapshots',
                             snapshot + '@localhost')).delete()
        btrfs.Subvolume(join('/var/lib/docker/snapshots',
                             snapshot2 + '@localhost')).delete()
        btrfs.Subvolume(join('/var/lib/docker/snapshots', snapshot)).delete()
        btrfs.Subvolume(join('/var/lib/docker/snapshots', snapshot2)).delete()
        btrfs.Subvolume(join('/var/lib/docker/received', snapshot)).delete()
        btrfs.Subvolume(join('/var/lib/docker/received', snapshot2)).delete()

    def test_snapshot(self):
        """Check we can snapshot a volume
        """
        # create a volume with a file
        name = 'buttervolume-test-' + uuid.uuid4().hex
        path = join(VOLUMES_PATH, name)
        self.app.post('/VolumeDriver.Create', json.dumps({'Name': name}))
        with open(join(path, 'foobar'), 'w') as f:
            f.write('foobar')
        # snapshot the volume
        resp = self.app.post('/VolumeDriver.Snapshot',
                             json.dumps({'Name': name}))
        snapshot = join(SNAPSHOTS_PATH,
                        json.loads(resp.body.decode())['Snapshot'])
        # check the snapshot has the same content
        with open(join(path, 'foobar')) as x:
            with open(join(snapshot, 'foobar')) as y:
                self.assertEqual(x.read(), y.read())
        # clean up
        self.app.post('/VolumeDriver.Remove', json.dumps({'Name': name}))
        self.app.post('/VolumeDriver.Snapshot.Remove',
                      json.dumps({'Name': snapshot}))

    def test_snapshots(self):
        """Check we can list snapshots
        """
        # create two volumes with a file
        name = 'buttervolume-test-' + uuid.uuid4().hex
        path = join(VOLUMES_PATH, name)
        name2 = 'buttervolume-test-' + uuid.uuid4().hex
        path2 = join(VOLUMES_PATH, name2)
        self.app.post('/VolumeDriver.Create', json.dumps({'Name': name}))
        self.app.post('/VolumeDriver.Create', json.dumps({'Name': name2}))
        with open(join(path, 'foobar'), 'w') as f:
            f.write('foobar')
        with open(join(path2, 'foobar2'), 'w') as f:
            f.write('foobar2')
        # snapshot each volume twice
        resp = self.app.post('/VolumeDriver.Snapshot',
                             json.dumps({'Name': name}))
        snap1 = json.loads(resp.body.decode())['Snapshot']
        resp = self.app.post('/VolumeDriver.Snapshot',
                             json.dumps({'Name': name}))
        snap2 = json.loads(resp.body.decode())['Snapshot']
        resp = self.app.post('/VolumeDriver.Snapshot',
                             json.dumps({'Name': name2}))
        snap3 = json.loads(resp.body.decode())['Snapshot']
        resp = self.app.post('/VolumeDriver.Snapshot',
                             json.dumps({'Name': name2}))
        snap4 = json.loads(resp.body.decode())['Snapshot']
        # list all the snapshots
        resp = self.app.post('/VolumeDriver.Snapshot.List', json.dumps({}))
        snapshots = json.loads(resp.body.decode())['Snapshots']
        # check the list of snapshots
        self.assertEqual(set(snapshots), set([snap1, snap2, snap3, snap4]))
        # list all the snapshots of the second volume only
        resp = self.app.post('/VolumeDriver.Snapshot.List',
                             json.dumps({'Name': name2}))
        snapshots = json.loads(resp.body.decode())['Snapshots']
        # check the list of snapshots
        self.assertEqual(set(snapshots), set([snap3, snap4]))
        # clean up
        self.app.post('/VolumeDriver.Remove', json.dumps({'Name': name}))
        self.app.post('/VolumeDriver.Remove', json.dumps({'Name': name2}))
        self.app.post('/VolumeDriver.Snapshot.Remove',
                      json.dumps({'Name': snap1}))
        self.app.post('/VolumeDriver.Snapshot.Remove',
                      json.dumps({'Name': snap2}))
        self.app.post('/VolumeDriver.Snapshot.Remove',
                      json.dumps({'Name': snap3}))
        self.app.post('/VolumeDriver.Snapshot.Remove',
                      json.dumps({'Name': snap4}))

    def test_schedule(self):
        """check we can schedule actions such as snapshots
        """
        # create a volume with a file
        name = 'buttervolume-test-' + uuid.uuid4().hex
        name2 = 'buttervolume-test-' + uuid.uuid4().hex
        path = join(VOLUMES_PATH, name)
        path2 = join(VOLUMES_PATH, name2)
        self.app.post('/VolumeDriver.Create', json.dumps({'Name': name}))
        self.app.post('/VolumeDriver.Create', json.dumps({'Name': name2}))
        with open(join(path, 'foobar'), 'w') as f:
            f.write('foobar')
        with open(join(path2, 'foobar'), 'w') as f:
            f.write('foobar')
        # check we have no schedule
        resp = self.app.get('/VolumeDriver.Schedule.List')
        schedule = json.loads(resp.body.decode())['Schedule']
        self.assertEqual(len(schedule), 0)
        # schedule a snapshot of the two volumes every 60 minutes
        self.app.post('/VolumeDriver.Schedule', json.dumps(
            {'Name': name, 'Action': 'snapshot', 'Timer': 60}))
        self.app.post('/VolumeDriver.Schedule', json.dumps(
            {'Name': name2, 'Action': 'snapshot', 'Timer': 60}))
        # check we have 2 scheduled jobs
        resp = self.app.get('/VolumeDriver.Schedule.List')
        schedule = json.loads(resp.body.decode())['Schedule']
        self.assertEqual(len(schedule), 2)
        self.assertEqual(schedule[0]['Action'], 'snapshot')
        self.assertEqual(schedule[1]['Timer'], '60')
        # check that the schedule is stored
        with open(SCHEDULE) as f:
            lines = f.readlines()
            self.assertEqual(lines[1], '{},snapshot,60\n'.format(name))
        # run the scheduler
        scheduler(SCHEDULE, test=True)
        # check we have two snapshots
        snaps = os.listdir(SNAPSHOTS_PATH)
        self.assertEqual(
            2, len({s for s in snaps
                    if s.startswith(name) or s.startswith(name2)}))
        # unschedule
        self.app.post('/VolumeDriver.Schedule', json.dumps(
            {'Name': name, 'Action': 'snapshot', 'Timer': 0}))
        with open(SCHEDULE) as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 1)
        # check we have 1 scheduled job
        resp = self.app.get('/VolumeDriver.Schedule.List')
        schedule = json.loads(resp.body.decode())['Schedule']
        self.assertEqual(len(schedule), 1)
        # simulate we spent more time
        SCHEDULE_LOG['snapshot'][name2] = datetime.now() - timedelta(1)
        # run the scheduler and check we only have one more snapshot
        scheduler(SCHEDULE, test=True)
        snaps = os.listdir(SNAPSHOTS_PATH)
        self.assertEqual(
            3, len({s for s in snaps
                    if s.startswith(name) or s.startswith(name2)}))
        # unschedule the last job
        self.app.post('/VolumeDriver.Schedule', json.dumps(
            {'Name': name2, 'Action': 'snapshot', 'Timer': 0}))
        resp = self.app.get('/VolumeDriver.Schedule.List')
        schedule = json.loads(resp.body.decode())['Schedule']
        self.assertEqual(len(schedule), 0)
        # unschedule
        self.app.post('/VolumeDriver.Schedule', json.dumps(
            {'Name': name, 'Action': 'snapshot', 'Timer': 0}))
        # clean up
        for snap in os.listdir(SNAPSHOTS_PATH):
            if snap.startswith(name) or snap.startswith(name2):
                self.app.post('/VolumeDriver.Snapshot.Remove',
                              json.dumps({'Name': snap}))
        self.app.post('/VolumeDriver.Remove', json.dumps({'Name': name}))
        self.app.post('/VolumeDriver.Remove', json.dumps({'Name': name2}))

    def test_restore(self):
        """ Check we can restore a snapshot as a volume
        """
        # create a volume with a file
        name = 'buttervolume-test-' + uuid.uuid4().hex
        path = join(VOLUMES_PATH, name)
        self.app.post('/VolumeDriver.Create', json.dumps({'Name': name}))
        with open(join(path, 'foobar'), 'w') as f:
            f.write('original foobar')
        # snapshot the volume
        resp = self.app.post('/VolumeDriver.Snapshot',
                             json.dumps({'Name': name}))
        snapshot = json.loads(resp.body.decode())['Snapshot']
        # modify the file
        with open(join(path, 'foobar'), 'w') as f:
            f.write('modified foobar')
        # overwrite the volume with the snapshot
        resp = self.app.post('/VolumeDriver.Snapshot.Restore',
                             json.dumps({'Name': snapshot}))
        # check the volume has the original content
        with open(join(path, 'foobar')) as f:
            self.assertEqual(f.read(), 'original foobar')
        # check we have another snapshot with the volume backup
        volume_backup = json.loads(resp.body.decode())['VolumeBackup']
        path = join(SNAPSHOTS_PATH, volume_backup)
        with open(join(path, 'foobar')) as f:
            self.assertEqual(f.read(), 'modified foobar')
        # delete the volume and check we still can restore
        self.app.post('/VolumeDriver.Remove', json.dumps({'Name': name}))
        resp = self.app.post('/VolumeDriver.Snapshot.Restore',
                             json.dumps({'Name': snapshot}))
        path = join(VOLUMES_PATH, name)
        with open(join(path, 'foobar')) as f:
            self.assertEqual(f.read(), 'original foobar')
        self.app.post('/VolumeDriver.Remove', json.dumps({'Name': name}))
        btrfs.Subvolume(join(SNAPSHOTS_PATH, snapshot)).delete()
        btrfs.Subvolume(join(SNAPSHOTS_PATH, volume_backup)).delete()


if __name__ == '__main__':
    unittest.main()
