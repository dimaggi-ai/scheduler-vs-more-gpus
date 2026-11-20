"""Stage output siblings and publish without overwrite; roll back ordinary errors.

Not a multi-file atomic transaction across process crashes. No files owned by
another run are deleted during rollback, even if a destination is replaced.
"""
import os
from pathlib import Path
import tempfile


def _identity(path):
    stat = os.lstat(path)
    return stat.st_dev, stat.st_ino


def _remove_owned(path, identity):
    try:
        if _identity(path) == identity:
            os.unlink(path)
    except FileNotFoundError:
        pass


def publish(outputs, input_path=None):
    outputs = [(Path(path).absolute(), content) for path, content in outputs if path]
    resolved = [path.resolve() for path, _ in outputs]
    if len(resolved) != len(set(resolved)) or (input_path and Path(input_path).resolve() in resolved):
        raise ValueError('output paths must be distinct and cannot overwrite the input')
    for path, _ in outputs:
        if not path.parent.is_dir():
            raise ValueError('output parent directory does not exist: ' + str(path.parent))
        if os.path.lexists(path):
            raise ValueError('output already exists; choose fresh evidence paths')
    staged, published = [], []
    try:
        for path, content in outputs:
            fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
            identity = _identity(temporary)
            staged.append((temporary, identity, path))
            with os.fdopen(fd, 'w') as out:
                out.write(content)
                out.flush()
                os.fsync(out.fileno())
        for temporary, identity, path in staged:
            # Hard-link creation is atomic and refuses an existing destination;
            # rename/replace would silently overwrite a concurrent creator.
            os.link(temporary, path)
            published.append((path, identity))
    except BaseException:
        for path, identity in reversed(published):
            _remove_owned(path, identity)
        raise
    finally:
        for temporary, identity, _ in staged:
            _remove_owned(temporary, identity)
