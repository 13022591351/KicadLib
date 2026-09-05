"""Project-local options, shared by the toolbar and CLI."""
import json
import os
import tempfile
from pathlib import Path
from .errors import ExportError

VERSION = '0.1.0'
OPTIONS_FILE = 'export-toolkit-options.json'
DEFAULTS = {
    'pcb_package': True,
    'smt_package': True,
    'schematic_pdf': True,
    'pcb_pdf': True,
    'fab_pdf': True,
    'step_lite': False,
    'step_full': False,
    'refill_zones': False,
    'alternative_edge': False,
    'vcut': False,
    'auto_translate': True,
    'all_active_layers': False,
    'extra_layers': '',
    'strict': False,
    'open_output': True,
}
OUTPUT_OPTIONS = ('pcb_package', 'smt_package', 'schematic_pdf', 'pcb_pdf',
                  'step_lite', 'step_full')


def load_options(directory, path=None):
    path = Path(path) if path else Path(directory) / OPTIONS_FILE
    options = DEFAULTS.copy()
    if path.exists():
        try:
            stored = json.loads(path.read_text(encoding='utf-8'))
        except (ValueError, OSError) as exc:
            raise ExportError(f'Cannot read options {path}: {exc}') from exc
        if not isinstance(stored, dict):
            raise ExportError(f'Options must be a JSON object: {path}')
        for key, default in DEFAULTS.items():
            if key in stored:
                if type(stored[key]) is not type(default):
                    raise ExportError(f'Invalid option type: {key}')
                options[key] = stored[key]
    return options


def save_options(directory, options, path=None):
    path = Path(path) if path else Path(directory) / OPTIONS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump({key: options[key] for key in DEFAULTS}, stream, indent=2)
            stream.write('\n')
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)
