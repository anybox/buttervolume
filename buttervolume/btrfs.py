import os
from subprocess import run as _run, PIPE


def run(cmd, shell=True, check=True, stdout=PIPE, stderr=PIPE):
    return _run(cmd, shell=shell, check=check, stdout=stdout,
                stderr=stderr).stdout.decode()


class Subvolume(object):
    """ basic wrapper around the CLI
    """
    def __init__(self, path):
        self.path = path

    def show(self):
        """somewhat hardcoded..."""
        raw = run('btrfs subvolume show "{}"'.format(self.path))
        output = {k.strip(): v.strip()
                  for k, v in [l.split(':', 1) for l in raw.split('\n')[1:12]]}
        assert(raw.split('\n')[12].strip() == 'Snapshot(s):')
        output['Snapshot(s)'] = [l.strip() for l in raw.split('\n')[13:]]
        return output

    def exists(self):
        if not os.path.exists(self.path):
            return False
        try:
            self.show()
        except:
            return False
        return True

    def snapshot(self, target, readonly=False):
        r = '-r' if readonly else ''
        return run('btrfs subvolume snapshot {} "{}" "{}"'
                   .format(r, self.path, target))

    def create(self, cow=False):
        out = run('btrfs subvolume create "{}"'.format(self.path))
        if not cow:
            run('chattr +C "{}"'.format(self.path))
        return out

    def delete(self, check=True):
        """

        :param check: if True, in case btrfs subvolume fails (exit code != 0)
                      an exception will raised
        :return: btrfs output string
        """
        return run('btrfs subvolume delete {}'.format(self.path), check=check)


class Filesystem(object):
    def __init__(self, path):
        self.path = path

    def label(self, label=None):
        if label is None:
            return run('btrfs filesystem label "{}"'.format(self.path))
        else:
            return run('btrfs filesystem label "{}" "{}"'
                       .format(self.path, label))
