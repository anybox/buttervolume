from buttervolume import plugin
from os.path import join
from webtest import TestApp
import json
import os
import subprocess
import unittest
import uuid

# check that the target dir is btrfs
path = plugin.VOLUMES_PATH
jsonloads = plugin.jsonloads


class TestCase(unittest.TestCase):

    def setUp(self):
        self.app = TestApp(plugin.app)
        plugin.check_btrfs(path)

    def test(self):
        # list
        resp = jsonloads(self.app.post('/VolumeDriver.List', '{}').body)
        self.assertEquals(resp, {'Volumes': [], 'Err': ''})

        # create a volume
        name = 'buttervolume-test-' + uuid.uuid4().hex
        path = join(plugin.VOLUMES_PATH, name)
        resp = jsonloads(self.app.post('/VolumeDriver.Create',
                                       json.dumps({'Name': name})).body)
        self.assertEquals(resp, {'Err': ''})

        # get
        resp = jsonloads(self.app.post('/VolumeDriver.Get',
                                       json.dumps({'Name': name})).body)
        self.assertEquals(resp['Volume']['Name'], name)
        self.assertEquals(resp['Volume']['Mountpoint'], path)
        self.assertEquals(resp['Err'], '')

        # create the same volume
        resp = jsonloads(self.app.post('/VolumeDriver.Create',
                                       json.dumps({'Name': name})).body)
        self.assertEquals(resp, {'Err': ''})

        # list
        resp = jsonloads(self.app.post('/VolumeDriver.List').body)
        self.assertEquals(resp['Volumes'], [{u'Name': name}])

        # mount
        resp = jsonloads(self.app.post('/VolumeDriver.Mount',
                                       json.dumps({'Name': name})).body)
        self.assertEquals(resp['Mountpoint'], join(plugin.VOLUMES_PATH, name))
        resp = jsonloads(self.app.post('/VolumeDriver.Mount',
                                       json.dumps({'Name': name})).body)
        self.assertEquals(resp['Mountpoint'], join(plugin.VOLUMES_PATH, name))
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
        self.assertEquals(resp['Mountpoint'], join(plugin.VOLUMES_PATH, name))
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
        self.assertEquals(resp, {'Err': ''})
        resp = jsonloads(self.app.post(
            '/VolumeDriver.Unmount',
            json.dumps({
                'Name': 'buttervolume-test-' + uuid.uuid4().hex})).body)
        self.assertEquals(resp, {'Err': ''})

        # remove
        resp = jsonloads(self.app.post(
            '/VolumeDriver.Remove',
            json.dumps({'Name': name})).body)
        self.assertEquals(resp, {'Err': ''})
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
        self.assertEquals(resp['Volumes'], [])

    def test_disable_cow(self):
        # create a volume
        name = 'buttervolume-test-' + uuid.uuid4().hex
        path = join(plugin.VOLUMES_PATH, name)
        self.app.post('/VolumeDriver.Create', json.dumps({'Name': name}))

        # put the nocow command
        os.system('touch {}'.format(join(path, '_data', '.nocow')))
        os.system('touch {}'.format(join(path, '.nocow')))

        # mount
        self.app.post('/VolumeDriver.Mount', json.dumps({'Name': name}))
        # check the nocow
        self.assertTrue(b'-C-' in subprocess.check_output(
                "lsattr -d '{}'".format(path), shell=True).split()[0])
        self.app.post('/VolumeDriver.Remove', json.dumps({'Name': name}))

    def test_send(self):
        # create a volume with a file
        name = 'buttervolume-test-' + uuid.uuid4().hex
        path = join(plugin.VOLUMES_PATH, name)
        self.app.post('/VolumeDriver.Create', json.dumps({'Name': name}))
        with open(join(path, 'foobar'), 'w') as f:
            f.write('foobar')
        # send the volume (to the same host with another name)
        resp = self.app.post('/VolumeDriver.Send', json.dumps({
            'Name': name,
            'Host': 'localhost',
            'RemotePath': '/var/lib/docker/received'}))
        snapshot = json.loads(resp.body.decode())['Snapshot']
        remote_path = join('/var/lib/docker/received', snapshot)
        # check the volumes have the same content
        self.assertEquals(open(join(path, 'foobar')).read(),
                          open(join(remote_path, 'foobar')).read())
        # change files in the master volume
        with open(join(path, 'foobar'), 'w') as f:
            f.write('changed foobar')
        # send again to the other volume
        resp = self.app.post('/VolumeDriver.Send', json.dumps({
            'Name': name,
            'Host': 'localhost',
            'RemotePath': '/var/lib/docker/received'}))
        snapshot2 = json.loads(resp.body.decode())['Snapshot']
        remote_path2 = join('/var/lib/docker/received', snapshot2)
        # check the files are the same
        self.assertEquals(open(join(path, 'foobar')).read(),
                          open(join(remote_path2, 'foobar')).read())
        self.app.post('/VolumeDriver.Remove', json.dumps({'Name': name}))
        subprocess.run(
            'btrfs subvolume delete "{}"'
            .format(join('/var/lib/docker/snapshots', snapshot)), shell=True)
        subprocess.run(
            'btrfs subvolume delete "{}"'
            .format(join('/var/lib/docker/snapshots', snapshot2)), shell=True)


if __name__ == '__main__':
    unittest.main()
