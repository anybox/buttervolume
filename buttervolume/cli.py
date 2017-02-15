import argparse
import csv
import json
import logging
import os
import requests_unixsocket
import sys
import urllib
from bottle import app
from buttervolume.plugin import jsonloads, SCHEDULE, SCHEDULE_LOG
from datetime import datetime, timedelta
from threading import Timer
from waitress import serve
from webtest import TestApp
logging.basicConfig()
logger = logging.getLogger()
SOCKET = '/run/docker/plugins/btrfs.sock'
TIMER = 60.0
app = app()


def get_from(resp, key):
    """get specified key from plugin response output
    """
    try:  # bottle
        content = resp.content
    except:  # TestApp
        content = resp.body
    error = jsonloads(content)['Err']
    if resp.status_code != 200:
        print('Error {}: {}'.format(resp.status_code, resp.reason),
              file=sys.stderr)
        return None
    elif error:
        print(error, file=sys.stderr)
        return None
    else:
        return jsonloads(content)[key]


def snapshot(args, test=False):
    name = args.name[0]
    urlpath = '/VolumeDriver.Snapshot'
    param = json.dumps({'Name': name})
    if test:
        resp = TestApp(app).post(urlpath, param)
    else:
        resp = requests_unixsocket.Session().post(
            ('http+unix://{}{}')
            .format(urllib.parse.quote_plus(SOCKET), urlpath),
            param)
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
        return
    name = action = timer = ''
    # run each action in the schedule if time is elapsed since the last one
    with open(config) as f:
        for line in csv.reader(f):
            try:
                name, action, timer = line
                now = datetime.now()
                # just starting, we consider beeing late on snapshots
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
                    path = snapshot(Arg(name=[name]), test=test)
                    SCHEDULE_LOG[action][name] = now
                    logger.info("Successfully snapshotted to %s", path)
            except Exception as e:
                logger.error('Error processing scheduler action file %s '
                             'name=%s, action=%s, timer=%s\n%s',
                             config, name, action, timer, str(e))
    # schedule the next run
    if not test:  # run only once
        Timer(TIMER, scheduler).start()


def run(args):
    # run a thread for the scheduled snapshots
    Timer(TIMER, scheduler).start()
    # listen to requests
    serve(app, unix_socket=SOCKET)


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

    parser_snapshot.set_defaults(func=snapshot)
    parser_snapshots.set_defaults(func=snapshots)
    parser_run.set_defaults(func=run)

    args = parser.parse_args()
    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()
