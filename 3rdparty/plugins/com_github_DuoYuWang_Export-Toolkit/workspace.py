"""Project-specific temporary outputs; callers hold the project export lock."""
import fcntl
import shutil
from contextlib import contextmanager
from pathlib import Path

from .errors import ExportError


@contextmanager
def project_lock(project_file):
    """Protect configuration writes as well as checks and export publication."""
    output = Path(project_file).parent / 'Export'
    if output.is_symlink():
        raise ExportError(f'Export directory must not be a symlink: {output}')
    output.mkdir(exist_ok=True)
    with open(output / '.export-toolkit.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ExportError('Another Export-Toolkit job is running for this project.') from exc
        yield output


@contextmanager
def project_workspace(project_file, log=print):
    with project_lock(project_file) as output:
        with export_workspace(project_file, output, log) as work:
            yield work


def workspace_name(project_file):
    return f'Export-Toolkit-{Path(project_file).stem}-work'


@contextmanager
def export_workspace(project_file, output, log=print):
    """Clean this project's interrupted runs, then create a fresh output directory."""
    directory = output / workspace_name(project_file)
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        raise ExportError(f'Work directory must be a directory, not a symlink: {directory}')
    if directory.exists():
        log(f'Removing output from an interrupted job: {directory}')
        shutil.rmtree(directory)
    directory.mkdir()
    try:
        yield directory
    finally:
        try:
            shutil.rmtree(directory)
        except OSError as exc:
            # Cleanup must not undo a committed success or mask the original
            # export/cancellation exception. The next run retries this cleanup.
            log(f'WARNING: Temporary export files retained at {directory}: {exc}')
