"""Run with KiCad's Python: python3 /path/to/Export-Toolkit/cli.py export ..."""
import argparse
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

# Direct script execution works without pip installation or a PYTHONPATH change.
# Do not execute the KiCad registration entry point when loading the CLI package.
if not __package__:
    package_name = '_export_toolkit'
    spec = importlib.util.spec_from_loader(package_name, loader=None, is_package=True)
    package = importlib.util.module_from_spec(spec)
    package.__path__ = [str(Path(__file__).resolve().parent)]
    sys.modules[package_name] = package
    __package__ = package_name

from .config import DEFAULTS, VERSION, load_options, save_options
from .dependencies import check_dependencies
from .errors import ExportError, log_exception
from .project import Project
from .release import extract_notes


def check_report_destination(path):
    if path is None:
        return
    if path.exists() and not path.is_file():
        raise ExportError(f'JSON report output must be a file: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.export-toolkit-report-', dir=path.parent)
    os.close(fd)
    Path(temporary).unlink()


def write_report(path, report):
    """Replace the previous report, including read-only files in writable directories."""
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.export-toolkit-report-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='Export-Toolkit', description='Native KiCad 10 production exports')
    parser.add_argument('--version', action='version', version=VERSION)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('check', help='Check runtime libraries and native tools')
    export = sub.add_parser('export', help='Export the project to Export/<project>-<SCHRev>/')
    export.add_argument('--project', required=True, type=Path)
    export.add_argument('--board', type=Path)
    export.add_argument('--schematic', type=Path, help='First/root schematic; its Revision supplies SCHRev')
    export.add_argument('--config', type=Path, help='Defaults to export-toolkit-options.json in the project')
    export.add_argument('--release-notes-file', type=Path, help='UTF-8 release notes body; omitted preserves existing notes')
    export.add_argument('--save-options', action='store_true', help='Persist the effective options to JSON')
    export.add_argument('--report', type=Path, help='Write a machine-readable JSON result for CI / review tools')
    for key, value in DEFAULTS.items():
        if isinstance(value, bool):
            export.add_argument('--' + key.replace('_', '-'), action=argparse.BooleanOptionalAction, default=None)
        else:
            export.add_argument('--' + key.replace('_', '-'), default=None)
    args = parser.parse_args(argv)
    report = {'schema_version': 1, 'success': False}
    def save_report():
        write_report(getattr(args, 'report', None), report)
    def log_error(exc, result=None):
        log_exception(exc, lambda message: print(message, file=sys.stderr), result)
    try:
        tools = check_dependencies()
        if args.command == 'check':
            for key, value in tools.items():
                print(f'{key}: {value}')
            return 0
        check_report_destination(args.report)
        from .core import export_project
        project = Project.open(args.project, args.board, args.schematic)
        options = load_options(project.file.parent, args.config)
        for key in DEFAULTS:
            value = getattr(args, key)
            if value is not None:
                options[key] = value
        if args.save_options:
            save_options(project.file.parent, options, args.config)
        notes = extract_notes(args.release_notes_file.read_text(encoding='utf-8')) if args.release_notes_file else None
        export_project(project, options, notes, report=report)
        save_report()
        return 0
    except KeyboardInterrupt:
        report.update(success=False, error='Export cancelled.')
        try:
            save_report()
        except Exception as exc:
            log_error(exc)
        print('Export cancelled.', file=sys.stderr)
        return 130
    except Exception as exc:
        log_error(exc, report)
        try:
            save_report()
        except Exception as report_error:
            log_error(report_error)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
