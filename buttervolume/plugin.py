import configparser
import csv
import json
import logging
import os
from bottle import request, route
from buttervolume import btrfs
from datetime import datetime
from os.path import join, basename, dirname
from subprocess import CalledProcessError
from subprocess import run, PIPE


config = configparser.ConfigParser()
config.read('/etc/buttervolume/config.ini')


def getconfig(config, var, default):
    """read the var from the environ, then config file, then default
    """
    return (os.environ.get('BUTTERVOLUME_' + var)
            or config['DEFAULT'].get(var, default))


# overrideable defaults with config file
VOLUMES_PATH = getconfig(config, 'VOLUMES_PATH',
                         '/var/lib/buttervolume/volumes/')
SNAPSHOTS_PATH = getconfig(config, 'SNAPSHOTS_PATH',
                           '/var/lib/buttervolume/snapshots/')
TEST_REMOTE_PATH = getconfig(config, 'TEST_REMOTE_PATH',
                             '/var/lib/buttervolume/received/')
SCHEDULE = getconfig(config, 'SCHEDULE',
                     '/etc/buttervolume/schedule.csv')
SOCKET = getconfig(config, 'SOCKET',
                   '/run/docker/plugins/btrfs.sock')
TIMER = int(getconfig(config, 'TIMER', 60))
DTFORMAT = getconfig(config, 'DTFORMAT', '%Y-%m-%dT%H:%M:%S.%f')
LOGLEVEL = getattr(logging, getconfig(config, 'LOGLEVEL', 'INFO'))
SCHEDULE_LOG = {'snapshot': {}, 'replicate': {}, 'synchronize': {}}

logging.basicConfig(level=LOGLEVEL)
log = logging.getLogger()


def jsonloads(stuff):
    return json.loads(stuff.decode())


@route('/Plugin.Activate', ['POST'])
def plugin_activate():
    return json.dumps({'Implements': ['VolumeDriver']})


@route('/VolumeDriver.Create', ['POST'])
def volume_create():
    name = jsonloads(request.body.read())['Name']
    if '@' in name:
        return json.dumps({'Err': '"@" is illegal in a volume name'})
    volpath = join(VOLUMES_PATH, name)
    # volume already exists?
    if name in [v['Name']for v in json.loads(volume_list())['Volumes']]:
        return json.dumps({'Err': ''})
    try:
        btrfs.Subvolume(volpath).create()
    except CalledProcessError as e:
        return json.dumps({'Err': e.stderr})
    except OSError as e:
        return json.dumps({'Err': e.strerror})
    except Exception as e:
        return json.dumps({'Err': str(e)})
    return json.dumps({'Err': ''})


@route('/VolumeDriver.Mount', ['POST'])
def volume_mount():
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
        log.error('%s: no such volume', name)
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


@route('/VolumeDriver.Volume.Sync', ['POST'])
def volume_sync():
    """Rsync between two nodes"""
    test = jsonloads(request.body.read()).get('Test', False)
    remote_volumes = VOLUMES_PATH if not test else TEST_REMOTE_PATH
    volumes = jsonloads(request.body.read())['Volumes']
    remote_hosts = jsonloads(request.body.read())['Hosts']
    port = os.getenv("SSH_PORT", '1122')
    errors = list()
    for volume_name in volumes:
        local_volume_path = join(VOLUMES_PATH, volume_name)
        remote_volume_path = join(remote_volumes, volume_name)
        for remote_host in remote_hosts:
            log.debug(
                "Rsync volume: %s from host: %s",
                local_volume_path, remote_host
            )
            try:
                cmd = [
                    'rsync', '-v', '-r', '-a', '-z', '-h', '-P',
                    '--update',
                    '-e', "ssh -p {}".format(port),
                    '{}:{}/'.format(remote_host, remote_volume_path),
                    local_volume_path,
                ]
                log.debug("Running %r", cmd)
                run(cmd, check=True, stdout=PIPE, stderr=PIPE)
            except Exception as ex:
                err = getattr(ex, 'stderr', ex)
                error_message = "Error while rsync {} from {} (cmd: {}): " \
                                "{}".format(volume_name, remote_host, cmd, err)
                log.error(error_message)
                errors.append(error_message)

    return json.dumps({'Err': '\n'.join(errors)})


@route('/VolumeDriver.Capabilities', ['POST'])
def driver_cap():
    """butter volumes are local to the active node.
    They only exist as snapshots on the remote nodes.
    """
    return json.dumps({"Capabilities": {"Scope": "local"}})


@route('/VolumeDriver.Snapshot.Send', ['POST'])
def snapshot_send():
    """The last sent snapshot is remembered by adding a suffix with the target
    """
    test = jsonloads(request.body.read()).get('Test', False)
    snapshot_name = jsonloads(request.body.read())['Name']
    snapshot_path = join(SNAPSHOTS_PATH, snapshot_name)
    remote_host = jsonloads(request.body.read())['Host']
    remote_snapshots = SNAPSHOTS_PATH if not test else TEST_REMOTE_PATH
    # take the latest snapshot suffixed with the target host
    sent_snapshots = sorted(
        [s for s in os.listdir(SNAPSHOTS_PATH)
         if len(s.split('@')) == 3 and
         s.split('@')[0] == snapshot_name.split('@')[0] and
         s.split('@')[2] == remote_host])
    latest = sent_snapshots[-1] if len(sent_snapshots) > 0 else None
    if latest and len(latest.rsplit('@')) == 3:
        latest = latest.rsplit('@', 1)[0]
    parent = '-p "{}"'.format(join(SNAPSHOTS_PATH, latest)) if latest else ''
    port = os.getenv("SSH_PORT", '1122')
    # needed by a current issue with send
    run('btrfs filesystem sync "{}"'.format(SNAPSHOTS_PATH), shell=True)
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
    timestamped = '{}@{}'.format(name, datetime.now().strftime(DTFORMAT))
    snapshot_path = join(SNAPSHOTS_PATH, timestamped)
    if not os.path.exists(path):
        return json.dumps({'Err': 'No such volume: {}'.format(name)})
    try:
        btrfs.Subvolume(path).snapshot(snapshot_path, readonly=True)
    except Exception as e:
        log.error("Error creating snapshot: %s", str(e))
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
        log.error("Error deleting snapshot: %s", str(e))
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
    params = jsonloads(request.body.read())
    snapshot_name = params['Name']
    target_name = params.get('Target')
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
    target_name = target_name or snapshot_name.split('@')[0]
    target_path = join(VOLUMES_PATH, target_name)
    volume = btrfs.Subvolume(target_path)
    res = {'Err': ''}
    if snapshot.exists():
        if volume.exists():
            # backup and delete
            timestamp = datetime.now().strftime(DTFORMAT)
            stamped_name = '{}@{}'.format(target_name, timestamp)
            stamped_path = join(SNAPSHOTS_PATH, stamped_name)
            volume.snapshot(stamped_path, readonly=True)
            res['VolumeBackup'] = stamped_name
            volume.delete()
        snapshot.snapshot(target_path)
    else:
        res['Err'] = 'No such snapshot'
    return json.dumps(res)


@route('/VolumeDriver.Clone', ['POST'])
def snapshot_clone():
    """
    Create a new volume as clone from another.
    """
    params = jsonloads(request.body.read())
    volume_name = params['Name']
    target_name = params.get('Target')
    volume_path = join(VOLUMES_PATH, volume_name)
    target_path = join(VOLUMES_PATH, target_name)
    volume = btrfs.Subvolume(volume_path)
    res = {'Err': ''}
    if volume.exists():
        # clone
        volume.snapshot(target_path)
        res['VolumeCloned'] = target_name
    else:
        res['Err'] = 'No such volume'
    return json.dumps(res)


@route('/VolumeDriver.Snapshots.Purge', ['POST'])
def snapshots_purge():
    """
    Purge snapshots with a retention pattern
    (see cli help)
    """
    params = jsonloads(request.body.read())
    volume_name = params['Name']
    dryrun = params.get('Dryrun', False)

    # convert the pattern to seconds, check validity and reorder
    units = {'m': 1, 'h': 60, 'd': 60*24, 'w': 60*24*7, 'y': 60*24*365}
    try:
        pattern = sorted(int(i[:-1])*units[i[-1]]
                         for i in params['Pattern'].split(':'))
        assert(len(pattern) >= 2)
    except:
        log.error("Invalid purge pattern: %s", params['Pattern'])
        return json.dumps({'Err': 'Invalid purge pattern'})

    # snapshots related to the volume, more recents first
    snapshots = (s for s in os.listdir(SNAPSHOTS_PATH)
                 if s.startswith(volume_name + '@'))
    try:
        for snapshot in compute_purges(snapshots, pattern, datetime.now()):
            if dryrun:
                log.info('(Dry run) Would delete snapshot {}'
                         .format(snapshot))
            else:
                    btrfs.Subvolume(
                        join(SNAPSHOTS_PATH, snapshot)).delete()
                    log.info('Deleted snapshot {}'.format(snapshot))
    except Exception as e:
        log.error("Error purging snapshots: %s", e.strerror)
        return json.dumps({'Err': e.strerror})
    return json.dumps({'Err': ''})


def compute_purges(snapshots, pattern, now):
    """Return the list of snapshots to purge,
    given a list of snapshots, a purge pattern and a now time
    """
    snapshots = sorted(snapshots)
    pattern = sorted(pattern, reverse=True)
    purge_list = []
    max_age = pattern[0]
    # Age of the snapshots in minutes.
    # Example : [30, 70, 90, 150, 210, ..., 4000]
    snapshots_age = []
    valid_snapshots = []
    for s in snapshots:
        try:
            snapshots_age.append(
                int((now - datetime.strptime(
                    s.split('@')[1], DTFORMAT)).total_seconds()
                    )/60)
            valid_snapshots.append(s)
        except:
            log.info("Skipping purge of %s with invalid date format", s)
            continue
    if not valid_snapshots:
        return purge_list
    # pattern = 3600:180:60
    # age segments = [(3600, 180), (180, 60)]
    for age_segment in [(pattern[i], pattern[i+1])
                        for i, p in enumerate(pattern[:-1])]:
        last_timeframe = -1
        for i, age in enumerate(snapshots_age):
            # if the age is outside the age_segment, delete nothing.
            # Only 70 and 90 are inside the age_segment (60, 180)
            if age > age_segment[0] < max_age or age < age_segment[1]:
                continue
            # Now get the timeframe number of the snapshot.
            # Ages 70 and 90 are in the same timeframe (70//60 == 90//60)
            timeframe = age // age_segment[1]
            # delete if we already had a snapshot in the same timeframe
            # or if the snapshot is very old
            if timeframe == last_timeframe or age > max_age:
                purge_list.append(valid_snapshots[i])
            last_timeframe = timeframe
    return purge_list
