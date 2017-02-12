import os
import sys
import logging
import json
from os.path import join, basename, exists
from subprocess import check_call
from bottle import request, route, app
from waitress import serve
from subprocess import run
from datetime import datetime
logging.basicConfig()
logger = logging.getLogger()

# absolute path to the volumes
VOLUMES_PATH = "/var/lib/docker/volumes/"
SNAPSHOTS_PATH = "/var/lib/docker/snapshots/"
CODE = sys.getfilesystemencoding()
app = app()


def jsonloads(x):
    return json.loads(bytes.decode(x, CODE))


def check_btrfs(path):
    check_call("btrfs filesystem label '{}'".format(path), shell=True)


@route('/Plugin.Activate', ['POST'])
def plugin_activate():
    return json.dumps({'Implements': ['VolumeDriver']})


@route('/VolumeDriver.Create', ['POST'])
def volume_create():
    name = jsonloads(request.body.read())['Name']
    volpath = join(VOLUMES_PATH, name)
    # volume already exists?
    if name in [v['Name']for v in json.loads(volume_list())['Volumes']]:
        return json.dumps({'Err': ''})
    try:
        check_call("btrfs subvolume create '{}'".format(volpath), shell=True)
    except Exception as e:
        return {'Err': e.strerror}
    return json.dumps({'Err': ''})


@route('/VolumeDriver.Mount', ['POST'])
def volume_mount():
    name = jsonloads(request.body.read())['Name']
    path = join(VOLUMES_PATH, name)
    if exists(join(path, '_data', '.nocow')) or exists(join(path, '.nocow')):
        try:
            check_call("chattr +C '{}'".format(join(path)), shell=True)
            logger.info("disabled COW on {}".format(path))
        except Exception as e:
            return json.dumps(
                {'Err': 'could not disable COW on {}'.format(path)})
    if exists(join(path, '_data', '.nocow')):
        os.remove(join(path, '_data', '.nocow'))
    if exists(join(path, '.nocow')):
        os.remove(join(path, '.nocow'))
    return volume_path()


@route('/VolumeDriver.Path', ['POST'])
def volume_path():
    name = jsonloads(request.body.read())['Name']
    path = join(VOLUMES_PATH, name)
    try:
        check_call("btrfs subvolume show '{}'".format(path), shell=True)
    except Exception as e:
        return json.dumps({'Err': '{}: no such volume'.format(path)})
    return json.dumps({'Mountpoint': path, 'Err': ''})


@route('/VolumeDriver.Unmount', ['POST'])
def volume_unmount():
    return json.dumps({'Err': ''})


@route('/VolumeDriver.Get', ['POST'])
def volume_get():
    name = jsonloads(request.body.read())['Name']
    path = join(VOLUMES_PATH, name)
    try:
        check_call("btrfs subvolume show '{}'".format(path), shell=True)
    except Exception as e:
        return json.dumps({'Err': '{}: no such volume'.format(path)})
    return json.dumps(
        {'Volume': {'Name': name, 'Mountpoint': path}, 'Err': ''})


@route('/VolumeDriver.Remove', ['POST'])
def volume_remove():
    name = jsonloads(request.body.read())['Name']
    path = join(VOLUMES_PATH, name)
    try:
        check_call("btrfs subvolume delete '{}'".format(path), shell=True)
    except Exception as e:
        return json.dumps({'Err': '{}: no such volume'.format(name)})
    return json.dumps({'Err': ''})


@route('/VolumeDriver.List', ['POST'])
def volume_list():
    volumes = []
    for p in [join(VOLUMES_PATH, v) for v in os.listdir(VOLUMES_PATH)]:
        try:
            check_call("btrfs subvolume show '{}'".format(p), shell=True)
        except Exception as e:
            logger.info(e)
            continue
        volumes.append(p)
    return json.dumps({'Volumes': [{'Name': basename(v)} for v in volumes],
                       'Err': ''})


@route('/VolumeDriver.Send', ['POST'])
def volume_send():
    volume_name = jsonloads(request.body.read())['Name']
    volume_path = join(VOLUMES_PATH, volume_name)
    snapshot_path = join(SNAPSHOTS_PATH, volume_name)
    host = jsonloads(request.body.read())['Host']
    remote_snapshots = jsonloads(request.body.read()
                                 ).get('RemotePath', SNAPSHOTS_PATH)
    timestamp = datetime.now().isoformat()
    stamped_snapshot = '{}-{}'.format(volume_name, timestamp)
    run('btrfs subvolume snapshot -r "{volume_path}" "{snapshot_path}"'
        .format(**locals()), shell=True, check=True)
    run('btrfs send "{snapshot_path}"'
        ' | ssh \'{host}\' "btrfs receive \'{remote_snapshots}\''
        '   && mv \'{remote_snapshots}/{volume_name}\''
        '         \'{remote_snapshots}/{stamped_snapshot}\'"'
        .format(**locals()), shell=True, check=True)
    os.rename(snapshot_path, join(SNAPSHOTS_PATH, stamped_snapshot))
    return json.dumps({'Err': '', 'Snapshot': stamped_snapshot})


def main():
    serve(app, unix_socket='/run/docker/plugins/btrfs.sock')
