"""Read-only native ERC/parity/DRC; persist only the last successful check time."""
import json
import re
from datetime import datetime
from pathlib import Path

from .errors import ExportError
from .dependencies import check_dependencies
from .git_status import log_git_diff
from .config import load_options, save_options
from .native import Native, english_environment, require_file
from .workspace import project_workspace


def now():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def report_issues(data, kind):
    if kind == 'erc':
        return [issue for sheet in data['sheets'] for issue in sheet['violations']]
    if kind == 'sync':
        return data['schematic_parity']
    return [issue for section in ('violations', 'unconnected_items')
            for issue in data[section]]


def check_result(path, kind, report, log):
    require_file(path)
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise ExportError(f'KiCad produced an invalid {kind.upper()} JSON report: {exc}') from exc
    issues = report_issues(data, kind)
    # KiCad keeps the original severity on excluded findings and marks them
    # separately. Do not count those as active errors or warnings.
    active = [item for item in issues if not item.get('excluded', False)]
    errors = [item for item in active if item['severity'] == 'error']
    warnings = [item for item in active if item['severity'] == 'warning']
    report.setdefault('checks', {})[kind] = {'errors': len(errors), 'warnings': len(warnings),
                                            'excluded': len(issues) - len(active),
                                            'issues': issues}
    log(f'{kind.upper()}: {len(errors)} error(s), {len(warnings)} warning(s).')
    if errors:
        details = []
        for issue in errors:
            items = '; '.join(item.get('description', '') for item in issue.get('items', []))
            details.append(f'{issue["type"]}: {issue["description"]}' + (f' [{items}]' if items else ''))
        raise ExportError(f'{kind.upper()} failed:\n' + '\n'.join(details))


def run_checks(project, native, work, report, log):
    erc = work / 'erc.json'
    native.run(['sch', 'erc'], ['--format', 'json', '--severity-error', '--severity-warning',
                               '--output', erc, project.schematic])
    check_result(erc, 'erc', report, log)
    drc = work / 'drc.json'
    output = native.run(['pcb', 'drc'], ['--schematic-parity', '--format', 'json',
                        '--severity-error', '--severity-warning',
                        '--output', drc, project.board])
    # KiCad 10 can return zero and an empty parity list when netlist loading failed.
    # Require confirmation that the check actually ran, in the English CLI locale.
    if not re.search(r'Found\s+\d+\s+schematic parity issues', output):
        raise ExportError('KiCad could not complete schematic/PCB parity checking. '
                           'Save and fully annotate the schematic before checking.\n' + output)
    # Both results come from one native DRC run. Report parity first, without
    # pretending that KiCad ran a separate schematic-to-PCB update command.
    failures = []
    for kind in ('sync', 'drc'):
        try:
            check_result(drc, kind, report, log)
        except ExportError as exc:
            failures.append(str(exc))
    if failures:
        raise ExportError('\n'.join(failures))


def check_project(project, log=print, board=None, report=None, heartbeat=None,
                  editor_content=None, tools=None):
    """Run the standalone GUI/CLI action; never export or modify a release."""
    from .core import load_saved_board
    report = report if report is not None else {}
    report.update(schema_version=1, success=False, project=project.name, checks={},
                  last_check_success_at=None)
    with project_workspace(project.file, log) as work:
        # Invalidate history under the project lock before starting a new check.
        # Errors, incomplete parity checking and interrupted runs must not leave
        # an older success looking like the result of this attempt.
        options = load_options(project.file.parent)
        save_options(project.file.parent, options, last_check_success_at='')
        if tools is None:
            tools = check_dependencies(heartbeat=heartbeat, log=log)
        report['kicad_version'] = tools['kicad_version']
        load_saved_board(project, board, editor_content=editor_content, log=log, heartbeat=heartbeat)
        native = Native(tools['kicad_cli'], project, log,
                        env=english_environment(work / 'kicad-config'), heartbeat=heartbeat)
        try:
            log('Checking saved inputs with existing zone fills. No zone refill or PCB save.')
            run_checks(project, native, work, report, log)
            last_check = now()
            options = load_options(project.file.parent)
            save_options(project.file.parent, options, last_check_success_at=last_check)
            report.update(success=True, last_check_success_at=last_check)
        finally:
            report['git_diff'] = log_git_diff(project.file.parent, log, heartbeat=heartbeat)
    log('ERC, schematic parity and DRC have no active errors. Check time recorded; design files unchanged.')
    return report
