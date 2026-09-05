"""Native ERC, then DRC with schematic parity, before any production export."""
import json
import re
from pathlib import Path

from .native import require_file
from .errors import ExportError


def report_issues(data, kind):
    if kind == 'erc':
        return [issue for sheet in data['sheets'] for issue in sheet['violations']]
    return [issue for section in ('violations', 'unconnected_items', 'schematic_parity')
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
        raise ExportError(f'{kind.upper()} failed. Fix the errors before exporting:\n' + '\n'.join(details))


def run_checks(project, native, work, report, log, *, refill=False):
    # Native parity resolves these beside the input PCB. Fail rather than check
    # a different root sheet or use different project rules for an explicit path.
    if (project.board.with_suffix('.kicad_pro').resolve() != project.file.resolve()
            or project.board.with_suffix('.kicad_sch').resolve() != project.schematic.resolve()):
        raise ExportError('Native DRC requires the PCB, project and root schematic '
                         'to share a directory and filename stem.')
    erc = work / 'erc.json'
    native.run(['sch', 'erc'], ['--format', 'json', '--severity-error', '--severity-warning',
                               '--output', erc, project.schematic])
    check_result(erc, 'erc', report, log)
    drc = work / 'drc.json'
    refill_args = ['--refill-zones', '--save-board'] if refill else []
    if refill:
        log('DRC will refill zones and save the PCB before export.')
    output = native.run(['pcb', 'drc'], ['--schematic-parity', '--format', 'json',
                        '--severity-error', '--severity-warning', *refill_args,
                        '--output', drc, project.board])
    if refill:
        report['zones_refilled'] = True
        report['board_saved'] = True
    # KiCad 10 can return zero and an empty parity list when netlist loading failed.
    # Require confirmation that the check actually ran, in the English CLI locale.
    if not re.search(r'Found\s+\d+\s+schematic parity issues', output):
        raise ExportError('KiCad could not complete schematic/PCB parity checking. '
                           'Save and fully annotate the schematic before exporting.\n' + output)
    check_result(drc, 'drc', report, log)
