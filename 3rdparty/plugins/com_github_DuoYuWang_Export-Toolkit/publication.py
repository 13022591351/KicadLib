"""Recoverable release replacement; previous releases never live in work/."""
import os
import shutil

from .errors import ExportError


def previous_release(target):
    return target.with_name('.' + target.name + '.previous')


def check_directory(path):
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise ExportError(f'Release path must be a directory, not a symlink: {path}')


def recover_publication(target, log=print):
    """Called under the project lock, including after an interrupted rename."""
    backup = previous_release(target)
    check_directory(target)
    check_directory(backup)
    if backup.exists() and not target.exists():
        os.rename(backup, target)
        log(f'Restored previous release after interrupted publication: {target}')
    elif backup.exists():
        # Both names exist only after the new directory was committed. Failure
        # to remove the backup must not be reported as loss of the new release.
        try:
            shutil.rmtree(backup)
        except OSError as exc:
            log(f'WARNING: Previous release retained at {backup}: {exc}')


def publish(staged, target, log=print):
    recover_publication(target, log)
    backup = previous_release(target)
    if backup.exists():
        raise ExportError(f'Cannot replace release while its previous backup remains: {backup}')
    if target.exists():
        os.rename(target, backup)
    try:
        os.rename(staged, target)
    except BaseException:
        if backup.exists() and not target.exists():
            # If rollback also fails, the old release remains outside work/;
            # recovery at the next run will restore it before exporting.
            try:
                os.rename(backup, target)
            except OSError as exc:
                log(f'WARNING: Restore previous release from {backup}: {exc}')
        raise
    if backup.exists():
        try:
            shutil.rmtree(backup)
        except OSError as exc:
            log(f'WARNING: New release published; previous copy retained at {backup}: {exc}')
