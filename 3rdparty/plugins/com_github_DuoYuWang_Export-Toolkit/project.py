"""Read KiCad project metadata; never rewrite the user's source files."""
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from .errors import ExportError


def parse_sexpr(text):
    """Read lists, atoms and KiCad quoted strings, including escaped quotes.

    Embedded base64 data is treated as atoms. We only read this representation;
    all board/schematic exports and board serialization belong to KiCad.
    """
    root, stack, i = [], [], 0
    current = root
    while i < len(text):
        c = text[i]
        if c.isspace():
            i += 1
        elif c == '(':
            node = []
            current.append(node)
            stack.append(current)
            current = node
            i += 1
        elif c == ')':
            if not stack:
                raise ExportError('Unexpected closing parenthesis in KiCad file')
            current = stack.pop()
            i += 1
        elif c == '"':
            value = []
            i += 1
            while i < len(text) and text[i] != '"':
                if text[i] == '\\':
                    i += 1
                    if i == len(text):
                        raise ExportError('Incomplete KiCad string escape')
                    value.append({'n': '\n', 'r': '\r', 't': '\t'}.get(text[i], text[i]))
                else:
                    value.append(text[i])
                i += 1
            if i == len(text):
                raise ExportError('Unclosed KiCad string')
            current.append(''.join(value))
            i += 1
        else:
            end = i
            while end < len(text) and not text[end].isspace() and text[end] not in '()':
                end += 1
            current.append(text[i:end])
            i = end
    if stack or len(root) != 1:
        raise ExportError('Incomplete KiCad S-expression')
    return root[0]


def children(node, key):
    return [item for item in node if isinstance(item, list) and item and item[0] == key]


def child(node, key, default=None):
    values = children(node, key)
    return values[0] if values else default


def read_tree(path):
    return parse_sexpr(Path(path).read_text(encoding='utf-8-sig'))


def safe_component(value, label):
    value = value.strip()
    if not value or value in ('.', '..') or any(c in value for c in '/\x00\n\r'):
        raise ExportError(f'{label} must be non-empty and contain no path separators or newlines.')
    return value


def git_commit(directory):
    try:
        return subprocess.run(['git', '-C', str(directory), 'rev-parse', 'HEAD'],
                              capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ''


def kicad_config_home():
    return Path(os.environ.get('KICAD_CONFIG_HOME',
                str(Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'kicad')))


def path_variables():
    """Read KiCad Configure Paths without writing the user's global settings."""
    common = kicad_config_home() / '10.0' / 'kicad_common.json'
    values = {}
    if common.exists():
        values.update(json.loads(common.read_text()).get('environment', {}).get('vars', {}))
    values.update(os.environ)
    return values


@dataclass
class Project:
    file: Path
    board: Path
    schematic: Path
    name: str
    pcb_revision: str
    sch_revision: str
    data: dict
    variables: dict
    commit: str

    @classmethod
    def open(cls, project_file, board=None, schematic=None):
        file = Path(project_file).expanduser().resolve()
        if file.suffix != '.kicad_pro' or not file.is_file():
            raise ExportError(f'Project file not found: {file}')
        try:
            data = json.loads(file.read_text(encoding='utf-8'))
        except json.JSONDecodeError as exc:
            raise ExportError(f'Invalid project JSON in {file}: {exc}') from exc
        board = (Path(board).expanduser() if board else file.with_suffix('.kicad_pcb')).resolve()
        schematic = (Path(schematic).expanduser() if schematic else file.with_suffix('.kicad_sch')).resolve()
        # Native exporters discover settings using the input's directory and
        # filename stem. This binding is required even when ERC/DRC is not run.
        for label, item, suffix in (('PCB', board, '.kicad_pcb'),
                                    ('Root schematic', schematic, '.kicad_sch')):
            expected = file.with_suffix(suffix)
            if item != expected:
                raise ExportError(f'{label} must share the selected project\'s directory and filename stem.\n'
                                  f'Selected: {item}\nExpected: {expected}\n'
                                  'Select a matching project or input file so KiCad loads the correct settings.')
            if not item.is_file():
                raise ExportError(f'Input file not found: {item}')
        variables = path_variables()
        variables.update(data.get('text_variables', {}))
        commit = git_commit(file.parent)
        variables.update(KIPRJMOD=str(file.parent), PROJECTNAME=file.stem,
                         VCSHASH=commit or 'no hash', VCSSHORTHASH=commit[:8] or 'no hash')
        def revision(path):
            block = child(read_tree(path), 'title_block', [])
            raw = child(block, 'rev', ['', ''])[1]
            for _ in range(10):
                expanded = re.sub(r'\$\{([^}]+)\}', lambda m: str(variables.get(m[1], m[0])), raw)
                if raw == expanded:
                    break
                raw = expanded
            if '${' in raw:
                raise ExportError(f'Unresolved Revision variable in {path}: {raw}')
            return safe_component(raw, f'Revision in {path.name}')
        return cls(file, board, schematic, safe_component(file.stem, 'Project name'),
                   revision(board), revision(schematic), data, variables, commit)

    @property
    def release_dir(self):
        return self.file.parent / 'Export' / f'{self.name}-{self.sch_revision}'

    def expand_path(self, value, base=None):
        for _ in range(10):
            expanded = re.sub(r'\$\{([^}]+)\}', lambda m: str(self.variables.get(m[1], m[0])), value)
            if expanded == value:
                break
            value = expanded
        path = Path(value).expanduser()
        return path if path.is_absolute() else (base or self.file.parent) / path

    def worksheet(self, kind):
        section = 'pcbnew' if kind == 'pcb' else 'schematic'
        value = self.data.get(section, {}).get('page_layout_descr_file', '')
        if not value or value.startswith('kicad-embed://'):
            return None
        path = self.expand_path(value)
        if not path.is_file():
            raise ExportError(f'Drawing sheet not found: {path}')
        return path.resolve()
