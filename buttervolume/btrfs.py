from subprocess import run as _run, PIPE


def run(cmd):
    return _run(cmd, shell=True, check=True, stdout=PIPE).stdout.decode()


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

    def snapshot(self, target, readonly=False):
        r = '-r' if readonly else ''
        return run('btrfs subvolume snapshot {} "{}" "{}"'
                   .format(r, self.path, target))

    def create(self):
        return run('btrfs subvolume create "{}"'.format(self.path))

    def delete(self):
        return run('btrfs subvolume delete "{}"'.format(self.path))


class Filesystem(object):
    def __init__(self, path):
        self.path = path

    def label(self, label=None):
        if label is None:
            return run('btrfs filesystem label "{}"'.format(self.path))
        else:
            return run('btrfs filesystem label "{}" "{}"'
                       .format(self.path, label))
