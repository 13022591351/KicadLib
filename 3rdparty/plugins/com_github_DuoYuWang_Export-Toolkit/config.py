"""Project-local options, shared by the toolbar and CLI."""
import json
import os
import tempfile
from pathlib import Path
from .errors import ExportError

VERSION = '0.1.0'
OPTIONS_FILE = 'export-toolkit-options.json'
LAST_CHECK_SUCCESS = 'last_check_success_at'
DEFAULTS = {
    'pcb_package': True,
    'smt_package': True,
    'schematic_pdf': True,
    'pcb_pdf': True,
    'pcba_pdf': False,
    'pcba_comment': '',
    'fab_pdf': True,
    'step_lite': False,
    'step_full': False,
    'alternative_edge': False,
    'vcut': False,
    'auto_translate': True,
    'all_active_layers': False,
    'extra_layers': '',
    'pdf_text_outlines': True,
    'font_name': 'Sarasa Fixed SC',
    'font_replace_all': False,
    'strict': False,
    'open_output': True,
}
OUTPUT_OPTIONS = ('pcb_package', 'smt_package', 'schematic_pdf', 'pcb_pdf',
                  'pcba_pdf', 'step_lite', 'step_full')


def pcba_enabled(options):
    return bool(options.get('pcba_pdf', False) and options.get('pcba_comment', '').strip())


def has_outputs(options):
    return any(options[key] for key in OUTPUT_OPTIONS if key != 'pcba_pdf') or pcba_enabled(options)


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


def load_last_check(directory, path=None):
    path = Path(path) if path else Path(directory) / OPTIONS_FILE
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        value = data.get(LAST_CHECK_SUCCESS) if isinstance(data, dict) else None
        return value if isinstance(value, str) and value else None
    except (OSError, ValueError):
        return None


def last_check_label(value):
    return 'Last successful ERC/DRC: ' + (value or 'Not recorded')


def save_options(directory, options, path=None, *, last_check_success_at=None):
    """Preserve history by default; an explicit empty string clears it."""
    path = Path(path) if path else Path(directory) / OPTIONS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    last_check = (load_last_check(directory, path) if last_check_success_at is None
                  else last_check_success_at)
    data = {key: options[key] for key in DEFAULTS}
    if last_check:
        data[LAST_CHECK_SUCCESS] = last_check
    fd, tmp = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, indent=2)
            stream.write('\n')
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)
