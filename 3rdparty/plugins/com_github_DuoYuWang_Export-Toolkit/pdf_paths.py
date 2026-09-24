"""Share exact filled paths in outlined schematic PDFs, without rasterization.

This deliberately accepts only the simple graphics streams written by our
MuPDF SVG conversion, not arbitrary PDF syntax. Unsupported input is retained.
"""
from collections import Counter
import hashlib
import math
import os
from pathlib import Path
import re
import tempfile

from .errors import ExportError
from .pdf_fonts import pdf_font_library

NUMBER = re.compile(rb'[-+]?(?:\d*\.\d+|\d+\.?\d*)\Z')
TOKEN = re.compile(rb'\S+')
NAME = re.compile(rb'/[^\s()<>\[\]{}/%]+\Z')
CALL = re.compile(rb'/ETPath\d+\s+Do(?!\S)')
ARITY = {b'm': 2, b'l': 2, b'c': 6, b'h': 0}
PATH_OPS = set(ARITY) | {b'v', b'y', b're'}
PAINT = {b'f', b'f*', b'F', b'S', b's', b'B', b'B*', b'b', b'b*', b'n'}
OTHER_OPS = set(b'q Q cm w J j M d ri i gs CS cs SC SCN sc scn G g RG rg K k W W* Do'.split())


class UnsupportedPaths(Exception):
    """Optimization is optional; preserve unsupported graphics unchanged."""


def filled_paths(stream, heartbeat=None):
    """Yield (start, end, normalized instructions), in a single linear scan."""
    if any(c in stream for c in (b'(', b')', b'<', b'>', b'%', b'\x00')):
        raise UnsupportedPaths('complex PDF syntax')
    start, valid, numbers = None, True, []
    for index, token in enumerate(TOKEN.finditer(stream)):
        if heartbeat and index % 4096 == 0:
            heartbeat()
        value = token[0]
        if NUMBER.fullmatch(value):
            numbers.append(token.start())
            continue
        if value in PATH_OPS:
            if start is None:
                start = numbers[0] if numbers else token.start()
                valid = value == b'm'
            valid = valid and len(numbers) == ARITY.get(value, -1)
        elif value in PAINT:
            if start is not None and valid and not numbers and value in (b'f', b'f*'):
                if token.end() - start >= 128:
                    yield start, token.end(), b' '.join(stream[start:token.end()].split())
            start, valid = None, True
        elif value in OTHER_OPS or NAME.fullmatch(value) or value in (b'[', b']'):
            # Do not extract any suffix of a clipped/unsupported path.
            if start is not None:
                valid = False
        else:
            raise UnsupportedPaths(f'unsupported graphics token {value[:32]!r}')
        numbers = []


def content_hash(stream):
    return hashlib.sha256(b' '.join(stream.split())).digest()


def dictionary(document, xref, key):
    kind, value = document.xref_get_key(xref, key)
    if kind == 'xref':
        value = document.xref_object(int(value.split()[0]))
    if not value.startswith('<<') or not value.rstrip().endswith('>>'):
        raise UnsupportedPaths(f'missing direct {key} dictionary')
    return value.rstrip()


def validate_candidate(library, candidate, expected, metadata, heartbeat):
    with library.open(candidate) as checked:
        if checked.is_repaired or checked.is_encrypted or len(checked) != len(expected):
            raise ExportError('Invalid PDF after schematic path reuse.')
        if checked.metadata != metadata or checked.get_toc():
            raise ExportError('PDF document information changed during schematic path reuse.')
        for page, (geometry, digest) in zip(checked, expected):
            if heartbeat:
                heartbeat()
            actual = (tuple(page.mediabox), tuple(page.cropbox), page.rotation)
            if actual != geometry or page.get_fonts() or page.get_text().strip():
                raise ExportError('PDF page geometry or text changed during schematic path reuse.')
            forms = {name: checked.xref_stream(xref)
                     for xref, name, _, _ in page.get_xobjects()}
            expanded = CALL.sub(lambda m: forms[m[0].split()[0][1:].decode('ascii')],
                                page.read_contents())
            if content_hash(expanded) != digest:
                raise ExportError('PDF drawing instructions changed during schematic path reuse.')


def reuse_pdf_paths(path, log=print, *, heartbeat=None):
    """Atomically keep a smaller validated candidate; never modify design files."""
    library = pdf_font_library()
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ExportError(f'Schematic path reuse requires a regular PDF: {path}')
    before = path.stat().st_size
    result = dict(before_bytes=before, after_bytes=before, reused=False,
                  shared_paths=0, references=0)
    temporary = None
    try:
        with library.open(path) as document:
            if not document.is_pdf or document.is_encrypted or document.is_repaired or not len(document):
                raise UnsupportedPaths('not a clean, unencrypted PDF')
            if document.get_toc():
                raise UnsupportedPaths('document is not outlined')
            counts, expected = Counter(), []
            for index, page in enumerate(document, 1):
                log(f'PDF path reuse: {path.name}: scanning page {index}/{len(document)}.')
                if page.get_fonts() or page.get_xobjects() or page.get_links() or list(page.annots()):
                    raise UnsupportedPaths('fonts, existing Forms or annotations')
                # Fail closed for inherited/unusual resource layouts.
                dictionary(document, page.xref, 'Resources')
                stream = page.read_contents()
                if re.search(rb'/ETPath\d+', stream):
                    raise UnsupportedPaths('reserved resource name already in use')
                expected.append(((tuple(page.mediabox), tuple(page.cropbox), page.rotation),
                                 content_hash(stream)))
                counts.update(p for _, _, p in filled_paths(stream, heartbeat))
            chosen = [p for p, n in counts.items() if n >= 3 and (len(p)-24)*(n-1) > 300]
            if not chosen:
                log(f'PDF path reuse: {path.name}: no reusable paths; original retained.')
                return result
            forms = {}
            for index, instructions in enumerate(chosen):
                if heartbeat:
                    heartbeat()
                coordinates = [float(t) for t in instructions.split() if NUMBER.fullmatch(t)]
                if not all(math.isfinite(v) and abs(v) < 1e7 for v in coordinates):
                    raise UnsupportedPaths('out-of-range path coordinates')
                xs, ys = coordinates[0::2], coordinates[1::2]
                # All control points lie inside this box, so it cannot clip
                # the filled Bezier curves. The added box is not artwork.
                bbox = (math.floor(min(xs))-1, math.floor(min(ys))-1,
                        math.ceil(max(xs))+1, math.ceil(max(ys))+1)
                xref = document.get_new_xref()
                document.update_object(xref, '<< /Type /XObject /Subtype /Form /FormType 1 '
                                       '/BBox [' + ' '.join(map(str, bbox)) + '] /Resources << >> >>')
                document.update_stream(xref, instructions)
                forms[instructions] = (f'ETPath{index}', xref)
            for index, page in enumerate(document, 1):
                log(f'PDF path reuse: {path.name}: sharing page {index}/{len(document)}.')
                original = page.read_contents()
                parts, end, used = [], 0, {}
                for start, stop, instructions in filled_paths(original, heartbeat):
                    if instructions not in forms:
                        continue
                    name, xref = forms[instructions]
                    used[name] = xref
                    parts.extend((original[end:start], f'/{name} Do'.encode('ascii')))
                    end = stop
                    result['references'] += 1
                if not used:
                    continue
                parts.append(original[end:])
                resources = dictionary(document, page.xref, 'Resources')
                document.xref_set_key(page.xref, 'Resources', resources)
                kind, _ = document.xref_get_key(page.xref, 'Resources/XObject')
                # Preserve image resources; original Form objects were excluded.
                objects = ('<< >>' if kind == 'null' else
                           dictionary(document, page.xref, 'Resources/XObject'))
                additions = ' '.join(f'/{name} {xref} 0 R' for name, xref in used.items())
                document.xref_set_key(page.xref, 'Resources/XObject', objects[:-2] + additions + ' >>')
                xref = document.get_new_xref()
                document.update_object(xref, '<< >>')
                document.update_stream(xref, b''.join(parts))
                page.set_contents(xref)
            metadata = document.metadata
            if heartbeat:
                heartbeat()
            fd, name = tempfile.mkstemp(prefix='.' + path.name + '.paths-', suffix='.pdf', dir=path.parent)
            os.close(fd)
            temporary = Path(name)
            document.save(temporary, garbage=4, deflate=True)
        validate_candidate(library, temporary, expected, metadata, heartbeat)
        after = temporary.stat().st_size
        if after >= before:
            log(f'PDF path reuse: {path.name}: no size reduction; original retained.')
            return result
        temporary.chmod(path.stat().st_mode & 0o777)
        if heartbeat:
            heartbeat()
        os.replace(temporary, path)
        temporary = None
        result.update(after_bytes=after, reused=True, shared_paths=len(forms))
        log(f'PDF path reuse: {path.name}: {len(forms)} shared paths, '
            f'{result["references"]} references; {before / 1024**2:.2f} -> {after / 1024**2:.2f} MiB.')
        return result
    except UnsupportedPaths as exc:
        log(f'PDF path reuse: {path.name}: {exc}; original retained.')
        return result
    except ExportError:
        raise
    except Exception as exc:
        raise ExportError(f'Cannot reuse schematic PDF paths in {path.name}: {exc}') from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
