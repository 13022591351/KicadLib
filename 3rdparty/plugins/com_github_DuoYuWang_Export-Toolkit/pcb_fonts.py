"""In-memory PCB font edits through KiCad; only explicit overrides are logged.

No schematic, project, worksheet or library text is rewritten by this action.
"""
import json
from pathlib import Path
import subprocess
from .errors import ExportError
from .native import run_process
from .workspace import project_lock


def installed_font(name, heartbeat=None):
    name = name.strip()
    if not name or any(ord(c) < 32 for c in name):
        raise ExportError('Enter a non-empty font family name without control characters.')
    if name == 'KiCad Font':
        return name
    try:
        result = run_process(['fc-list', '--format=%{family}\n'], text=True,
                             timeout=15, heartbeat=heartbeat)
        result.check_returncode()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ExportError(f'Cannot enumerate installed fonts (fontconfig/fc-list required): {exc}') from exc
    families = {value.strip().casefold() for line in result.stdout.splitlines()
                for value in line.split(',')}
    if name.casefold() not in families:
        raise ExportError(f'Font is not installed: {name}. No PCB changes made.')
    return name


def text_items(board):
    """Include hidden fields, all layers, dimensions and native table cells."""
    def visit(item, owner='Board'):
        if hasattr(item, 'SetFontProp'):
            yield item, owner
        if hasattr(item, 'GetCells'):
            try:
                cells = list(item.GetCells())
            except TypeError as exc:
                raise ExportError('This KiCad Python build does not expose table cells; '
                                  'no PCB fonts have been changed.') from exc
            for cell in cells:
                if not hasattr(cell, 'SetFontProp'):
                    raise ExportError('This KiCad Python build cannot edit table-cell fonts; '
                                      'no PCB fonts have been changed.')
                yield from visit(cell, owner + '/table')
    for item in board.GetDrawings():
        yield from visit(item)
    for footprint in board.GetFootprints():
        owner = footprint.GetReference()
        for item in footprint.GetFields():
            yield from visit(item, owner)
        for item in footprint.GraphicalItems():
            yield from visit(item, owner)


def plan_fonts(board, name, replace_all=False):
    changes, details = [], []
    target = '' if name == 'KiCad Font' else name
    for item, owner in text_items(board):
        old = item.GetFontName()
        if (not old or replace_all) and old != target:
            changes.append((item, item.GetFontProp()))
            if old:
                details.append(dict(owner=owner, layer=board.GetLayerName(item.GetLayer()),
                                    text=item.GetText(), before=old, after=name))
    return changes, details


def apply_changes(changes, name):
    try:
        for item, _ in changes:
            item.SetFontProp(name)
    except BaseException:
        restore_changes(changes)
        raise


def restore_changes(changes):
    for item, previous in changes:
        item.SetFontProp(previous)


def set_pcb_fonts(project, name, replace_all=False, *, editor_board=None,
                  log=print, heartbeat=None, persist=None):
    """Edit the current board, including existing unsaved edits; never save it.

    The GUI remains inside the native action-plugin Run() until its modal dialog
    closes, allowing KiCad to record the normal undo/modified state. Preferences
    may be cached, but no design, backup or report files are created here.
    """
    if editor_board is None:
        raise ExportError('PCB font changes require the current editor board.')
    if Path(editor_board.GetFileName()).resolve() != project.board.resolve():
        raise ExportError('The editor is not displaying the selected PCB.')
    name = installed_font(name, heartbeat)
    with project_lock(project.file):
        if persist:
            persist()
        changes, details = plan_fonts(editor_board, name, replace_all)
        if heartbeat:
            heartbeat()
        if not changes:
            return dict(changed=0, overwritten=0, changes=[], saved=False)
        # Apply as a single non-yielding operation, rolling back setters on error.
        apply_changes(changes, name)
        try:
            editor_board.SetModified()
        except BaseException:
            restore_changes(changes)
            raise
        if details:
            log('\n'.join('Fonts: overwritten ' + json.dumps(row, ensure_ascii=False) for row in details))
        return dict(changed=len(changes), overwritten=len(details), changes=details, saved=False)
