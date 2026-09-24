"""GUI/CLI shared production workflow. All design exporters belong to KiCad."""
import math

from .boards import board_content, check_models, manufacturing_layers
from .config import DEFAULTS, VERSION, load_last_check, pcba_enabled, has_outputs
from .dependencies import check_dependencies
from .errors import ExportError
from .exports import ExportJobs
from .native import Native, english_environment, pdf_merge_tool
from .release import load_notes, write_notes, sha256
from .workspace import project_workspace
from .publication import publish, recover_publication
from .inputs import InputGuard
from .pdf_fonts import pdf_font_library
from .pdf_outlines import pdf_outline_library
from .git_status import log_git_diff
from .progress import prepare


def export_project(project, options, notes=None, log=print, board=None, report=None, heartbeat=None,
                   step_timeout=1800, persist=None, editor_content=None, tools=None):
    log('Preparing: Export requested; validating saved inputs.')
    if heartbeat:
        heartbeat()
    if not math.isfinite(step_timeout) or step_timeout <= 0:
        raise ExportError('STEP timeout must be greater than zero seconds.')
    if tools is None:
        tools = check_dependencies(heartbeat=heartbeat, log=log)
    if not has_outputs(options):
        raise ExportError('Select at least one export output.')
    if options['pcb_pdf'] or pcba_enabled(options):
        pdf_merge_tool()
    if (options['pcb_pdf'] or pcba_enabled(options) or options['schematic_pdf']
            or (options['smt_package'] and options['fab_pdf'])):
        if options.get('pdf_text_outlines', DEFAULTS['pdf_text_outlines']):
            pdf_outline_library()
        else:
            pdf_font_library()
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
    def workspace_log(message):
        if message.startswith('WARNING: '):
            warn(message.removeprefix('WARNING: '))
        else:
            log(message)

    with project_workspace(project.file, workspace_log) as work:
        if persist:
            prepare('Saving export preferences', persist, log, heartbeat)
        report['last_check_success_at'] = load_last_check(project.file.parent)
        if not report['last_check_success_at']:
            warn('No successful ERC/DRC check time recorded. Continuing export without running checks.')
        prepare('Recovering interrupted publication',
                lambda: recover_publication(target, workspace_log), log, heartbeat)
        guard = prepare('Fingerprinting source inputs',
                        lambda: InputGuard(project, heartbeat), log, heartbeat)
        # Refresh metadata inside the guarded interval, not from a stale dialog.
        project = prepare('Reading project metadata', lambda: type(project).open(
            project.file, project.board, project.schematic, heartbeat=heartbeat), log, heartbeat)
        if project.release_dir != target:
            raise ExportError('Project revision changed; reopen export and retry.')
        guard.project = project
        prepare('Verifying source inputs', guard.verify, log, heartbeat)
        if notes is None:
            notes = load_notes(project.file.parent)
        report.update(pcb_revision=project.pcb_revision, schematic_revision=project.sch_revision,
                      git_commit=project.commit, step_timeout_seconds=step_timeout)
        release = work / 'release'
        release.mkdir()
        report['git_diff'] = prepare('Reading Git changes', lambda: log_git_diff(
            project.file.parent, log, heartbeat=heartbeat), log, heartbeat)
        board = load_saved_board(project, board, editor_content=editor_content,
                                 log=log, heartbeat=heartbeat)
        log(f'Export-Toolkit {VERSION}; KiCad {tools["kicad_version"]}')
        log(f'Project: {project.name}; PCB Rev: {project.pcb_revision}; SCH Rev: {project.sch_revision}')
        environment = prepare('Copying private KiCad settings',
                              lambda: english_environment(work / 'kicad-config'), log, heartbeat)
        native = Native(tools['kicad_cli'], project, log,
                        env=environment, heartbeat=heartbeat,
                        step_timeout=step_timeout)
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
        if pcba_enabled(options):
            jobs.export_pcba_pdf()
        if options['schematic_pdf']:
            jobs.export_schematic_pdf()
        for kind in ('lite', 'full'):
            if options['step_' + kind]:
                jobs.export_step(kind)
        prepare('Verifying source inputs after export', guard.verify, log, heartbeat)
        write_notes(release, project, notes, VERSION, tools['kicad_version'], report['last_check_success_at'])
        report['outputs'] = [{'name': p.name, 'bytes': p.stat().st_size, 'sha256': sha256(p)}
                             for p in sorted(release.iterdir()) if p.name != 'RELEASE_NOTES.md']
        log('All selected exports completed. Publishing the complete release.')
        if heartbeat:
            heartbeat()
        guard.verify()
        publish(release, target, log)
        report.update(success=True, release_directory=str(target))
        log(f'Published: {target}')
        return target


def load_saved_board(project, editor_board=None, *, editor_content=None, log=print, heartbeat=None):
    """Use saved original inputs and reject unsaved/stale editor contents."""
    import pcbnew
    board = prepare('Loading saved PCB', lambda: pcbnew.LoadBoard(str(project.board)), log, heartbeat)
    if not board:
        raise ExportError(f'Cannot load board: {project.board}')
    if editor_board is not None:
        if editor_content is None:
            editor_content = prepare('Reading editor PCB content',
                                     lambda: board_content(editor_board, heartbeat), log, heartbeat)
        # In the editor pcbnew.LoadBoard may return the already-open board.
        # Compare with a genuine disk read, never the editor against itself.
        disk_board = prepare('Reading saved PCB for comparison',
                             lambda: pcbnew.PCB_IO_KICAD_SEXPR().LoadBoard(str(project.board), None),
                             log, heartbeat)
        if not disk_board:
            raise ExportError('Cannot read the saved PCB for comparison.')
        saved_content = prepare('Comparing saved PCB content',
                                lambda: board_content(disk_board, heartbeat), log, heartbeat)
        if editor_content != saved_content:
            raise ExportError('The PCB editor differs from the saved PCB. '
                              'Save your changes or reload an externally updated PCB before exporting.')
    raw_revision = board.GetTitleBlock().GetRevision().strip()
    if raw_revision != project.pcb_revision and '${' not in raw_revision:
        raise ExportError('Save the PCB Revision and reopen Export-Toolkit before exporting.')
    return board
