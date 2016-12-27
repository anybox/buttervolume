import os
import logging
import json
from os.path import join, basename
from subprocess import check_call
from bottle import request, route, app
from waitress import serve
logging.basicConfig()
logger = logging.getLogger()

# absolute path to the volumes
VOLUMES_PATH = "/var/lib/docker/volumes/"
app = app()


def check_btrfs(path):
    check_call("btrfs filesystem label \"%s\"" % path, shell=True)


@route('/Plugin.Activate', ['POST'])
def plugin_activate():
    return json.dumps({'Implements': ['VolumeDriver']})


@route('/VolumeDriver.Create', ['POST'])
def volume_create():
    name = json.loads(request.body.read())['Name']
    volpath = join(VOLUMES_PATH, name)
    # volume already exists?
    if name in [v['Name']for v in json.loads(volume_list())['Volumes']]:
        return json.dumps({'Err': ''})
    try:
        check_call("btrfs subvolume create '%s'" % volpath, shell=True)
    except Exception as e:
        return {'Err': e.strerror}
    return json.dumps({'Err': ''})


@route('/VolumeDriver.Mount', ['POST'])
def volume_mount():
    return volume_path()


@route('/VolumeDriver.Path', ['POST'])
def volume_path():
    name = json.loads(request.body.read())['Name']
    path = join(VOLUMES_PATH, name)
    try:
        check_call("btrfs subvolume show '%s'" % path, shell=True)
    except Exception as e:
        return json.dumps({'Err': '%s: no such volume' % path})
    return json.dumps({'Mountpoint': path, 'Err': ''})


@route('/VolumeDriver.Unmount', ['POST'])
def volume_unmount():
    return json.dumps({'Err': ''})


@route('/VolumeDriver.Get', ['POST'])
def volume_get():
    return volume_path()


@route('/VolumeDriver.Remove', ['POST'])
def volume_remove():
    name = json.loads(request.body.read())['Name']
    path = join(VOLUMES_PATH, name)
    try:
        check_call("btrfs subvolume delete '%s'" % path, shell=True)
    except Exception as e:
        return json.dumps({'Err': '%s: no such volume' % name})
    return json.dumps({'Err': ''})


@route('/VolumeDriver.List', ['POST'])
def volume_list():
    volumes = []
    for p in [join(VOLUMES_PATH, v) for v in os.listdir(VOLUMES_PATH)]:
        try:
            check_call("btrfs subvolume show '%s'" % p, shell=True)
        except Exception as e:
            logger.info(e)
            continue
        volumes.append(p)
    return json.dumps({'Volumes': [{'Name': basename(v)} for v in volumes],
                       'Err': ''})


def main():
    serve(app, unix_socket='/run/docker/plugins/btrfs.sock')
