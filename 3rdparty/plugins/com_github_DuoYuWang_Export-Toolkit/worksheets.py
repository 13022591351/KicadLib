"""Supply Git values to native plotting without changing source drawing sheets."""
import base64
import ctypes
import ctypes.util
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
