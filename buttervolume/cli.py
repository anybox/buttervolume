import argparse
import csv
import json
import logging
import os
import requests_unixsocket
import signal
from requests.exceptions import ConnectionError
import sys
import urllib
from bottle import app
from buttervolume.plugin import SCHEDULE
from buttervolume.plugin import VOLUMES_PATH, SNAPSHOTS_PATH
from buttervolume.plugin import LOGLEVEL, SOCKET, USOCKET, TIMER, SCHEDULE_LOG
from datetime import datetime, timedelta
from subprocess import CalledProcessError
from threading import Timer
from waitress import serve
from webtest import TestApp


logging.basicConfig(level=LOGLEVEL)
log = logging.getLogger()
app = app()
CURRENTTIMER = None


class Session(object):
    """wrapper for requests_unixsocket.Session
    """
    def __init__(self):
        self.session = requests_unixsocket.Session()

    def post(self, *a, **kw):
        try:
            return self.session.post(*a, **kw)
        except ConnectionError:
            log.error('Failed to connect to Buttervolume. '
                      'You can start it with: buttervolume run')
            return

    def get(self, *a, **kw):
        try:
            return self.session.get(*a, **kw)
        except ConnectionError:
            log.error('Failed to connect to Buttervolume. '
                      'You can start it with: buttervolume run')


def get_from(resp, key):
    """get specified key from plugin response output
    """
    if resp is None:
        return False
    try:  # bottle
        content = resp.content
    except:  # TestApp
        content = resp.body
    if resp.status_code == 200:
        error = json.loads(content.decode())['Err']
        if error:
            log.error(error)
            return False
        return json.loads(content.decode()).get(key)
    else:
        log.error('%s: %s', resp.status_code, resp.reason)
        return False


def snapshot(args, test=False):
    urlpath = '/VolumeDriver.Snapshot'
    param = json.dumps({'Name': args.name[0]})
    if test:
        resp = TestApp(app).post(urlpath, param)
    else:
        resp = Session().post(
            'http+unix://{}{}'
            .format(urllib.parse.quote_plus(USOCKET), urlpath),
            param)
    res = get_from(resp, 'Snapshot')
    if res:
        print(res)
    return res


def schedule(args):
    urlpath = '/VolumeDriver.Schedule'
    param = json.dumps({
        'Name': args.name[0],
        'Action': args.action[0],
        'Timer': args.timer[0]})
    resp = Session().post(
        'http+unix://{}{}'.format(
            urllib.parse.quote_plus(USOCKET), urlpath), param)
    res = get_from(resp, '')
    return res


def scheduled(args):
    urlpath = '/VolumeDriver.Schedule.List'
    resp = Session().get(
        'http+unix://{}{}'
        .format(urllib.parse.quote_plus(USOCKET), urlpath))
    scheduled = get_from(resp, 'Schedule')
    if scheduled:
        print('\n'.join(["{Action} {Timer} {Name}".format(**job)
                         for job in scheduled]))
    return scheduled


def snapshots(args):
    resp = Session().post(
        'http+unix://{}/VolumeDriver.Snapshot.List'
        .format(urllib.parse.quote_plus(USOCKET)),
        json.dumps({'Name': args.name}))
    snapshots = get_from(resp, 'Snapshots')
    if snapshots:
        print('\n'.join(snapshots))
    return snapshots


def restore(args):
    resp = Session().post(
        'http+unix://{}/VolumeDriver.Snapshot.Restore'
        .format(urllib.parse.quote_plus(USOCKET)),
        json.dumps({'Name': args.name[0], 'Target': args.target}))
    res = get_from(resp, 'VolumeBackup')
    if res:
        print(res)
    return res


def clone(args):
    resp = Session().post(
        'http+unix://{}/VolumeDriver.Clone'
        .format(urllib.parse.quote_plus(USOCKET)),
        json.dumps({'Name': args.name[0], 'Target': args.target}))
    res = get_from(resp, 'VolumeCloned')
    if res:
        print(res)
    return res


def send(args, test=False):
    urlpath = '/VolumeDriver.Snapshot.Send'
    param = {'Name': args.snapshot[0], 'Host': args.host[0]}
    if test:
        param['Test'] = True
        resp = TestApp(app).post(urlpath, json.dumps(param))
    else:
        resp = Session().post(
            'http+unix://{}{}'
            .format(urllib.parse.quote_plus(USOCKET), urlpath),
            json.dumps(param))
    res = get_from(resp, '')
    if res:
        print(res)
    return res


def sync(args, test=False):
    urlpath = '/VolumeDriver.Volume.Sync'
    param = {'Volumes': args.volumes, 'Hosts': args.hosts}
    if test:
        param['Test'] = True
        resp = TestApp(app).post(urlpath, json.dumps(param))
    else:
        resp = Session().post(
            'http+unix://{}{}'
            .format(urllib.parse.quote_plus(USOCKET), urlpath),
            json.dumps(param))
    res = get_from(resp, '')
    if res:
        print(res)
    return res


def remove(args):
    urlpath = '/VolumeDriver.Snapshot.Remove'
    param = json.dumps({'Name': args.name[0]})
    resp = Session().post(
        ('http+unix://{}{}')
        .format(urllib.parse.quote_plus(USOCKET), urlpath),
        param)
    res = get_from(resp, '')
    if res:
        print(res)
    return res


def purge(args, test=False):
    urlpath = '/VolumeDriver.Snapshots.Purge'
    param = {'Name': args.name[0],
             'Pattern': args.pattern[0],
             'Dryrun': args.dryrun}
    if test:
        param['Test'] = True
        resp = TestApp(app).post(urlpath, json.dumps(param))
    else:
        resp = Session().post(
            'http+unix://{}{}'
            .format(urllib.parse.quote_plus(USOCKET), urlpath),
            json.dumps(param))
    res = get_from(resp, '')
    if res:
        print(res)
    return res


class Arg():
    def __init__(self, *a, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def scheduler(config=SCHEDULE, test=False):
    """Read the scheduler config and apply it, then scheduler again.
    WARNING: this should be guaranteed against runtime errors
    otherwise the next scheduler won't run
    """
    global CURRENTTIMER
    log.info("New scheduler job at %s", datetime.now())
    # open the config and launch the tasks
    if not os.path.exists(config):
        log.warn('No config file %s', config)
        if not test:
            CURRENTTIMER = Timer(TIMER, scheduler)
            CURRENTTIMER.start()
        return
    name = action = timer = ''
    # run each action in the schedule if time is elapsed since the last one
    with open(config) as f:
        for line in csv.reader(f):
            try:
                name, action, timer = line
                now = datetime.now()
                # just starting, we consider beeing late on snapshots
                SCHEDULE_LOG.setdefault(action, {})
                SCHEDULE_LOG[action].setdefault(name, now - timedelta(1))
                last = SCHEDULE_LOG[action][name]
                if now < last + timedelta(minutes=int(timer)):
                    continue
                if action not in SCHEDULE_LOG.keys():
                    log.warn("Skipping invalid action %s", action)
                    continue
                # choose and run the right action
                if action == "snapshot":
                    log.info("Starting scheduled snapshot of %s", name)
                    snap = snapshot(Arg(name=[name]), test=test)
                    if not snap:
                        log.info("Could not snapshot %s", name)
                        continue
                    log.info("Successfully snapshotted to %s", snap)
                    SCHEDULE_LOG[action][name] = now
                if action.startswith('replicate:'):
                    _, host = action.split(':')
                    log.info("Starting scheduled replication of %s", name)
                    snap = snapshot(Arg(name=[name]), test=test)
                    if not snap:
                        log.info("Could not snapshot %s", name)
                        continue
                    log.info("Successfully snapshotted to %s", snap)
                    send(Arg(snapshot=[snap], host=[host]), test=test)
                    log.info("Successfully replicated %s to %s", name, snap)
                    SCHEDULE_LOG[action][name] = now
                if action.startswith('purge:'):
                    _, pattern = action.split(':', 1)
                    log.info("Starting scheduled purge of %s with pattern %s",
                             name, pattern)
                    purge(Arg(name=[name], pattern=[pattern], dryrun=False),
                          test=test)
                    log.info("Finished purging")
                    SCHEDULE_LOG[action][name] = now
                if action.startswith('synchronize:'):
                    log.info("Starting scheduled synchronization of %s", name)
                    hosts = action.split(':')[1].split(',')
                    # do a snapshot to save state before pulling data
                    snap = snapshot(Arg(name=[name]), test=test)
                    log.debug("Successfully snapshotted to %s", snap)
                    sync(Arg(volumes=[name], hosts=hosts), test=test)
                    log.debug("End of %s synchronization from %s", name, hosts)
                    SCHEDULE_LOG[action][name] = now
            except CalledProcessError as e:
                log.error('Error processing scheduler action file %s '
                          'name=%s, action=%s, timer=%s, '
                          'exception=%s, stdout=%s, stderr=%s',
                          config, name, action, timer,
                          str(e), e.stdout, e.stderr)
            except Exception as e:
                log.error('Error processing scheduler action file %s '
                          'name=%s, action=%s, timer=%s\n%s',
                          config, name, action, timer, str(e))
    # schedule the next run
    if not test:  # run only once
        CURRENTTIMER = Timer(TIMER, scheduler)
        CURRENTTIMER.start()


def shutdown(signum, frame):
    global CURRENTTIMER
    CURRENTTIMER.cancel()
    sys.exit(0)


def run(args):
    global CURRENTTIMER
    if not os.path.exists(VOLUMES_PATH):
        log.info('Creating %s', VOLUMES_PATH)
        os.makedirs(VOLUMES_PATH, exist_ok=True)
    if not os.path.exists(SNAPSHOTS_PATH):
        log.info('Creating %s', SNAPSHOTS_PATH)
        os.makedirs(SNAPSHOTS_PATH, exist_ok=True)
    # run a thread for the scheduled snapshots
    print('Starting scheduler job every {}s'.format(TIMER))
    CURRENTTIMER = Timer(1, scheduler)
    CURRENTTIMER.start()
    signal.signal(signal.SIGTERM, shutdown)
    # listen to requests
    print('Listening to requests...')
    serve(app, unix_socket=SOCKET, unix_socket_perms='660')


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
        help='Name of the volume whose snapshots are to list')

    parser_schedule = subparsers.add_parser(
        'schedule', help='(un)Schedule a snapshot, replication, '
                         'synchronization or purge')
    parser_schedule.add_argument(
        'action', metavar='action', nargs=1,
        help=('Name of the action to schedule '
              '(snapshot, replicate:<host>, purge:<pattern>, '
              'synchronize:<host[,host2[,host3]]>)'))
    parser_schedule.add_argument(
        'timer', metavar='timer', nargs=1, type=int,
        help='Time span in minutes between two actions')
    parser_schedule.add_argument(
        'name', metavar='name', nargs=1,
        help='Name of the volume whose snapshots are to schedule')

    parser_scheduled = subparsers.add_parser(
        'scheduled', help='List scheduled actions')

    parser_restore = subparsers.add_parser(
        'restore', help='Restore a snapshot')
    parser_restore.add_argument(
        'name', metavar='name', nargs=1,
        help=('Name of the snapshot to restore '
              '(use the name of the volume to restore the latest snapshot)'))
    parser_restore.add_argument(
        'target', metavar='target', nargs='?', default=None,
        help=('Name of the restored volume'))

    parser_clone = subparsers.add_parser(
        'clone', help='Clone a volume')
    parser_clone.add_argument(
        'name', metavar='name', nargs=1,
        help=('Name of the volume to be cloned'))
    parser_clone.add_argument(
        'target', metavar='target', nargs='?', default=None,
        help=('Name of the new volume to be created'))

    parser_send = subparsers.add_parser(
        'send', help='Send a snapshot to another host')
    parser_send.add_argument(
        'host', metavar='host', nargs=1,
        help='Host to send the snapshot to')
    parser_send.add_argument(
        'snapshot', metavar='snapshot', nargs=1,
        help='Snapshot to send')

    parser_sync = subparsers.add_parser(
        'sync', help='Sync a volume from other host(s)')
    parser_sync.add_argument(
        'volumes', metavar='volumes', nargs=1,
        help='Volumes to sync (1 max)')
    parser_sync.add_argument(
        'hosts', metavar='hosts', nargs='*',
        help='Host list to sync data from (space separator)')

    parser_remove = subparsers.add_parser(
        'rm', help='Delete a snapshot')
    parser_remove.add_argument(
        'name', metavar='name', nargs=1, help='Name of the snapshot to delete')
    parser_purge = subparsers.add_parser(
        'purge', help="Purge old snapshot using a purge pattern")
    parser_purge.add_argument(
        'pattern', metavar='pattern', nargs=1,
        help=("Purge pattern (X:Y, or X:Y:Z, or X:Y:Z:T, etc.)\n"
              "Pattern components must have a suffix with the unit:\n"
              "  m = minutes, h = hours, d = days, w = weeks, y = years\n"
              "So 4h:1d:1w means:\n"
              "  Keep all snapshots in the last four hours,\n"
              "  then keep 1 snapshot every 4 hours during 1 day,\n"
              "  then keep 1 snapshot every day during the 1st week\n"
              "  then delete snapshots older than 1 week.\n"))
    parser_purge.add_argument(
        'name', metavar='name', nargs=1,
        help=("Name of the volume whose snapshots are to purge"))
    parser_purge.add_argument(
        '--dryrun', action='store_true',
        help="Don't really purge but tell what would be deleted")

    parser_run.set_defaults(func=run)
    parser_snapshot.set_defaults(func=snapshot)
    parser_snapshots.set_defaults(func=snapshots)
    parser_schedule.set_defaults(func=schedule)
    parser_scheduled.set_defaults(func=scheduled)
    parser_restore.set_defaults(func=restore)
    parser_clone.set_defaults(func=clone)
    parser_send.set_defaults(func=send)
    parser_sync.set_defaults(func=sync)
    parser_remove.set_defaults(func=remove)
    parser_purge.set_defaults(func=purge)

    args = parser.parse_args()
    if hasattr(args, 'func'):
        if args.func(args) is False:
            sys.exit(1)
    else:
        parser.print_help()
