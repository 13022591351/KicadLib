"""Read-only Git summaries for the project's tracked working files."""
import json
import os
import subprocess

from .native import run_process


def log_git_diff(directory, log=print, *, heartbeat=None):
    """Include staged and unstaged changes against HEAD, scoped to this project."""
    args = ['git', '-C', str(directory), '--no-pager', 'diff', '--numstat', '-z',
            '--no-renames', '--no-ext-diff', '--no-textconv', '--relative', 'HEAD', '--', '.']
    try:
        result = run_process(args, heartbeat=heartbeat, capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        log(f'Git diff unavailable: {exc}')
        return []
    if result.returncode:
        log('Git diff unavailable: no readable Git repository with a HEAD commit.')
        return []
    entries = []
    for row in result.stdout.split(b'\0'):
        if not row:
            continue
        added, deleted, name = row.split(b'\t', 2)
        entries.append({'file': os.fsdecode(name),
                        'added': None if added == b'-' else int(added),
                        'deleted': None if deleted == b'-' else int(deleted)})
    log('Git diff against HEAD (tracked files in this project, staged and unstaged):')
    if not entries:
        log('No tracked file changes.')
    for entry in entries:
        name = json.dumps(entry['file'], ensure_ascii=False)
        counts = ('binary' if entry['added'] is None else
                  f'+{entry["added"]}  -{entry["deleted"]}')
        log(f'  {name}  {counts}')
    return entries
