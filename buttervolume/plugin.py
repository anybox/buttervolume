import csv
import json
import logging
import os
from bottle import request, route
from buttervolume import btrfs
from datetime import datetime
from os.path import join, basename, exists, dirname
from subprocess import check_call, CalledProcessError
from subprocess import run, PIPE
logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger()

# absolute path to the volumes
VOLUMES_PATH = "/var/lib/docker/volumes/"
SNAPSHOTS_PATH = "/var/lib/docker/snapshots/"
TEST_RECEIVE_PATH = "/var/lib/docker/received/"
SCHEDULE = "/etc/buttervolume/schedule.csv"
SCHEDULE_LOG = {'snapshot': {}, 'replicate': {}}


def jsonloads(stuff):
    return json.loads(stuff.decode())


@route('/Plugin.Activate', ['POST'])
def plugin_activate():
    return json.dumps({'Implements': ['VolumeDriver']})


@route('/VolumeDriver.Create', ['POST'])
def volume_create():
    name = jsonloads(request.body.read())['Name']
    if '@' in name:
        return json.dumps({'Err': '"@" is illegal in the name of the volume'})
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
            log.info("disabled COW on %s", path)
        except Exception:
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
    if not btrfs.Subvolume(path).exists():
        return json.dumps({'Err': '{}: no such volume'.format(path)})
    return json.dumps({'Mountpoint': path, 'Err': ''})


@route('/VolumeDriver.Unmount', ['POST'])
def volume_unmount():
    return json.dumps({'Err': ''})


@route('/VolumeDriver.Get', ['POST'])
def volume_get():
    name = jsonloads(request.body.read())['Name']
    path = join(VOLUMES_PATH, name)
    if not btrfs.Subvolume(path).exists():
        return json.dumps({'Err': '{}: no such volume'.format(path)})
    return json.dumps(
        {'Volume': {'Name': name, 'Mountpoint': path}, 'Err': ''})


@route('/VolumeDriver.Remove', ['POST'])
def volume_remove():
    name = jsonloads(request.body.read())['Name']
    path = join(VOLUMES_PATH, name)
    try:
        btrfs.Subvolume(path).delete()
    except Exception:
        return json.dumps({'Err': '{}: no such volume'.format(name)})
    return json.dumps({'Err': ''})


@route('/VolumeDriver.List', ['POST'])
def volume_list():
    volumes = []
    for p in [join(VOLUMES_PATH, v) for v in os.listdir(VOLUMES_PATH)
              if v != 'metadata.db']:
        if not btrfs.Subvolume(p).exists():
            continue
        volumes.append(p)
    return json.dumps({'Volumes': [{'Name': basename(v)} for v in volumes],
                       'Err': ''})


@route('/VolumeDriver.Snapshot.Send', ['POST'])
def snapshot_send():
    """The last sent snapshot is remembered by adding a suffix with the target
    """
    test = jsonloads(request.body.read()).get('Test', False)
    snapshot_name = jsonloads(request.body.read())['Name']
    snapshot_path = join(SNAPSHOTS_PATH, snapshot_name)
    remote_host = jsonloads(request.body.read())['Host']
    remote_snapshots = SNAPSHOTS_PATH if not test else TEST_RECEIVE_PATH
    # take the latest snapshot suffixed with the target host
    sent_snapshots = sorted(
        [s for s in os.listdir(SNAPSHOTS_PATH)
         if len(s.split('@')) == 3
         and s.split('@')[0] == snapshot_name.split('@')[0]
         and s.split('@')[2] == remote_host])
    latest = sent_snapshots[-1] if len(sent_snapshots) > 0 else None
    if latest and len(latest.rsplit('@')) == 3:
        latest = latest.rsplit('@', 1)[0]
    parent = '-p "{}"'.format(join(SNAPSHOTS_PATH, latest)) if latest else ''
    port = '1122'
    if test:  # I currently run tests outside docker
        port = '22'
    run('sync', shell=True)  # needed by a current issue with send
    cmd = ('btrfs send {parent} "{snapshot_path}"'
           ' | ssh -p {port} {remote_host} "btrfs receive {remote_snapshots}"')
    try:
        log.info(cmd.format(**locals()))
        run(cmd.format(**locals()),
            shell=True, check=True, stdout=PIPE, stderr=PIPE)
    except CalledProcessError as e:
        log.warn('Failed using parent %s. Sending full snapshot %s '
                 '(stdout: %s, stderr: %s)',
                 latest, snapshot_path, e.stdout, e.stderr)
        parent = ''
        try:
            rmcmd = (
                'ssh -p {port} {remote_host} '
                '"btrfs subvolume delete {remote_snapshots}/{snapshot_name}"')
            log.info(rmcmd.format(**locals()))
            run(rmcmd.format(**locals()), shell=True, stdout=PIPE, stderr=PIPE)
            log.info(cmd.format(**locals()))
            run(cmd.format(**locals()),
                shell=True, check=True, stdout=PIPE, stderr=PIPE)
        except CalledProcessError as e:
            log.error('Failed sending full snapshot '
                      '(stdout: %s, stderr: %s)',
                      e.stdout, e.stderr)
            return json.dumps({'Err': str(e.stderr)})
    btrfs.Subvolume(snapshot_path).snapshot(
        '{}@{}'.format(snapshot_path, remote_host), readonly=True)
    for old_snapshot in sent_snapshots:
        btrfs.Subvolume(old_snapshot).delete
    return json.dumps({'Err': ''})


@route('/VolumeDriver.Snapshot', ['POST'])
def volume_snapshot():
    """snapshot a volume in the SNAPSHOTS dir
    """
    name = jsonloads(request.body.read())['Name']
    path = join(VOLUMES_PATH, name)
    timestamped = '{}@{}'.format(name, datetime.now().isoformat())
    snapshot_path = join(SNAPSHOTS_PATH, timestamped)
    if not os.path.exists(path):
        return json.dumps({'Err': 'No such volume: {}'.format(name)})
    try:
        btrfs.Subvolume(path).snapshot(snapshot_path, readonly=True)
    except Exception as e:
        return json.dumps({'Err': str(e)})
    return json.dumps({'Err': '', 'Snapshot': timestamped})


@route('/VolumeDriver.Snapshot.List', ['POST'])
def snapshot_list():
    name = jsonloads(request.body.read()).get('Name')
    snapshots = os.listdir(SNAPSHOTS_PATH)
    if name:
        snapshots = [s for s in snapshots if s.startswith(name + '@')]
    return json.dumps({'Err': '', 'Snapshots': snapshots})


@route('/VolumeDriver.Snapshot.Remove', ['POST'])
def snapshot_delete():
    name = jsonloads(request.body.read())['Name']
    path = join(SNAPSHOTS_PATH, name)
    if not os.path.exists(path):
        return json.dumps({'Err': 'No such snapshot'})
    try:
        btrfs.Subvolume(path).delete()
    except Exception as e:
        return json.dumps({'Err': str(e)})
    return json.dumps({'Err': ''})


@route('/VolumeDriver.Schedule', ['POST'])
def schedule():
    """Schedule or unschedule a job
    TODO add a lock
    """
    name = jsonloads(request.body.read())['Name']
    timer = jsonloads(request.body.read())['Timer']
    action = jsonloads(request.body.read())['Action']
    schedule = []
    if timer:  # 0 means unschedule!
        schedule.append((name, action, timer))
    if os.path.exists(SCHEDULE):
        with open(SCHEDULE) as f:
            for n, a, t in csv.reader(f):
                # skip the line we want to write
                if n == name and a == action:
                    continue
                schedule.append((n, a, t))
    os.makedirs(dirname(SCHEDULE), exist_ok=True)
    with open(SCHEDULE, 'w') as f:
        for line in schedule:
            csv.writer(f).writerow(line)
    return json.dumps({'Err': ''})


@route('/VolumeDriver.Schedule.List', ['GET'])
def schedule_list():
    """List scheduled jobs
    """
    schedule = []
    if os.path.exists(SCHEDULE):
        with open(SCHEDULE) as f:
            for n, a, t in csv.reader(f):
                schedule.append({'Name': n, 'Timer': t, 'Action': a})
    return json.dumps({'Err': '', 'Schedule': schedule})


@route('/VolumeDriver.Snapshot.Restore', ['POST'])
def snapshot_restore():
    """
    Snapshot a volume and overwrite it with the specified snapshot.
    """
    snapshot_name = jsonloads(request.body.read())['Name']
    if '@' not in snapshot_name:
        # we're passing the name of the volume. Use the latest snapshot.
        volume_name = snapshot_name
        snapshots = os.listdir(SNAPSHOTS_PATH)
        snapshots = [s for s in snapshots if s.startswith(volume_name + '@')]
        if not snapshots:
            return json.dumps({'Err': ''})
        snapshot_name = sorted(snapshots)[-1]
    snapshot_path = join(SNAPSHOTS_PATH, snapshot_name)
    snapshot = btrfs.Subvolume(snapshot_path)
    volume_name = snapshot_name.split('@')[0]
    volume_path = join(VOLUMES_PATH, volume_name)
    volume = btrfs.Subvolume(volume_path)
    res = {'Err': ''}
    if snapshot.exists():
        if volume.exists():
            # backup and delete
            timestamp = datetime.now().isoformat()
            stamped_name = '{}@{}'.format(volume_name, timestamp)
            stamped_path = join(SNAPSHOTS_PATH, stamped_name)
            volume.snapshot(stamped_path, readonly=True)
            res['VolumeBackup'] = stamped_name
            volume.delete()
        snapshot.snapshot(volume_path)
    else:
        res['Err'] = 'No such snapshot'
    return json.dumps(res)


@route('/VolumeDriver.Snapshots.Purge', ['POST'])
def snapshots_purge():
    """
    Purge snapshots with a save pattern
    x:y : keep 1 snapshot every x minutes during the first y minutes.
    x:y:z : keep 1 snapshot every x minutes during the first y minutes,
            then 1 snapshot every y minutes during the next z minutes
    x:y:z:t : keep 1 snapshot every x minutes during... (same)
    """
    params = jsonloads(request.body.read())
    volume_name = params['Name']
    dryrun = params.get('Dryrun', False)
    try:
        pattern = sorted(int(i) for i in params['Pattern'].split(':'))
        assert(len(pattern) >= 2)
        max_age = pattern[-1]
    except:
        return {'Err': 'Invalid purge pattern'}
    # snapshots related to the volume, more recents first
    snapshots = sorted([s for s in os.listdir(SNAPSHOTS_PATH)
                        if s.startswith(volume_name + '@')], reverse=True)
    now = datetime.now()
    # Age of the snapshots in minutes.
    # Example : [30, 70, 90, 150, 210, ..., 4000]
    snapshots_age = [int((now - datetime.strptime(
                        s.split('@')[1],
                        "%Y-%m-%dT%H:%M:%S.%f")).total_seconds())//60
                     for s in snapshots]
    if not snapshots:
        return {'Err': ''}
    # pattern = 60:180:3600
    # age segments = [(60, 180), (180, 3600)]
    try:
        for age_segment in [(pattern[i], pattern[i+1])
                            for i, p in enumerate(pattern[:-1])]:
            last_timeframe = -1
            for i, age in enumerate(snapshots_age):
                # if the age is outside the age_segment, delete nothing.
                # Only 70 and 90 are inside the age_segment (60, 180)
                if age < age_segment[0] or age >= age_segment[1] < max_age:
                    continue
                # Now get the timeframe of the snapshot.
                # Ages 70 and 90 are in the same timeframe (70//60 == 90//60)
                timeframe = age // age_segment[0]
                # delete if we already had a snapshot in the same timeframe
                # or if the snapshot is very old
                if timeframe == last_timeframe or age > max_age:
                    snapshot = snapshots[i]
                    if dryrun:
                        log.info('(Dry run) Would delete snapshot {}'
                                 .format(snapshot))
                    else:
                        btrfs.Subvolume(
                            join(SNAPSHOTS_PATH, snapshot)).delete()
                        log.info('Deleted snapshot {}'.format(snapshot))
                last_timeframe = timeframe
    except Exception as e:
        return json.dumps({'Err': e.strerror})
    return json.dumps({'Err': ''})
