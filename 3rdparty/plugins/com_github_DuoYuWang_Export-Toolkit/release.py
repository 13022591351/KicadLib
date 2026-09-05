"""Editable release notes and checksums of final delivered files."""
import hashlib
import os
import tempfile
from datetime import datetime

from .config import last_check_label

NOTES_FILE = 'RELEASE_NOTES.md'
START = '<!-- export-toolkit:notes:start -->'
END = '<!-- export-toolkit:notes:end -->'
CHANGES = "\n## What's Changed\n"
LEGACY_CHANGES = '\n## Changes\n'
CHECKSUMS = '\n## File Checksums — SHA-256\n'


def load_notes(directory):
    path = directory / NOTES_FILE
    if not path.exists():
        return ''
    return extract_notes(path.read_text(encoding='utf-8'))


def extract_notes(text):
    """Only the Changes body is user input; header/checksums are never reused."""
    if START in text and END in text:
        return text.split(START, 1)[1].split(END, 1)[0].strip('\n')
    for heading in (CHANGES, LEGACY_CHANGES):
        if heading in text and CHECKSUMS in text:
            return text.split(heading, 1)[1].rsplit(CHECKSUMS, 1)[0].strip('\n')
    # Preserve manually created notes, too.
    return text


def save_user_notes(directory, text):
    """The project file contains only user-maintained change text."""
    path = directory / NOTES_FILE
    fd, tmp = tempfile.mkstemp(prefix='.release-notes-', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
        os.replace(tmp, path)
    finally:
        from pathlib import Path
        Path(tmp).unlink(missing_ok=True)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def write_notes(directory, project, notes, version, kicad_version, last_check=None):
    lines = ['# Release Notes', '', f'- Project: {project.name}',
             f'- Schematic Revision: {project.sch_revision}', f'- PCB Revision: {project.pcb_revision}',
             f'- Generated At: {datetime.now().astimezone().isoformat(timespec="seconds")}',
             f'- Export-Toolkit: {version}', f'- KiCad: {kicad_version}',
             f'- Git Commit: {project.commit or "Unavailable"}',
             f'- {last_check_label(last_check)}',
             '', "## What's Changed", '',
             notes.rstrip(), '', '## File Checksums — SHA-256', '',
             '| File | SHA-256 |', '| --- | --- |']
    for path in sorted(directory.iterdir()):
        if path.name != NOTES_FILE and path.is_file():
            escaped_name = path.name.replace('|', '\\|')
            lines.append(f'| {escaped_name} | `{sha256(path)}` |')
    (directory / NOTES_FILE).write_text('\n'.join(lines) + '\n', encoding='utf-8')
