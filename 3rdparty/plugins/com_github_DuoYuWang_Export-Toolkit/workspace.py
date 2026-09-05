"""Project-specific temporary outputs; callers hold the project export lock."""
import hashlib
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path


def workspace_prefix(project_file):
    identity = hashlib.sha256(os.fsencode(Path(project_file).resolve())).hexdigest()[:20]
    return f'export-toolkit-{os.getuid()}-{identity}-'


@contextmanager
def export_workspace(project_file, output, log=print):
    """Clean this project's interrupted runs, then create a fresh output directory."""
    prefix = workspace_prefix(project_file)
    candidates = list(Path(tempfile.gettempdir()).glob(prefix + '*'))
    # Completed outputs may have been staged here for a cross-filesystem move.
    candidates += list(output.glob('.export-toolkit-publish-*'))
    for path in candidates:
        if path.is_symlink() or not path.is_dir():
            continue
        log(f'Removing temporary output from an interrupted export: {path}')
        shutil.rmtree(path)
    with tempfile.TemporaryDirectory(prefix=prefix) as directory:
        yield Path(directory)
