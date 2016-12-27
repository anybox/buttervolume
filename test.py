from buttervolume import plugin
from os.path import join
import json
import unittest
import uuid
from webtest import TestApp

# check that the target dir is btrfs
path = plugin.VOLUMES_PATH


class TestCase(unittest.TestCase):

    def setUp(self):
        self.app = TestApp(plugin.app)
        plugin.check_btrfs(path)

    def test(self):
        # list
        resp = json.loads(self.app.post('/VolumeDriver.List', '{}').body)
        self.assertEquals(resp, {'Volumes': [], 'Err': ''})

        # create a volume
        name = uuid.uuid4().hex
        path = join(plugin.VOLUMES_PATH, name)
        resp = json.loads(self.app.post('/VolumeDriver.Create',
                                        json.dumps({'Name': name})).body)
        self.assertEquals(resp, {'Err': ''})

        # get
        resp = json.loads(self.app.post('/VolumeDriver.Get',
                                        json.dumps({'Name': name})).body)
        self.assertEquals(resp['Volume']['Name'], name)
        self.assertEquals(resp['Volume']['Mountpoint'], path)
        self.assertEquals(resp['Err'], '')
        
        # create the same volume
        resp = json.loads(self.app.post('/VolumeDriver.Create',
                                        json.dumps({'Name': name})).body)
        self.assertEquals(resp, {'Err': ''})

        # list
        resp = json.loads(self.app.post('/VolumeDriver.List').body)
        self.assertEquals(resp['Volumes'], [{u'Name': name}])

        # mount
        resp = json.loads(self.app.post('/VolumeDriver.Mount',
                                        json.dumps({'Name': name})).body)
        self.assertEquals(resp['Mountpoint'], join(plugin.VOLUMES_PATH, name))
        resp = json.loads(self.app.post('/VolumeDriver.Mount',
                                        json.dumps({'Name': name})).body)
        self.assertEquals(resp['Mountpoint'], join(plugin.VOLUMES_PATH, name))
        # not existing path
        name2 = uuid.uuid4().hex
        resp = json.loads(self.app.post(
            '/VolumeDriver.Mount',
            json.dumps({'Name': name2})).body)
        self.assertTrue(resp['Err'].endswith('no such volume'))

        # path
        resp = json.loads(self.app.post(
            '/VolumeDriver.Path',
            json.dumps({'Name': name})).body)
        self.assertEquals(resp['Mountpoint'], join(plugin.VOLUMES_PATH, name))
        # not existing path
        resp = json.loads(self.app.post(
            '/VolumeDriver.Path',
            json.dumps({'Name': uuid.uuid4().hex})).body)
        self.assertTrue(resp['Err'].endswith('no such volume'))

        # unmount
        resp = json.loads(self.app.post(
            '/VolumeDriver.Unmount',
            json.dumps({'Name': name})).body)
        self.assertEquals(resp, {'Err': ''})
        resp = json.loads(self.app.post(
            '/VolumeDriver.Unmount',
            json.dumps({'Name': uuid.uuid4().hex})).body)
        self.assertEquals(resp, {'Err': ''})

        # remove
        resp = json.loads(self.app.post(
            '/VolumeDriver.Remove',
            json.dumps({'Name': name})).body)
        self.assertEquals(resp, {'Err': ''})
        # remove again
        resp = json.loads(self.app.post(
            '/VolumeDriver.Remove',
            json.dumps({'Name': name})).body)
        self.assertTrue(resp['Err'].endswith("no such volume"))

        # get
        resp = json.loads(self.app.post('/VolumeDriver.Get',
                                        json.dumps({'Name': name})).body)
        self.assertTrue(resp['Err'].endswith("no such volume"))

        # list
        resp = json.loads(self.app.post('/VolumeDriver.List',
                                        '{}').body)
        self.assertEquals(resp['Volumes'], [])


if __name__ == '__main__':
    unittest.main()
