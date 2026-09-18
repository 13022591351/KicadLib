"""Supply Git values to native plotting without changing source drawing sheets."""
import base64
import ctypes
import ctypes.util
from pathlib import Path
import re
import json
from functools import lru_cache

from .errors import ExportError
from .project import child, children, read_tree

VCS_ALIASES = {'VCSHASH': 'EXPORT_TOOLKIT_VCS_HASH',
               'VCSSHORTHASH': 'EXPORT_TOOLKIT_VCS_ID'}
MAX_WORKSHEET_BYTES = 64 * 1024 * 1024


@lru_cache(maxsize=1)
def zstd_library():
    """Use the system library that decodes KiCad's embedded drawing sheets."""
    name = ctypes.util.find_library('zstd')
    if not name:
        raise ExportError('Missing system libzstd, required for embedded KiCad drawing sheets.')
    try:
        library = ctypes.CDLL(name)
        library.ZSTD_getFrameContentSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        library.ZSTD_getFrameContentSize.restype = ctypes.c_ulonglong
        library.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                            ctypes.c_void_p, ctypes.c_size_t]
        library.ZSTD_decompress.restype = ctypes.c_size_t
        library.ZSTD_isError.argtypes = [ctypes.c_size_t]
        library.ZSTD_isError.restype = ctypes.c_uint
    except (OSError, AttributeError) as exc:
        raise ExportError(f'Cannot load system libzstd: {exc}') from exc
    return library


def embedded_worksheet(source, name):
    files = child(read_tree(source), 'embedded_files', [])
    matches = [item for item in children(files, 'file')
               if child(item, 'name', ['', ''])[1] == name]
    if len(matches) != 1:
        raise ExportError(f'Embedded drawing sheet {name!r} not found uniquely in {source.name}.')
    encoded = ''.join(child(matches[0], 'data', [])[1:]).replace('|', '')
    try:
        compressed = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise ExportError(f'Invalid embedded drawing sheet encoding: {name}') from exc
    library = zstd_library()
    source_buffer = ctypes.create_string_buffer(compressed)
    size = library.ZSTD_getFrameContentSize(source_buffer, len(compressed))
    # UNKNOWN/ERROR are unsigned values above the limit. Reject them before
    # allocating, as KiCad itself does for embedded files with unknown sizes.
    if not 0 < size <= MAX_WORKSHEET_BYTES:
        raise ExportError(f'Embedded drawing sheet has an invalid or excessive decoded size: {name}')
    destination = ctypes.create_string_buffer(size)
    written = library.ZSTD_decompress(destination, size, source_buffer, len(compressed))
    if library.ZSTD_isError(written) or written != size:
        raise ExportError(f'Cannot decompress embedded drawing sheet: {name}')
    return destination.raw[:written]


def prepare_worksheet(project, kind, work):
    """Keep the drawing intact, replacing only reserved VCS variable names."""
    section = 'pcbnew' if kind == 'pcb' else 'schematic'
    value = project.data.get(section, {}).get('page_layout_descr_file', '')
    if not value:
        return None
    original = project.worksheet(kind)
    if original is None:
        source = project.board if kind == 'pcb' else project.schematic
        contents = embedded_worksheet(source, value.removeprefix('kicad-embed://'))
    else:
        contents = original.read_bytes()
    updated = contents
    for builtin, alias in VCS_ALIASES.items():
        updated = updated.replace(('${' + builtin + '}').encode(), ('${' + alias + '}').encode())
    if updated == contents:
        # Let KiCad load the original external/embedded worksheet when it has
        # no VCS tokens. No export copy is needed in that case.
        return original
    directory = work / 'drawing-sheets'
    directory.mkdir(exist_ok=True)
    destination = directory / f'{kind}.kicad_wks'
    destination.write_bytes(updated)
    return destination


def document_worksheet(project, work, executable):
    """Resolve an explicit PCB worksheet so all assembled pages share totals."""
    path = prepare_worksheet(project, 'pcb', work)
    if path is not None:
        contents = path.read_text(encoding='utf-8-sig')
    else:
        value = project.data.get('pcbnew', {}).get('page_layout_descr_file', '')
        if value.startswith('kicad-embed://'):
            contents = embedded_worksheet(project.board, value.removeprefix('kicad-embed://')).decode('utf-8-sig')
        else:
            candidates = [Path(executable).resolve().parent.parent / 'share/kicad/template',
                          Path(executable).resolve().parent.parent / 'SharedSupport/template',
                          Path('/usr/share/kicad/template'), Path('/usr/local/share/kicad/template')]
            for key in ('KICAD10_TEMPLATE_DIR', 'KICAD_TEMPLATE_DIR'):
                if project.variables.get(key):
                    candidates.insert(0, Path(project.variables[key]))
            default = next((p / 'pagelayout_default.kicad_wks' for p in candidates
                            if (p / 'pagelayout_default.kicad_wks').is_file()), None)
            if default is None:
                raise ExportError('Cannot locate KiCad default drawing sheet. '
                                  'Select a .kicad_wks drawing sheet in the project page settings.')
            contents = default.read_text(encoding='utf-8-sig')
    for builtin, alias in VCS_ALIASES.items():
        contents = contents.replace('${' + builtin + '}', '${' + alias + '}')
    return contents


def numbered_worksheet(contents, work, total, page=None, *, comment1=None, revision=None):
    """Set the document total, and continuation-page numbers for drill maps."""
    contents = contents.replace('${##}', str(total)).replace('%N', str(total))
    if page is not None:
        contents = contents.replace('${#}', str(page)).replace('%S', str(page))
    if page is not None and page > 1:
        # Every map is a separate native export, but a continuation sheet in
        # the assembled PDF. Respect first-page-only worksheet decorations.
        contents = re.sub(r'\(option\s+notonpage1\s*\)', '', contents)
        contents = re.sub(r'\(option\s+page1only\s*\)', '(option notonpage1)', contents)
    substitutions = {}
    for tokens, value in ((('${COMMENT1}', '%C0'), comment1),
                          (('${REVISION}', '%R'), revision)):
        if value is not None:
            escaped = json.dumps(value, ensure_ascii=False)[1:-1]
            substitutions.update(dict.fromkeys(tokens, escaped))
    if substitutions:
        # Quote the value as worksheet string content, not CLI KEY=VALUE: KiCad
        # rejects --define-var values containing '='. Substitute in one pass so
        # tokens inside the user text cannot trigger another replacement here.
        contents = re.sub('|'.join(re.escape(token) for token in substitutions),
                          lambda match: substitutions[match[0]], contents)
    directory = work / 'drawing-sheets'
    directory.mkdir(exist_ok=True)
    path = directory / f'pcb-document-{page or "layers"}.kicad_wks'
    path.write_text(contents, encoding='utf-8')
    return path
