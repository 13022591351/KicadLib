"""GUI/CLI shared production workflow. All design exporters belong to KiCad."""
import os
import shutil

from .boards import board_content, check_models, manufacturing_layers
from .config import OUTPUT_OPTIONS, VERSION, load_last_check
from .dependencies import check_dependencies
from .errors import ExportError
from .exports import ExportJobs
from .native import Native, english_environment
from .release import NOTES_FILE, load_notes, write_notes, sha256, save_user_notes
from .workspace import project_workspace


def publish(staged, target):
    """Delete the old version only after the entire staged release is ready."""
    if target.is_symlink():
        raise ExportError(f'Refusing to replace a symlink: {target}')
    if target.exists() and not target.is_dir():
        raise ExportError(f'Release target is not a directory: {target}')
    if target.exists():
        shutil.rmtree(target)
    os.rename(staged, target)


def export_project(project, options, notes=None, log=print, board=None, report=None, heartbeat=None):
    tools = check_dependencies()
    if not any(options[k] for k in OUTPUT_OPTIONS):
        raise ExportError('Select at least one export output.')
    import pcbnew
    output = project.file.parent / 'Export'
    if output.is_symlink():
        raise ExportError(f'Export directory must not be a symlink: {output}')
    output.mkdir(exist_ok=True)
    target = project.release_dir
    if target.is_symlink():
        raise ExportError(f'Release target must not be a symlink: {target}')
    report = report if report is not None else {}
    report.update(schema_version=1, success=False, project=project.name,
                  pcb_revision=project.pcb_revision, schematic_revision=project.sch_revision,
                  plugin_version=VERSION, kicad_version=tools['kicad_version'],
                  git_commit=project.commit, options=dict(options), warnings=[], outputs=[])
    warnings = report['warnings']
    def warn(message):
        warnings.append(message)
        log('WARNING: ' + message)

    def warn_mpn(message):
        warn(message)
        if options['strict']:
            raise ExportError(message)
    if notes is None:
        notes = load_notes(project.file.parent)
        if not (project.file.parent / NOTES_FILE).exists():
            save_user_notes(project.file.parent, '')
    with project_workspace(project.file, log) as work:
        release = work / 'release'
        release.mkdir()
        board = load_saved_board(project, board)
        log(f'Export-Toolkit {VERSION}; KiCad {tools["kicad_version"]}')
        log(f'Project: {project.name}; PCB Rev: {project.pcb_revision}; SCH Rev: {project.sch_revision}')
        native = Native(tools['kicad_cli'], project, log,
                        env=english_environment(work / 'kicad-config'), heartbeat=heartbeat)
        report['last_check_success_at'] = load_last_check(project.file.parent)
        log('Exporting saved inputs with existing zone fills. No checks, refill or PCB save.')
        if options['step_lite'] or options['step_full']:
            check_models(board, project, warn=warn)
        outline = [pcbnew.Edge_Cuts]
        if options['pcb_package'] or options['pcb_pdf']:
            outline = manufacturing_layers(board, options['alternative_edge'], options['vcut'])
        jobs = ExportJobs(project, options, board, native, work, release, tools['sevenzip'],
                          log, warn_mpn, heartbeat)
        if options['pcb_package']:
            jobs.export_pcb_package(outline)
        if options['smt_package']:
            jobs.export_smt_package()
        if options['pcb_pdf']:
            jobs.export_pcb_pdf(outline)
        if options['schematic_pdf']:
            jobs.export_schematic_pdf()
        for kind in ('lite', 'full'):
            if options['step_' + kind]:
                jobs.export_step(kind)
        write_notes(release, project, notes, VERSION, tools['kicad_version'], report['last_check_success_at'])
        report['outputs'] = [{'name': p.name, 'bytes': p.stat().st_size, 'sha256': sha256(p)}
                             for p in sorted(release.iterdir()) if p.name != 'RELEASE_NOTES.md']
        log('All selected exports completed. Publishing the complete release.')
        publish(release, target)
        report.update(success=True, release_directory=str(target))
        log(f'Published: {target}')
        return target


def load_saved_board(project, editor_board=None):
    """Use saved original inputs and reject unsaved/stale editor contents."""
    import pcbnew
    board = pcbnew.LoadBoard(str(project.board))
    if not board:
        raise ExportError(f'Cannot load board: {project.board}')
    if editor_board is not None and board_content(editor_board) != board_content(board):
        raise ExportError('The PCB editor differs from the saved PCB. '
                          'Save your changes or reload an externally updated PCB before exporting.')
    raw_revision = board.GetTitleBlock().GetRevision().strip()
    if raw_revision != project.pcb_revision and '${' not in raw_revision:
        raise ExportError('Save the PCB Revision and reopen Export-Toolkit before exporting.')
    return board
