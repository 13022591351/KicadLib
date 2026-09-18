"""Read-only fingerprints of design inputs; reject mixed-version releases."""
import os
from pathlib import Path

from .errors import ExportError
from .project import read_tree, children
from .release import sha256

SUFFIXES = {'.kicad_pcb', '.kicad_pro', '.kicad_sch', '.kicad_dru', '.kicad_prl'}


def input_paths(project):
    paths = {project.file, project.board, project.schematic}
    for directory, folders, files in os.walk(project.file.parent):
        folders[:] = [name for name in folders if name not in ('Export', '.git')]
        paths.update(Path(directory) / name for name in files
                     if Path(name).suffix in SUFFIXES and not name.startswith('_autosave-'))
    # KiCad can create/update/remove autosave siblings while exporting even
    # when the saved design is unchanged. They are not exporter inputs. Filter
    # only directory discovery: explicitly selected or referenced inputs below
    # must remain guarded even if their names happen to use this prefix.
    paths.update(project.file.parent / name for name in
                 ('export-toolkit-options.json', 'RELEASE_NOTES.md'))
    # Follow external hierarchical sheets too, with cycle detection. The
    # project remains the base for KIPRJMOD; plain relative paths follow sheets.
    pending = [project.schematic]
    visited = set()
    while pending:
        schematic = pending.pop().resolve()
        if schematic in visited:
            continue
        visited.add(schematic)
        paths.add(schematic)
        for sheet in children(read_tree(schematic), 'sheet'):
            for prop in children(sheet, 'property'):
                if len(prop) > 2 and prop[1].lower() == 'sheetfile':
                    pending.append(project.expand_path(prop[2], schematic.parent))
    for kind in ('pcb', 'sch'):
        worksheet = project.worksheet(kind)
        if worksheet is not None:
            paths.add(worksheet)
    return sorted({p.resolve() for p in paths})


def fingerprint(project):
    return {str(path): sha256(path) if path.is_file() else None
            for path in input_paths(project)}


class InputGuard:
    def __init__(self, project):
        self.project = project
        self.before = fingerprint(project)

    def verify(self):
        try:
            after = fingerprint(self.project)
        except (OSError, ValueError, ExportError) as exc:
            raise ExportError(f'Cannot verify source inputs; release not published: {exc}') from exc
        changed = [path for path in sorted(self.before.keys() | after.keys())
                   if path not in self.before or path not in after
                   or self.before.get(path) != after.get(path)]
        if changed:
            raise ExportError('Source inputs changed during export; release not published. '
                              'Save the design and rerun export:\n' + '\n'.join(changed))
