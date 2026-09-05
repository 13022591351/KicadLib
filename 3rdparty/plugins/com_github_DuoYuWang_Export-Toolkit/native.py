"""Native KiCad exporters, with small KiCad 10 capability checks."""
import json
import os
import shutil
import subprocess
from pathlib import Path

from .project import kicad_config_home
from .errors import ExportError
from .worksheets import VCS_ALIASES


def run_process(args, *, heartbeat=None, **kwargs):
    if heartbeat is None:
        return subprocess.run(args, **kwargs)
    kwargs.pop('capture_output', None)
    timeout = kwargs.pop('timeout', None)
    import time
    started = time.monotonic()
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs) as process:
        try:
            while True:
                try:
                    stdout, stderr = process.communicate(timeout=0.1)
                    return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    heartbeat()
                    if timeout is not None and time.monotonic() - started >= timeout:
                        raise
        except BaseException:
            process.kill()
            process.communicate()
            raise


def english_environment(directory):
    """Use English CLI messages with a private copy of the user's KiCad settings."""
    directory = Path(directory).resolve()
    source = kicad_config_home() / '10.0'
    destination = directory / '10.0'
    if source.is_dir():
        # Preserve path variables, library tables, color themes and plot settings.
        # Copy symlink targets too, so the CLI cannot write back to user settings.
        shutil.copytree(source, destination)
    else:
        destination.mkdir(parents=True)
    common = destination / 'kicad_common.json'
    settings = json.loads(common.read_text(encoding='utf-8')) if common.exists() else {}
    # KiCad's saved language takes precedence over LANG/LC_ALL.
    settings.setdefault('system', {})['language'] = 'English'
    common.write_text(json.dumps(settings, indent=2) + '\n', encoding='utf-8')
    return {'KICAD_CONFIG_HOME': str(directory), 'LANGUAGE': 'en'}


class Native:
    def __init__(self, executable, project, log=print, *, env=None, heartbeat=None):
        self.executable = executable
        self.project = project
        self.log = log
        self.heartbeat = heartbeat
        self._help = {}
        self.env = os.environ.copy()
        # KiCad's saved path variables must also be available to a headless worker.
        self.env.update({k: str(v) for k, v in project.variables.items()
                         if k.startswith('KICAD') or k == 'SPICE_LIB_DIR'})
        self.env.update(env or {})

    def _invoke(self, command, args, **kwargs):
        try:
            return run_process([self.executable, *command, *map(str, args)], heartbeat=self.heartbeat,
                               env=self.env, text=True, capture_output=True, **kwargs)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ExportError(f'Cannot run KiCad {" ".join(command)}: {exc}') from exc

    def run(self, command, args, cwd=None):
        key = tuple(command)
        if key not in self._help:
            help_result = self._invoke(command, ['--help'], timeout=30)
            help_text = help_result.stdout + help_result.stderr
            if help_result.returncode:
                raise ExportError(f'Cannot read KiCad {" ".join(command)} options:\n{help_text}')
            self._help[key] = help_text
        for arg in args:
            if str(arg).startswith('--') and str(arg) not in self._help[key]:
                raise ExportError(f'This KiCad build lacks {" ".join(command)} {arg}. '
                                   'Please use a KiCad 10 build that provides this native option.')
        self.log('KiCad: ' + ' '.join(command))
        result = self._invoke(command, args, cwd=cwd)
        output = (result.stdout + result.stderr).strip()
        if output:
            self.log(output)
        if result.returncode:
            raise ExportError(f'KiCad {" ".join(command)} failed ({result.returncode}):\n{output}')
        return output

    def definitions(self):
        args = ['--define-var', f'PROJECTNAME={self.project.variables["PROJECTNAME"]}']
        # Native VCSHASH/VCSSHORTHASH take precedence over --define-var in
        # KiCad 10. Export worksheets use ordinary variables instead.
        for builtin, alias in VCS_ALIASES.items():
            args += ['--define-var', f'{alias}={self.project.variables[builtin]}']
        return args

    def pdf(self, board, destination, layers, *, fab=False, mirror=False, worksheet=None,
            common_layers=None):
        args = ['--output', destination, '--layers', ','.join(layers),
                '--mode-single' if fab else '--mode-multipage',
                '--drill-shape-opt', '2', '--crossout-DNP-footprints-on-fab-layers']
        if fab:
            args += ['--black-and-white', '--scale', '0']
        else:
            common = ['Edge.Cuts'] if common_layers is None else common_layers
            args += ['--common-layers', ','.join(common), '--include-border-title', '--scale', '1']
            if worksheet:
                args += ['--drawing-sheet', worksheet]
        if mirror:
            args += ['--mirror']
        self.run(['pcb', 'export', 'pdf'], [*args, *self.definitions(), board])
        # Some KiCad 10 builds interpret multipage --output as a directory.
        # Relocate the one native PDF, without modifying or rendering its contents.
        destination = Path(destination)
        if destination.is_dir():
            files = list(destination.glob('*.pdf'))
            if len(files) != 1:
                raise ExportError(f'Expected one native PDF in {destination}; got {len(files)}')
            moved = destination.with_name(destination.name + '.native')
            files[0].rename(moved)
            destination.rmdir()
            moved.rename(destination)
        require_file(destination)


def require_file(path):
    path = Path(path)
    if not path.is_file() or not path.stat().st_size:
        raise ExportError(f'KiCad did not produce a non-empty output: {path}')


def archive(sevenzip, source, destination, log=print, *, heartbeat=None):
    if not any(Path(source).iterdir()):
        raise ExportError(f'Cannot archive empty directory: {source}')
    for args in ([sevenzip, 'a', '-t7z', '-mx=5', '-y', str(destination), '.'],
                 [sevenzip, 't', str(destination)]):
        result = run_process(args, heartbeat=heartbeat, cwd=source, text=True, capture_output=True)
        if result.returncode:
            raise ExportError(f'7z failed ({result.returncode}):\n{result.stdout}\n{result.stderr}')
    require_file(destination)
    log(f'Archive verified: {Path(destination).name}')
