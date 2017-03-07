import argparse
import csv
import json
import logging
import os
import requests_unixsocket
from requests.exceptions import ConnectionError
import sys
import urllib
from bottle import app
from buttervolume.plugin import jsonloads, SCHEDULE
from buttervolume.plugin import SCHEDULE_LOG, SNAPSHOTS_PATH
from datetime import datetime, timedelta
from threading import Timer
from waitress import serve
from webtest import TestApp
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()
SOCKET = '/run/docker/plugins/btrfs.sock'
TIMER = 60
app = app()


class Session(object):
    """wrapper for requests_unixsocket.Session
    """
    def __init__(self):
        self.session = requests_unixsocket.Session()

    def post(self, *a, **kw):
        try:
            return self.session.post(*a, **kw)
        except ConnectionError:
            logger.error('Failed to connect to Buttervolume. '
                         'You can start it with: buttervolume run')
            sys.exit(1)

    def get(self, *a, **kw):
        try:
            return self.session.get(*a, **kw)
        except ConnectionError:
            logger.error('Failed to connect to Buttervolume. '
                         'You can start it with: buttervolume run')
            sys.exit(1)


def get_from(resp, key):
    """get specified key from plugin response output
    """
    try:  # bottle
        content = resp.content
    except:  # TestApp
        content = resp.body
    if resp.status_code != 200:
        logger.error('%s: %s', resp.status_code, resp.reason)
        sys.exit(1)
    else:
        error = jsonloads(content)['Err']
        if error:
            logger.error(error)
            sys.exit(1)
    return jsonloads(content).get(key)


def snapshot(args, test=False):
    urlpath = '/VolumeDriver.Snapshot'
    param = json.dumps({'Name': args.name[0]})
    if test:
        resp = TestApp(app).post(urlpath, param)
    else:
        resp = Session().post(
            'http+unix://{}{}'
            .format(urllib.parse.quote_plus(SOCKET), urlpath),
            param)
    res = get_from(resp, 'Snapshot') or sys.exit(1)
    if res:
        print(res)
        return res


def schedule(args):
    urlpath = '/VolumeDriver.Schedule'
    param = json.dumps({
        'Name': args.name[0],
        'Action': args.action[0],
        'Timer': args.timer[0]})
    Session().post(
        'http+unix://{}{}'
        .format(urllib.parse.quote_plus(SOCKET), urlpath), param)


def scheduled(args):
    urlpath = '/VolumeDriver.Schedule.List'
    resp = Session().get(
        'http+unix://{}{}'
        .format(urllib.parse.quote_plus(SOCKET), urlpath))
    scheduled = get_from(resp, 'Schedule')
    print('\n'.join(["{Action} {Timer} {Name}".format(**job)
                     for job in scheduled]))


def snapshots(args):
    resp = Session().post(
        'http+unix://{}/VolumeDriver.Snapshot.List'
        .format(urllib.parse.quote_plus(SOCKET)),
        json.dumps({'Name': args.name}))
    snapshots = get_from(resp, 'Snapshots')
    if snapshots is None:
        sys.exit(1)
    elif snapshots:
        print('\n'.join(snapshots))


def restore(args):
    resp = Session().post(
        'http+unix://{}/VolumeDriver.Snapshot.Restore'
        .format(urllib.parse.quote_plus(SOCKET)),
        json.dumps({'Name': args.name[0]}))
    res = get_from(resp, 'VolumeBackup')
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
            .format(urllib.parse.quote_plus(SOCKET), urlpath),
            json.dumps(param))
    res = get_from(resp, '')
    if res:
        print(res)


def remove(args):
    urlpath = '/VolumeDriver.Snapshot.Remove'
    param = json.dumps({'Name': args.name[0]})
    resp = Session().post(
        ('http+unix://{}{}')
        .format(urllib.parse.quote_plus(SOCKET), urlpath),
        param)
    res = get_from(resp, '')
    if res:
        print(res)


class Arg():
    def __init__(self, *a, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def scheduler(config=SCHEDULE, test=False):
    """Read the scheduler config and apply it, then scheduler again.
    WARNING: this should be guaranteed against runtime errors
    otherwise the next scheduler won't run
    """
    # open the config and launch the tasks
    if not os.path.exists(config):
        logger.warn('No config file %s', config)
        if not test:
            Timer(TIMER, scheduler).start()
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
                    logger.warn("Skipping invalid action %s", action)
                    continue
                # choose and run the right action
                if action == "snapshot":
                    logger.info("Running scheduled snapshot of %s", name)
                    snap = snapshot(Arg(name=[name]), test=test)
                    logger.info("Successfully snapshotted to %s", snap)
                    SCHEDULE_LOG[action][name] = now
                if action.startswith('replicate:'):
                    action, host = action.split(':')
                    logger.info("Running scheduled replication of %s", name)
                    snap = snapshot(Arg(name=[name]), test=test)
                    logger.info("Successfully snapshotted to %s", snap)
                    send(Arg(snapshot=[snap], host=[host]), test=test)
                    logger.info("Successfully replicated %s to %s", name, snap)
                    SCHEDULE_LOG[action][name] = now
            except Exception as e:
                logger.error('Error processing scheduler action file %s '
                             'name=%s, action=%s, timer=%s\n%s',
                             config, name, action, timer, str(e))
    # schedule the next run
    if not test:  # run only once
        Timer(TIMER, scheduler).start()


def run(args):
    if not os.path.exists(SNAPSHOTS_PATH):
        logger.info('Creating %s', SNAPSHOTS_PATH)
        os.makedirs(SNAPSHOTS_PATH, exist_ok=True)
    # run a thread for the scheduled snapshots
    print('Starting scheduler job every {}s'.format(TIMER))
    Timer(1, scheduler).start()
    # listen to requests
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
        'schedule', help='(un)Schedule a snapshot or replication')
    parser_schedule.add_argument(
        'action', metavar='action', nargs=1,
        help='Name of the action to schedule (snapshot, replicate:<host>)')
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
    parser_send = subparsers.add_parser(
        'send', help='Send a snapshot to another host')
    parser_send.add_argument(
        'host', metavar='host', nargs=1,
        help='Host to send the snapshot to')
    parser_send.add_argument(
        'snapshot', metavar='snapshot', nargs=1,
        help='Snapshot to send')
    parser_remove = subparsers.add_parser(
        'rm', help='Delete a snapshot')
    parser_remove.add_argument(
        'name', metavar='name', nargs=1, help='Name of the snapshot to delete')

    parser_run.set_defaults(func=run)
    parser_snapshot.set_defaults(func=snapshot)
    parser_snapshots.set_defaults(func=snapshots)
    parser_schedule.set_defaults(func=schedule)
    parser_scheduled.set_defaults(func=scheduled)
    parser_restore.set_defaults(func=restore)
    parser_send.set_defaults(func=send)
    parser_remove.set_defaults(func=remove)

    args = parser.parse_args()
    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()
