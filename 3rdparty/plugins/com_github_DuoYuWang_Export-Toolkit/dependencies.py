"""Only KiCad's Python API and native exporters are required."""
import importlib.util
import importlib
import os
import re
import shutil
import subprocess
from .errors import ExportError


def check_dependencies(gui=False):
    problems = []
    if os.name != 'posix':
        problems.append('Export-Toolkit supports Unix-like systems only.')
    for module in ('pcbnew', 'wx') if gui else ('pcbnew',):
        if importlib.util.find_spec(module) is None:
            problems.append(f'Missing {module}: use the Python interpreter supplied with KiCad.')
        else:
            try:
                loaded = importlib.import_module(module)
                if module == 'pcbnew' and not loaded.GetBuildVersion().startswith('10.'):
                    problems.append('The pcbnew Python module must also be from KiCad 10.')
            except (ImportError, OSError) as exc:
                problems.append(f'Cannot load {module} and its native libraries: {exc}')
    cli = shutil.which(os.environ.get('EXPORT_TOOLKIT_KICAD_CLI', 'kicad-cli'))
    if not cli:
        problems.append('Missing kicad-cli. Install KiCad 10 and add its executable to PATH.')
    else:
        try:
            version = subprocess.run([cli, 'version'], text=True, capture_output=True,
                                     check=True, timeout=15).stdout.strip()
            if not re.match(r'10\.', version):
                problems.append(f'KiCad 10 is required; found {version}.')
        except (OSError, subprocess.SubprocessError) as exc:
            problems.append(f'Cannot run kicad-cli: {exc}')
    candidates = [os.environ.get('EXPORT_TOOLKIT_7Z', ''), '7zz', '7z']
    sevenzip = next((shutil.which(p) for p in candidates if p and shutil.which(p)), None)
    if not sevenzip:
        problems.append('Missing 7zz/7z. Install 7zip or set EXPORT_TOOLKIT_7Z to its executable.')
    else:
        try:
            subprocess.run([sevenzip, 'i'], capture_output=True, check=True, timeout=15)
        except (OSError, subprocess.SubprocessError) as exc:
            problems.append(f'Cannot run 7z / load its codecs: {exc}')
    if problems:
        raise ExportError('\n'.join(problems))
    return {'kicad_cli': cli, 'sevenzip': sevenzip, 'kicad_version': version}
