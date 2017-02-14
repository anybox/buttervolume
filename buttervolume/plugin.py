import argparse
import json
import logging
import os
import requests_unixsocket
import sys
import urllib
from bottle import request, route, app
from buttervolume import btrfs
from datetime import datetime
from os.path import join, basename, exists
from subprocess import check_call
from subprocess import run
from waitress import serve
logging.basicConfig()
logger = logging.getLogger()

# absolute path to the volumes
VOLUMES_PATH = "/var/lib/docker/volumes/"
SNAPSHOTS_PATH = "/var/lib/docker/snapshots/"
CODE = sys.getfilesystemencoding()
SOCKET = '/run/docker/plugins/btrfs.sock'
app = app()


def jsonloads(x):
    return json.loads(bytes.decode(x, CODE))


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
        btrfs.Subvolume(volpath).create()
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
        btrfs.Subvolume(path).show()
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
        btrfs.Subvolume(path).show()
    except Exception as e:
        return json.dumps({'Err': '{}: no such volume'.format(path)})
    return json.dumps(
        {'Volume': {'Name': name, 'Mountpoint': path}, 'Err': ''})


@route('/VolumeDriver.Remove', ['POST'])
def volume_remove():
    name = jsonloads(request.body.read())['Name']
    path = join(VOLUMES_PATH, name)
    try:
        btrfs.Subvolume(path).delete()
    except Exception as e:
        return json.dumps({'Err': '{}: no such volume'.format(name)})
    return json.dumps({'Err': ''})


@route('/VolumeDriver.List', ['POST'])
def volume_list():
    volumes = []
    for p in [join(VOLUMES_PATH, v) for v in os.listdir(VOLUMES_PATH)
              if v != 'metadata.db']:
        try:
            btrfs.Subvolume(p).show()
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
    stamped_snapshot = '{}@{}'.format(volume_name, timestamp)
    btrfs.Subvolume(volume_path).snapshot(snapshot_path, readonly=True)
    # list snapshots. If none, do the 1st snapshot. Otherwise take the latest
    all_snapshots = sorted([s for s in os.listdir(SNAPSHOTS_PATH)
                            if s.startswith(volume_name) and s != volume_name])
    latest = all_snapshots[-1] if all_snapshots else None
    parent = '-p {}'.format(join(SNAPSHOTS_PATH, latest)) if latest else ''
    run('btrfs send {parent} "{snapshot_path}"'
        ' | ssh \'{host}\' "btrfs receive \'{remote_snapshots}\''
        '   && mv \'{remote_snapshots}/{volume_name}\''
        '         \'{remote_snapshots}/{stamped_snapshot}\'"'
        .format(**locals()), shell=True, check=True)
    os.rename(snapshot_path, join(SNAPSHOTS_PATH, stamped_snapshot))
    return json.dumps({'Err': '', 'Snapshot': stamped_snapshot})


@route('/VolumeDriver.Snapshot', ['POST'])
def volume_snapshot():
    """snapshot a volume in the SNAPSHOTS dir
    """
    name = jsonloads(request.body.read())['Name']
    path = join(VOLUMES_PATH, name)
    timestamped = '{}@{}'.format(name, datetime.now().isoformat())
    snapshot_path = join(SNAPSHOTS_PATH, timestamped)
    if not os.path.exists(path):
        return json.dumps({'Err': 'No such volume'})
    try:
        btrfs.Subvolume(path).snapshot(snapshot_path, readonly=True)
    except Exception as e:
        return {'Err': str(e)}
    return json.dumps({'Err': '', 'Snapshot': timestamped})


@route('/VolumeDriver.Snapshot.List', ['POST'])
def snapshot_list():
    name = jsonloads(request.body.read()).get('Name')
    snapshots = os.listdir(SNAPSHOTS_PATH)
    if name:
        snapshots = [s for s in snapshots if s.startswith(name + '@')]
    return json.dumps({'Err': '', 'Snapshots': snapshots})


@route('/VolumeDriver.Snapshot.Destroy', ['POST'])
def snapshot_destroy():
    name = jsonloads(request.body.read())['Name']
    path = join(SNAPSHOTS_PATH, name)
    btrfs.Subvolume(path).delete()


def main():
    parser = argparse.ArgumentParser(
        prog="buttervolume",
        description="Command-line client for the docker btrfs volume plugin",)
    subparsers = parser.add_subparsers(help='sub-commands')
    parser_run = subparsers.add_parser(
        'run', help='Run the plugin in foreground')
    parser_snapshot = subparsers.add_parser(
        'snapshot', help='Snapshot a volume')
    parser_snapshot.add_argument(
        'name', metavar='name', nargs=1, help='Name of the volume to snapshot')
    parser_snapshots = subparsers.add_parser(
        'snapshots', help='List snapshots')
    parser_snapshots.add_argument(
        'name', metavar='name', nargs='?',
        help='Name of the volume to list related snapshots')

    def get_from(resp, key):
        """get specified key from plugin response output
        """
        error = jsonloads(resp.content)['Err']
        if resp.status_code != 200:
            print('Error {}: {}'.format(resp.status_code, resp.reason),
                  file=sys.stderr)
            return None
        elif error:
            print(error, file=sys.stderr)
            return None
        else:
            return jsonloads(resp.content)[key]

    def snapshot(args):
        name = args.name[0]
        resp = requests_unixsocket.Session().post(
            'http+unix://{}/VolumeDriver.Snapshot'
            .format(urllib.parse.quote_plus(SOCKET)),
            json.dumps({'Name': name}))
        return get_from(resp, 'Snapshot') or sys.exit(1)

    def snapshots(args):
        name = args.name
        resp = requests_unixsocket.Session().post(
            'http+unix://{}/VolumeDriver.Snapshot.List'
            .format(urllib.parse.quote_plus(SOCKET)),
            json.dumps({'Name': name}))
        snapshots = get_from(resp, 'Snapshots')
        if snapshots is None:
            sys.exit(1)
        elif snapshots:
            print('\n'.join(snapshots))

    def run(args):
        serve(app, unix_socket=SOCKET)

    parser_snapshot.set_defaults(func=snapshot)
    parser_snapshots.set_defaults(func=snapshots)
    parser_run.set_defaults(func=run)

    args = parser.parse_args()
    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()
