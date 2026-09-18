"""Native KiCad exporters, with small KiCad 10 capability checks."""
import json
import codecs
import os
import re
import selectors
import signal
import shutil
import subprocess
import time
from pathlib import Path

from .project import kicad_config_home
from .errors import ExportError
from .worksheets import VCS_ALIASES


def run_process(args, *, heartbeat=None, on_output=None, on_status=None, **kwargs):
    """Drain both pipes while yielding to GUI cancellation and enforcing limits."""
    kwargs.pop('capture_output', None)
    timeout = kwargs.pop('timeout', None)
    text_mode = kwargs.pop('text', False)
    encoding = kwargs.pop('encoding', 'utf-8')
    errors = kwargs.pop('errors', 'replace')
    started = time.monotonic()
    last_output = started
    next_status = started + 30
    captured = {'stdout': [], 'stderr': []}
    decoders = {name: codecs.getincrementaldecoder(encoding)(errors=errors) for name in captured}
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          start_new_session=True, **kwargs) as process:
        selector = selectors.DefaultSelector()
        try:
            for name in captured:
                pipe = getattr(process, name)
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, name)
            while selector.get_map() or process.poll() is None:
                if heartbeat:
                    heartbeat()
                now = time.monotonic()
                if timeout is not None and now - started >= timeout:
                    raise subprocess.TimeoutExpired(args, timeout,
                                                    b''.join(captured['stdout']), b''.join(captured['stderr']))
                for key, _ in selector.select(timeout=0.1):
                    data = os.read(key.fileobj.fileno(), 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                        decoded = decoders[key.data].decode(b'', final=True)
                    else:
                        captured[key.data].append(data)
                        decoded = decoders[key.data].decode(data)
                        last_output = time.monotonic()
                    if decoded and on_output:
                        on_output(decoded)
                if on_status and now >= next_status:
                    on_status(now - started, now - last_output)
                    next_status = now + 30
            values = [b''.join(captured[name]) for name in ('stdout', 'stderr')]
            if text_mode:
                values = [value.decode(encoding, errors=errors) for value in values]
            return subprocess.CompletedProcess(args, process.wait(), *values)
        except BaseException:
            # Terminate descendants too, so cancellation cannot leave an orphan
            # native exporter writing into a workspace that is being removed.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            raise
        finally:
            selector.close()


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
    def __init__(self, executable, project, log=print, *, env=None, heartbeat=None, step_timeout=1800):
        self.executable = executable
        self.project = project
        self.log = log
        self.heartbeat = heartbeat
        self.step_timeout = step_timeout
        self._help = {}
        self.env = os.environ.copy()
        # KiCad's saved path variables must also be available to a headless worker.
        self.env.update({k: str(v) for k, v in project.variables.items()
                         if k.startswith('KICAD') or k == 'SPICE_LIB_DIR'})
        self.env.update(env or {})

    def _invoke(self, command, args, **kwargs):
        executable = [self.executable]
        # Ask libc-based native messages to flush promptly; absence of stdbuf
        # must not prevent export. Internal KiCad silent stages remain silent.
        if kwargs.get('on_output') and shutil.which('stdbuf'):
            executable = [shutil.which('stdbuf'), '-oL', '-eL', self.executable]
        try:
            return run_process([*executable, *command, *map(str, args)], heartbeat=self.heartbeat,
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
        def output_chunk(message):
            if message.rstrip('\r\n'):
                self.log(message.rstrip('\r\n'))
        def status(elapsed, silent):
            self.log(f'Running {" ".join(command)}: {elapsed:.0f}s elapsed; '
                     f'{max(0, silent):.0f}s without native output.')
        timeout = self.step_timeout if key == ('pcb', 'export', 'step') else None
        result = self._invoke(command, args, cwd=cwd, timeout=timeout,
                              on_output=output_chunk, on_status=status)
        output = (result.stdout + result.stderr).strip()
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

    def pdf(self, board, destination, layers, *, worksheet=None,
            common_layers=None, single_page=False):
        args = ['--output', destination, '--layers', ','.join(layers),
                '--mode-single' if single_page else '--mode-multipage',
                '--black-and-white', '--drill-shape-opt', '2',
                '--crossout-DNP-footprints-on-fab-layers']
        common = ['Edge.Cuts'] if common_layers is None else common_layers
        args += ['--common-layers', ','.join(common), '--include-border-title', '--scale', '1']
        if worksheet:
            args += ['--drawing-sheet', worksheet]
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


def pdf_merge_tool():
    executable = shutil.which('pdfunite')
    if not executable or not shutil.which('pdfinfo'):
        raise ExportError('Missing pdfunite/pdfinfo: install Poppler (poppler-utils on Debian/Ubuntu) '
                          'to assemble the PCB PDF and framed drill map pages.')
    return executable


def pdf_info(path):
    """Read the native page count and physical size without parsing PDF ourselves."""
    try:
        result = subprocess.run(['pdfinfo', str(path)], text=True, capture_output=True,
                                env={**os.environ, 'LC_ALL': 'C'}, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ExportError(f'Cannot inspect PCB PDF: {exc}') from exc
    pages = re.search(r'^Pages:\s+(\d+)', result.stdout, re.MULTILINE)
    size = re.search(r'^Page size:\s+([\d.]+) x ([\d.]+) pts', result.stdout, re.MULTILINE)
    if result.returncode or not pages or not size:
        raise ExportError(f'Cannot read PCB PDF page count/size: {result.stdout}\n{result.stderr}')
    return int(pages[1]), tuple(float(value) * 25.4 / 72 for value in size.groups())


def merge_pdfs(sources, destination, *, heartbeat=None):
    for path in sources:
        require_file(path)
    try:
        result = run_process([pdf_merge_tool(), *map(str, sources), str(destination)],
                             heartbeat=heartbeat, text=True, capture_output=True)
    except OSError as exc:
        raise ExportError(f'Cannot assemble PCB PDF: {exc}') from exc
    if result.returncode:
        raise ExportError(f'PDF assembly failed ({result.returncode}):\n'
                          f'{result.stdout}\n{result.stderr}')
    require_file(destination)


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
