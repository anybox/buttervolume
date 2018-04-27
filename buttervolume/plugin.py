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
DRIVERNAME = getconfig(config, 'DRIVERNAME', 'anybox/buttervolume:latest')
RUNPATH = getconfig(config, 'RUNPATH', '/run/docker')
SOCKET = getconfig(config, 'SOCKET',
                   os.path.join(RUNPATH, 'plugins', 'btrfs.sock'))
USOCKET = SOCKET
if not os.path.exists(USOCKET):
    # socket path on the host or another container
    plugins = json.loads(
        run('docker plugin inspect {}'.format(DRIVERNAME),
            shell=True, stdout=PIPE, stderr=PIPE).stdout.decode())
    if plugins:
        plugin = plugins[0]  # can we have several plugins with the same name?
        USOCKET = os.path.join(RUNPATH, 'plugins', plugin['Id'], 'btrfs.sock')

TIMER = int(getconfig(config, 'TIMER', 60))
DTFORMAT = getconfig(config, 'DTFORMAT', '%Y-%m-%dT%H:%M:%S.%f')
LOGLEVEL = getattr(logging, getconfig(config, 'LOGLEVEL', 'INFO'))
SCHEDULE_LOG = {'snapshot': {}, 'replicate': {}, 'synchronize': {}}

logging.basicConfig(level=LOGLEVEL)
log = logging.getLogger()


def add_debug_log(handler):
    def new_handler():
        req = json.loads(request.body.read().decode() or '{}')
        log.debug('Request: %s %s', request.path, req)
        resp = json.dumps(handler(req))
        log.debug('Response: %s', resp)
        return resp
    return new_handler


@route('/Plugin.Activate', ['POST'])
@add_debug_log
def plugin_activate(req):
    return {'Implements': ['VolumeDriver']}


@route('/VolumeDriver.Create', ['POST'])
@add_debug_log
def volume_create(req):
    name = req['Name']
    if '@' in name:
        return {'Err': '"@" is illegal in a volume name'}
    volpath = join(VOLUMES_PATH, name)
    # volume already exists?
    if name in [v['Name']for v in list_volumes()['Volumes']]:
        return {'Err': ''}
    try:
        btrfs.Subvolume(volpath).create()
    except CalledProcessError as e:
        return {'Err': e.stderr.decode()}
    except OSError as e:
        return {'Err': e.strerror}
    except Exception as e:
        return {'Err': str(e)}
    return {'Err': ''}


def volumepath(name):
    path = join(VOLUMES_PATH, name)
    if not btrfs.Subvolume(path).exists():
        return None
    return path


@route('/VolumeDriver.Mount', ['POST'])
@add_debug_log
def volume_mount(req):
    name = req['Name']
    path = volumepath(name)
    if path is None:
        return {'Err': '{}: no such volume'.format(name)}
    return {'Mountpoint': path, 'Err': ''}


@route('/VolumeDriver.Path', ['POST'])
@add_debug_log
def volume_path(req):
    name = req['Name']
    path = volumepath(name)
    if path is None:
        return {'Err': '{}: no such volume'.format(name)}
    return {'Mountpoint': path, 'Err': ''}


@route('/VolumeDriver.Unmount', ['POST'])
@add_debug_log
def volume_unmount(req):
    return {'Err': ''}


@route('/VolumeDriver.Get', ['POST'])
@add_debug_log
def volume_get(req):
    name = req['Name']
    path = volumepath(name)
    if path is None:
        return {'Err': '{}: no such volume'.format(name)}
    return {'Volume': {'Name': name, 'Mountpoint': path}, 'Err': ''}


@route('/VolumeDriver.Remove', ['POST'])
@add_debug_log
def volume_remove(req):
    name = req['Name']
    path = join(VOLUMES_PATH, name)
    try:
        btrfs.Subvolume(path).delete()
    except Exception:
        log.error('%s: no such volume', name)
        return {'Err': '{}: no such volume'.format(name)}
    return {'Err': ''}


@route('/VolumeDriver.List', ['POST'])
@add_debug_log
def volume_list(req):
    return list_volumes()


def list_volumes():
    volumes = []
    for p in [join(VOLUMES_PATH, v) for v in os.listdir(VOLUMES_PATH)
              if v != 'metadata.db']:
        if not btrfs.Subvolume(p).exists():
            continue
        volumes.append(p)
    return {'Volumes': [{'Name': basename(v)} for v in volumes], 'Err': ''}


@route('/VolumeDriver.Volume.Sync', ['POST'])
@add_debug_log
def volume_sync(req):
    """Rsync between two nodes"""
    test = req.get('Test', False)
    remote_volumes = VOLUMES_PATH if not test else TEST_REMOTE_PATH
    volumes = req['Volumes']
    remote_hosts = req['Hosts']
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

    return {'Err': '\n'.join(errors)}


@route('/VolumeDriver.Capabilities', ['POST'])
@add_debug_log
def driver_cap(req):
    """butter volumes are local to the active node.
    They only exist as snapshots on the remote nodes.
    """
    return {"Capabilities": {"Scope": "local"}}


@route('/VolumeDriver.Snapshot.Send', ['POST'])
@add_debug_log
def snapshot_send(req):
    """The last sent snapshot is remembered by adding a suffix with the target
    """
    test = req.get('Test', False)
    snapshot_name = req['Name']
    snapshot_path = join(SNAPSHOTS_PATH, snapshot_name)
    remote_host = req['Host']
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
            return {'Err': e.stderr.decode()}
    btrfs.Subvolume(snapshot_path).snapshot(
        '{}@{}'.format(snapshot_path, remote_host), readonly=True)
    for old_snapshot in sent_snapshots:
        btrfs.Subvolume(old_snapshot).delete
    return {'Err': ''}


@route('/VolumeDriver.Snapshot', ['POST'])
@add_debug_log
def volume_snapshot(req):
    """snapshot a volume in the SNAPSHOTS dir
    """
    name = req['Name']
    path = join(VOLUMES_PATH, name)
    timestamped = '{}@{}'.format(name, datetime.now().strftime(DTFORMAT))
    snapshot_path = join(SNAPSHOTS_PATH, timestamped)
    if not os.path.exists(path):
        return {'Err': 'No such volume: {}'.format(name)}
    try:
        btrfs.Subvolume(path).snapshot(snapshot_path, readonly=True)
    except Exception as e:
        log.error("Error creating snapshot: %s", str(e))
        return {'Err': str(e)}
    return {'Err': '', 'Snapshot': timestamped}


@route('/VolumeDriver.Snapshot.List', ['POST'])
@add_debug_log
def snapshot_list(req):
    name = req.get('Name')
    snapshots = os.listdir(SNAPSHOTS_PATH)
    if name:
        snapshots = [s for s in snapshots if s.startswith(name + '@')]
    return {'Err': '', 'Snapshots': snapshots}


@route('/VolumeDriver.Snapshot.Remove', ['POST'])
@add_debug_log
def snapshot_delete(req):
    name = req['Name']
    path = join(SNAPSHOTS_PATH, name)
    if not os.path.exists(path):
        return {'Err': 'No such snapshot'}
    try:
        btrfs.Subvolume(path).delete()
    except Exception as e:
        log.error("Error deleting snapshot: %s", str(e))
        return {'Err': str(e)}
    return {'Err': ''}


@route('/VolumeDriver.Schedule', ['POST'])
@add_debug_log
def schedule(req):
    """Schedule or unschedule a job
    TODO add a lock
    """
    name = req['Name']
    timer = req['Timer']
    action = req['Action']
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
    return {'Err': ''}


@route('/VolumeDriver.Schedule.List', ['GET'])
@add_debug_log
def schedule_list(req):
    """List scheduled jobs
    """
    schedule = []
    if os.path.exists(SCHEDULE):
        with open(SCHEDULE) as f:
            for n, a, t in csv.reader(f):
                schedule.append({'Name': n, 'Timer': t, 'Action': a})
    return {'Err': '', 'Schedule': schedule}


@route('/VolumeDriver.Snapshot.Restore', ['POST'])
@add_debug_log
def snapshot_restore(req):
    """
    Snapshot a volume and overwrite it with the specified snapshot.
    """
    snapshot_name = req['Name']
    target_name = req.get('Target')
    if '@' not in snapshot_name:
        # we're passing the name of the volume. Use the latest snapshot.
        volume_name = snapshot_name
        snapshots = os.listdir(SNAPSHOTS_PATH)
        snapshots = [s for s in snapshots if s.startswith(volume_name + '@')]
        if not snapshots:
            return {'Err': ''}
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
    return res


@route('/VolumeDriver.Clone', ['POST'])
@add_debug_log
def snapshot_clone(req):
    """
    Create a new volume as clone from another.
    """
    volumename = req['Name']
    targetname = req.get('Target')
    volumepath = join(VOLUMES_PATH, volumename)
    targetpath = join(VOLUMES_PATH, targetname)
    volume = btrfs.Subvolume(volumepath)
    res = {'Err': ''}
    if volume.exists():
        # clone
        volume.snapshot(targetpath)
        res['VolumeCloned'] = targetname
    else:
        res['Err'] = 'No such volume'
    return res


@route('/VolumeDriver.Snapshots.Purge', ['POST'])
@add_debug_log
def snapshots_purge(req):
    """
    Purge snapshots with a retention pattern
    (see cli help)
    """
    volume_name = req['Name']
    dryrun = req.get('Dryrun', False)

    # convert the pattern to seconds, check validity and reorder
    units = {'m': 1, 'h': 60, 'd': 60*24, 'w': 60*24*7, 'y': 60*24*365}
    try:
        pattern = sorted(int(i[:-1])*units[i[-1]]
                         for i in req['Pattern'].split(':'))
        assert(len(pattern) >= 2)
    except:
        log.error("Invalid purge pattern: %s", req['Pattern'])
        return {'Err': 'Invalid purge pattern'}

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
        return {'Err': e.strerror}
    return {'Err': ''}


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
