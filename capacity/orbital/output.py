"""Stage output siblings and publish without overwrite; roll back ordinary errors.

Not a multi-file atomic transaction across process crashes. Rollback never
unlinks a path it has not identified as this run's file. It first checks the
identity at the path and leaves a path that no longer holds this run's file.
Otherwise it renames the path into a private `.rollback` directory, checks the
identity again there and unlinks only on a match. A foreign file that replaced
a destination between the two checks is linked back without overwrite. If that
fails, it stays in the `.rollback` directory and the error names it.
"""
import os
from pathlib import Path
import tempfile


def _identity(path):
    stat = os.lstat(path)
    return stat.st_dev, stat.st_ino


def _remove_owned(path, identity):
    # There is no unlink-if-identity call. Checking a path and then unlinking
    # the same path can delete a file that replaced it between the two calls.
    path = Path(path)
    try:
        if _identity(path) != identity:
            return
    except FileNotFoundError:
        return
    holder = Path(tempfile.mkdtemp(prefix='.' + path.name + '.', suffix='.rollback', dir=path.parent))
    aside = holder / path.name
    try:
        try:
            os.rename(path, aside)
        except FileNotFoundError:
            return
        if _identity(aside) == identity:
            os.unlink(aside)
            return
        try:
            os.link(aside, path, follow_symlinks=False)
        except OSError as exc:
            raise OSError('rollback moved a file this run does not own and could not put it back; '
                          'it is preserved at ' + str(aside)) from exc
        os.unlink(aside)
    finally:
        try:
            os.rmdir(holder)
        except OSError:
            pass  # not empty: it holds a preserved foreign file


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
    staged, published, errors = [], [], []

    def remove(path, identity):
        # One entry that cannot be rolled back must not stop the others.
        try:
            _remove_owned(path, identity)
        except OSError as exc:
            errors.append(exc)

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
            # A filesystem without hard links raises OSError here: the run is
            # refused and rolled back (see README).
            os.link(temporary, path)
            published.append((path, identity))
    except BaseException:
        for path, identity in reversed(published):
            remove(path, identity)
        raise
    finally:
        for temporary, identity, _ in staged:
            remove(temporary, identity)
        if errors:
            raise OSError('; '.join(str(exc) for exc in errors))
