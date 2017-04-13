import json
import os
import unittest
import uuid
import tempfile
from buttervolume import btrfs, cli
from buttervolume import plugin
from buttervolume.cli import scheduler
from buttervolume.plugin import VOLUMES_PATH, SNAPSHOTS_PATH, TEST_RECEIVE_PATH
from buttervolume.plugin import jsonloads
from datetime import datetime, timedelta
from os.path import join
from subprocess import check_output, run
from webtest import TestApp

# check that the target dir is btrfs
SCHEDULE = plugin.SCHEDULE = tempfile.mkstemp()[1]
SCHEDULE_LOG = plugin.SCHEDULE_LOG
PREFIX_TEST_VOLUME = 'buttervolume-test-'


class TestCase(unittest.TestCase):

    def cleanup(self):
        # clean-up test volumes and snapshots before each test
        btrfs.Subvolume(
            join(VOLUMES_PATH, PREFIX_TEST_VOLUME) + '*').delete(check=False)
        btrfs.Subvolume(
            join(SNAPSHOTS_PATH, PREFIX_TEST_VOLUME) + '*').delete(check=False)
        btrfs.Subvolume(
            join(TEST_RECEIVE_PATH, PREFIX_TEST_VOLUME) + '*'
        ).delete(check=False)

    def setUp(self):
        self.app = TestApp(cli.app)
        # check we have a btrfs
        btrfs.Filesystem(VOLUMES_PATH).label()
        self.cleanup()

    def test(self):
        """first basic scenario
        """
        # list
        resp = jsonloads(self.app.post('/VolumeDriver.List', '{}').body)
        self.assertEqual(resp, {'Volumes': [], 'Err': ''})

        # create a volume
        name = PREFIX_TEST_VOLUME + uuid.uuid4().hex
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
        name2 = PREFIX_TEST_VOLUME + uuid.uuid4().hex
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
                'Name': PREFIX_TEST_VOLUME + uuid.uuid4().hex})).body)
        self.assertTrue(resp['Err'].endswith('no such volume'))

        # unmount
        resp = jsonloads(self.app.post(
            '/VolumeDriver.Unmount',
            json.dumps({'Name': name})).body)
        self.assertEqual(resp, {'Err': ''})
        resp = jsonloads(self.app.post(
            '/VolumeDriver.Unmount',
            json.dumps({
                'Name': PREFIX_TEST_VOLUME + uuid.uuid4().hex})).body)
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
        name = PREFIX_TEST_VOLUME + uuid.uuid4().hex
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
        name = PREFIX_TEST_VOLUME + uuid.uuid4().hex
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
            'Test': True}))
        remote_path = join(TEST_RECEIVE_PATH, snapshot)
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
            'Test': True}))
        remote_path2 = join(TEST_RECEIVE_PATH, snapshot2)
        # check the files are the same
        with open(join(snapshot2_path, 'foobar')) as x:
            with open(join(remote_path2, 'foobar')) as y:
                self.assertEqual(x.read(), y.read())
        # check the second snapshot is a child of the first one
        self.assertEqual(btrfs.Subvolume(remote_path).show()['UUID'],
                         btrfs.Subvolume(remote_path2).show()['Parent UUID'])

    def test_snapshot(self):
        """Check we can snapshot a volume
        """
        # create a volume with a file
        name = PREFIX_TEST_VOLUME + uuid.uuid4().hex
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

    def test_snapshots(self):
        """Check we can list snapshots
        """
        # create two volumes with a file
        name = PREFIX_TEST_VOLUME + uuid.uuid4().hex
        path = join(VOLUMES_PATH, name)
        name2 = PREFIX_TEST_VOLUME + uuid.uuid4().hex
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

    def test_schedule_snapshot(self):
        """check we can schedule actions such as snapshots
        """
        # create a volume with a file
        name = PREFIX_TEST_VOLUME + uuid.uuid4().hex
        name2 = PREFIX_TEST_VOLUME + uuid.uuid4().hex
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
        self.assertEqual(
            2, len({s for s in os.listdir(SNAPSHOTS_PATH)
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
        self.assertEqual(
            3, len({s for s in os.listdir(SNAPSHOTS_PATH)
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

    def test_schedule_replicate(self):
        # create a volume with a file
        name = PREFIX_TEST_VOLUME + uuid.uuid4().hex
        path = join(VOLUMES_PATH, name)
        self.app.post('/VolumeDriver.Create', json.dumps({'Name': name}))
        with open(join(path, 'foobar'), 'w') as f:
            f.write('foobar')
        # check we have no schedule
        resp = self.app.get('/VolumeDriver.Schedule.List')
        schedule = json.loads(resp.body.decode())['Schedule']
        self.assertEqual(len(schedule), 0)
        # check we have no snapshots
        resp = self.app.post('/VolumeDriver.Snapshot.List', json.dumps({}))
        snapshots = json.loads(resp.body.decode())['Snapshots']
        self.assertEqual(len(snapshots), 0)
        # replicate the volume every 120 minutes
        self.app.post('/VolumeDriver.Schedule', json.dumps(
            {'Name': name, 'Action': 'replicate:localhost', 'Timer': 120}))
        # also replicate a non existing volume
        self.app.post('/VolumeDriver.Schedule', json.dumps(
            {'Name': 'boo', 'Action': 'replicate:localhost', 'Timer': 120}))
        # simulate we spent more time
        SCHEDULE_LOG.setdefault('replicate:localhost', {})
        SCHEDULE_LOG['replicate:localhost'
                     ][name] = datetime.now() - timedelta(1)
        # run the scheduler and check we only have two more snapshots
        scheduler(SCHEDULE, test=True)
        self.assertEqual(
            2, len({s for s in os.listdir(SNAPSHOTS_PATH)
                    if s.startswith(name) or s.startswith(name)}))
        self.assertEqual(
            1, len({s for s in os.listdir(TEST_RECEIVE_PATH)
                    if s.startswith(name) or s.startswith(name)}))
        # unschedule the last job
        self.app.post('/VolumeDriver.Schedule', json.dumps(
            {'Name': 'boo', 'Action': 'replicate:localhost', 'Timer': 0}))
        self.app.post('/VolumeDriver.Schedule', json.dumps(
            {'Name': name, 'Action': 'replicate:localhost', 'Timer': 0}))
        self.app.post('/VolumeDriver.Remove', json.dumps({'Name': name}))

    def test_restore(self):
        """ Check we can restore a snapshot as a volume
        """
        # create a volume with a file
        name = PREFIX_TEST_VOLUME + uuid.uuid4().hex
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

    def test_purge(self):
        """Check we can purge snapshots with a save pattern
        """
        name = 'buttervolume-test-' + uuid.uuid4().hex
        # first run the purge without snapshots (should do nothing)
        resp = self.app.post('/VolumeDriver.Snapshots.Purge',
                             json.dumps({'Name': name, 'Pattern': '2h:2h'}))
        path = join(VOLUMES_PATH, name)
        self.app.post('/VolumeDriver.Create', json.dumps({'Name': name}))
        with open(join(path, 'foobar'), 'w') as f:
            f.write('original foobar')

        def cleanup_snapshots():
            for s in os.listdir(SNAPSHOTS_PATH):
                if s.startswith('buttervolume-test-'):
                    btrfs.Subvolume(join(SNAPSHOTS_PATH, s)).delete()

        def create_20_hourly_snapshots():
            hours = [(datetime.now() - timedelta(hours=h)).isoformat()
                     for h in range(20)]
            for h in hours:
                run('btrfs subvolume snapshot {} {}@{}'.format(
                    path, join(SNAPSHOTS_PATH, name), h), shell=True)

        create_20_hourly_snapshots()
        # run the purge with a simple save pattern (2h only once)
        nb_snaps = len(os.listdir(SNAPSHOTS_PATH))
        resp = self.app.post('/VolumeDriver.Snapshots.Purge',
                             json.dumps({'Name': name, 'Pattern': '2h:2h'}))
        self.assertEqual(jsonloads(resp.body), {'Err': ''})
        # check we deleted 17 snapshots
        self.assertEqual(len(os.listdir(SNAPSHOTS_PATH)), nb_snaps - 17)
        # run the purge again and check we still have the same nb of snapshots
        nb_snaps = len(os.listdir(SNAPSHOTS_PATH))
        resp = self.app.post('/VolumeDriver.Snapshots.Purge',
                             json.dumps({'Name': name, 'Pattern': '2h:2h'}))
        self.assertEqual(jsonloads(resp.body), {'Err': ''})
        self.assertEqual(len(os.listdir(SNAPSHOTS_PATH)), nb_snaps)

        cleanup_snapshots()
        create_20_hourly_snapshots()
        # run the purge with a more complex save pattern (2h:4h:8h:16h)
        nb_snaps = len(os.listdir(SNAPSHOTS_PATH))
        resp = self.app.post(
            '/VolumeDriver.Snapshots.Purge',
            json.dumps({'Name': name, 'Pattern': '2h:4h:8h:16h'}))
        self.assertEqual(jsonloads(resp.body), {'Err': ''})
        # check we deleted 11 snapshots
        self.assertEqual(len(os.listdir(SNAPSHOTS_PATH)), nb_snaps - 11)

        cleanup_snapshots()
        create_20_hourly_snapshots()
        # check we have an error with a non numeric pattern
        resp = self.app.post(
            '/VolumeDriver.Snapshots.Purge',
            json.dumps({'Name': name, 'Pattern': '60m:plop:3000m'}))
        self.assertEqual(jsonloads(resp.body),
                         {'Err': 'Invalid purge pattern'})
        # run the purge with a more complex unsorted save pattern
        nb_snaps = len(os.listdir(SNAPSHOTS_PATH))
        resp = self.app.post(
            '/VolumeDriver.Snapshots.Purge',
            json.dumps({'Name': name, 'Pattern': '60m:120m:300m:240m:180m'}))
        self.assertEqual(jsonloads(resp.body), {'Err': ''})
        # check we deleted 14 snapshots
        self.assertEqual(len(os.listdir(SNAPSHOTS_PATH)), nb_snaps - 14)
        cleanup_snapshots()
        self.app.post('/VolumeDriver.Remove', json.dumps({'Name': name}))


if __name__ == '__main__':
    unittest.main()
