"""Optional vector text outlines for completed native KiCad PDF exports."""
import os
from pathlib import Path
import tempfile

from .errors import ExportError
from .pdf_fonts import pdf_font_library

METADATA_KEYS = ('title', 'author', 'subject', 'keywords', 'creator', 'producer',
                 'creationDate', 'modDate', 'trapped')
PAGE_SIZE_TOLERANCE = 0.05  # PDF points; SVG serialization rounds dimensions.


def pdf_outline_library():
    """Check vector conversion APIs before starting any selected PDF export."""
    library = pdf_font_library()
    for name, methods in (
            ('Document', ('convert_to_pdf', 'insert_pdf', 'get_toc', 'set_metadata')),
            ('Page', ('get_svg_image', 'get_fonts', 'get_text'))):
        cls = getattr(library, name, None)
        if cls is None or not all(hasattr(cls, method) for method in methods):
            raise ExportError('PDF text outlines require a PyMuPDF version with SVG vector '
                              'export and PDF conversion support. Update PyMuPDF in '
                              "KiCad's Python environment.")
    return library


def _page_sizes(document, heartbeat):
    sizes = []
    for page in document:
        if heartbeat:
            heartbeat()
        sizes.append((page.rect.width, page.rect.height))
    return sizes


def _check_page_sizes(document, expected, heartbeat):
    actual = _page_sizes(document, heartbeat)
    if len(actual) != len(expected) or any(
            abs(a - b) > PAGE_SIZE_TOLERANCE
            for size, wanted in zip(actual, expected) for a, b in zip(size, wanted)):
        raise ExportError('PDF page count or displayed paper size changed during text outlining.')


def outline_pdf_text(path, log=print, *, heartbeat=None):
    """Replace a staged PDF only after every vector page has been validated.

    SVG and per-page PDF buffers stay in memory. The final candidate is a sibling
    file in the export work directory. Links, popups and searchable text are not
    carried over; document information is retained, bookmarks are removed.
    """
    library = pdf_outline_library()
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ExportError(f'PDF text outlining requires a regular file: {path}')
    before = path.stat().st_size
    mode = path.stat().st_mode & 0o777
    temporary = None
    try:
        with library.open(path) as original:
            if not original.is_pdf or original.is_encrypted or not len(original):
                raise ExportError(f'Cannot outline a non-PDF, encrypted or empty document: {path}')
            sizes = _page_sizes(original, heartbeat)
            has_fonts = False
            for page in original:
                if heartbeat:
                    heartbeat()
                has_fonts = bool(page.get_fonts(full=True)) or has_fonts
            if not has_fonts and not original.get_toc():
                log(f'PDF outlines: {path.name}: no fonts or bookmarks; original retained.')
                return {'before_bytes': before, 'after_bytes': before, 'outlined': False,
                        'pages': len(original)}
            if original.is_repaired:
                log(f'PDF outlines: {path.name}: reader reconstructed the input index; '
                    'the converted PDF will be checked before replacement.')
            metadata = {key: value for key, value in original.metadata.items()
                        if key in METADATA_KEYS}
            log(f'PDF outlines: {path.name}: converting {len(original)} page(s); '
                'text search/copy, bookmarks, page links and property popups will be removed.')
            with library.open() as converted:
                for index, page in enumerate(original, 1):
                    if heartbeat:
                        heartbeat()
                    log(f'PDF outlines: {path.name}: page {index}/{len(original)}.')
                    svg = page.get_svg_image(text_as_path=True)
                    if heartbeat:
                        heartbeat()
                    with library.open(stream=svg.encode('utf-8'), filetype='svg') as vector:
                        with library.open(stream=vector.convert_to_pdf(), filetype='pdf') as single:
                            _check_page_sizes(single, [sizes[index - 1]], heartbeat)
                            converted.insert_pdf(single)
                    del svg
                converted.set_metadata(metadata)
                if heartbeat:
                    heartbeat()
                fd, name = tempfile.mkstemp(prefix='.' + path.name + '.outlines-',
                                            suffix='.pdf', dir=path.parent)
                os.close(fd)
                temporary = Path(name)
                converted.save(temporary, garbage=4, deflate=True)
        with library.open(temporary) as checked:
            if not checked.is_pdf or checked.is_repaired or checked.is_encrypted:
                raise ExportError(f'Invalid PDF after text outlining: {path.name}')
            _check_page_sizes(checked, sizes, heartbeat)
            if checked.get_toc() or any(checked.metadata.get(k) != v
                                               for k, v in metadata.items()):
                raise ExportError(f'PDF bookmarks remain or document information changed: {path.name}')
            for page in checked:
                if heartbeat:
                    heartbeat()
                if page.get_fonts(full=True) or page.get_text().strip():
                    raise ExportError(f'PDF still contains fonts or text after outlining: {path.name}')
        after = temporary.stat().st_size
        temporary.chmod(mode)
        if heartbeat:
            heartbeat()
        os.replace(temporary, path)
        temporary = None
        log(f'PDF outlines: {path.name}: completed; '
            f'{before / 1024**2:.2f} -> {after / 1024**2:.2f} MiB.')
        return {'before_bytes': before, 'after_bytes': after, 'outlined': True, 'pages': len(sizes)}
    except ExportError:
        raise
    except Exception as exc:
        raise ExportError(f'Cannot outline PDF text in {path.name}: {exc}') from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
