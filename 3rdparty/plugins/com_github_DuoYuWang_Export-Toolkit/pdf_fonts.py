"""Share identical embedded font programs without changing fonts or artwork."""
import hashlib
import importlib
import os
from pathlib import Path
import tempfile

from .errors import ExportError

FONT_FILES = ('FontFile', 'FontFile2', 'FontFile3')
STREAM_STORAGE_KEYS = {'Length', 'Filter', 'DecodeParms', 'DL'}


def pdf_font_library():
    """Use the KiCad interpreter's installed PyMuPDF; never install at runtime."""
    for name in ('pymupdf', 'fitz'):
        try:
            module = importlib.import_module(name)
            if all(hasattr(module.Document, method) for method in
                   ('xref_get_keys', 'xref_get_key', 'xref_set_key', 'xref_stream', 'save')):
                return module
        except (ImportError, OSError, AttributeError):
            pass
    raise ExportError('PDF exports require PyMuPDF for font processing. '
                      'Install PyMuPDF in the Python environment used by KiCad '
                      '(for example: python3 -m pip install --user PyMuPDF).')


def _page_signature(document, heartbeat):
    """Check page geometry and decoded drawing instructions, without rendering."""
    result = []
    for page in document:
        if heartbeat:
            heartbeat()
        content = tuple(hashlib.sha256(document.xref_stream(xref)).digest()
                        for xref in page.get_contents())
        result.append((tuple(page.mediabox), tuple(page.cropbox), page.rotation, content))
    return result


def deduplicate_pdf_fonts(path, log=print, *, heartbeat=None):
    """Atomically replace a staged PDF only after an identical-font-only rewrite.

    Font descriptors, character maps, font names and styling remain distinct.
    Only FontFile references with matching decoded bytes AND stream metadata
    share an existing font stream. This neither subsets fonts nor rasterizes.
    """
    library = pdf_font_library()
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ExportError(f'Font deduplication requires a regular PDF file: {path}')
    before = path.stat().st_size
    result = {'before_bytes': before, 'after_bytes': before, 'duplicate_streams': 0}
    temporary = None
    try:
        with library.open(path) as document:
            if not document.is_pdf or document.is_encrypted:
                raise ExportError(f'Refusing to rewrite a non-PDF or encrypted PDF: {path}')
            if document.is_repaired:
                # Some pdfunite releases write inconsistent xref subsection
                # counts. Accept the reader's recovered index, but validate
                # every page and require a clean index on the saved candidate.
                log(f'PDF fonts: {path.name}: reader reconstructed the PDF index; '
                    'output will be verified before replacement.')
            references = []
            for descriptor in range(1, document.xref_length()):
                if heartbeat and descriptor % 128 == 0:
                    heartbeat()
                if document.xref_get_key(descriptor, 'Type') != ('name', '/FontDescriptor'):
                    continue
                for key in FONT_FILES:
                    kind, reference = document.xref_get_key(descriptor, key)
                    if kind == 'xref':
                        references.append((descriptor, key, int(reference.split()[0]), reference))
            seen, replacements, visited = {}, {}, set()
            for _, _, xref, reference in references:
                if xref in visited:
                    continue
                visited.add(xref)
                if heartbeat:
                    heartbeat()
                payload = document.xref_stream(xref)
                if payload is None:
                    raise ExportError(f'Invalid embedded font stream in {path.name}: {xref}')
                metadata = tuple((key, document.xref_get_key(xref, key))
                                 for key in sorted(document.xref_get_keys(xref))
                                 if key not in STREAM_STORAGE_KEYS)
                signature = (len(payload), hashlib.sha256(payload).digest(), metadata)
                candidate = seen.get(signature)
                if candidate and document.xref_stream(candidate[0]) == payload:
                    replacements[xref] = candidate[1]
                else:
                    seen[signature] = (xref, reference)
            if not replacements:
                log(f'PDF fonts: {path.name}: no duplicate embedded font streams.')
                return result
            original_pages = _page_signature(document, heartbeat)
            original_toc = document.get_toc()
            original_metadata = document.metadata
            for descriptor, key, xref, _ in references:
                if xref in replacements:
                    document.xref_set_key(descriptor, key, replacements[xref])
            fd, name = tempfile.mkstemp(prefix='.' + path.name + '.fonts-', suffix='.pdf', dir=path.parent)
            os.close(fd)
            temporary = Path(name)
            if heartbeat:
                heartbeat()
            # Collect only unreachable objects. Do not use garbage=3/4, clean,
            # subset_fonts or image/font recompression: keep other data alone.
            document.save(temporary, garbage=1, clean=False, deflate=False,
                          no_new_id=True, encryption=library.PDF_ENCRYPT_KEEP)
        with library.open(temporary) as checked:
            if (checked.is_repaired or _page_signature(checked, heartbeat) != original_pages
                    or checked.get_toc() != original_toc or checked.metadata != original_metadata):
                raise ExportError(f'PDF verification failed after font deduplication: {path.name}')
        after = temporary.stat().st_size
        if after >= before:
            log(f'PDF fonts: {path.name}: original retained (no size reduction).')
            return result
        if heartbeat:
            heartbeat()
        temporary.chmod(path.stat().st_mode & 0o777)
        os.replace(temporary, path)
        temporary = None
        result.update(after_bytes=after, duplicate_streams=len(replacements))
        log(f'PDF fonts: {path.name}: removed {len(replacements)} duplicate font stream(s); '
            f'{before / 1024**2:.2f} -> {after / 1024**2:.2f} MiB.')
        return result
    except ExportError:
        raise
    except Exception as exc:
        raise ExportError(f'Cannot deduplicate PDF fonts in {path.name}: {exc}') from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
