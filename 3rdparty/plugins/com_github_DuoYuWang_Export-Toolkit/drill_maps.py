"""Native drill drawings, rendered on their own boards to avoid phantom holes."""
import json
import math
from pathlib import Path
import tempfile

from .boards import temporary_outline
from .errors import ExportError


def native_maps(board, directory, outline):
    """DXF preserves KiCad's hole symbols and stroked drill table as vectors."""
    import pcbnew
    directory.mkdir()
    with temporary_outline(board, outline):
        writer = pcbnew.EXCELLON_WRITER(board)
        # Absolute coordinates keep the map aligned with the PCB drawing.
        writer.SetOptions(False, False, pcbnew.VECTOR2I(0, 0), False)
        writer.SetFormat(True)
        writer.SetRouteModeForOvalHoles(True)
        writer.SetMapFileFormat(pcbnew.PLOT_FORMAT_DXF)
        if not writer.CreateDrillandMapFilesSet(str(directory), False, True):
            raise ExportError('KiCad could not generate drill map drawings.')
    prefix = Path(board.GetFileName()).stem + '-'
    maps = []
    for path in directory.glob('*-drl_map.dxf'):
        label = path.name.removeprefix(prefix).removesuffix('-drl_map.dxf')
        maps.append((label, path))
    maps.sort(key=lambda item: (0 if item[0] == 'PTH' else 1 if item[0] == 'NPTH' else 2, item[0]))
    if not maps:
        raise ExportError('KiCad did not produce any drill map drawings.')
    return maps


def dxf_entities(path):
    """Read only the vector entities emitted by KiCad's native drill exporter.

    Unexpected entities fail explicitly rather than silently omitting drill data.
    This is not a general DXF importer. KiCad emits its legend as stroked lines.
    """
    lines = path.read_text(encoding='utf-8-sig').splitlines()
    if len(lines) % 2:
        raise ExportError(f'Incomplete native drill map: {path.name}')
    try:
        pairs = [(int(code), value.strip()) for code, value in zip(lines[::2], lines[1::2])]
        unit = pairs.index((9, '$INSUNITS'))
        if pairs[unit + 1] != (70, '4'):
            raise ExportError('Native drill map must use millimeters.')
        start = pairs.index((2, 'ENTITIES')) + 1
        end = pairs.index((0, 'ENDSEC'), start)
    except ValueError as exc:
        raise ExportError(f'Invalid native drill map: {path.name}') from exc
    entities = []
    for code, value in pairs[start:end]:
        if code == 0:
            if value not in ('LINE', 'CIRCLE', 'ARC'):
                raise ExportError(f'Unsupported native drill map entity: {value} in {path.name}')
            entities.append({'kind': value})
        elif entities:
            entities[-1][code] = value
    return entities


def map_board(source, path, label):
    """Make a drawing-only board; no pads/vias can leak into another hole set."""
    import pcbnew
    # BOARD() wraps CreateEmptyBoard(), which returns null inside PCB Editor.
    # Use the file-format reader directly: pcbnew.LoadBoard() also switches
    # the editor's global drawing sheet/project state to the seed's defaults.
    # Keep the seed in this export's workspace, never in the source project.
    with tempfile.NamedTemporaryFile(mode='w', suffix='.kicad_pcb',
                                     prefix='drill-seed-', dir=path.parent,
                                     encoding='utf-8', delete=False) as stream:
        seed = Path(stream.name)
        stream.write('(kicad_pcb (version 20260206) (generator "pcbnew"))\n')
    try:
        reader = pcbnew.PCB_IO_KICAD_SEXPR()
        board = reader.LoadBoard(str(seed), None)
    finally:
        seed.unlink(missing_ok=True)
    if not board:
        raise ExportError('KiCad could not load the temporary drill drawing board.')
    board.SetPageSettings(source.GetPageSettings())
    board.SetTitleBlock(source.GetTitleBlock())
    enabled = board.GetEnabledLayers()
    enabled.AddLayer(pcbnew.User_1)
    board.SetEnabledLayers(enabled)
    board.SetLayerName(pcbnew.User_1, 'Drill.' + label)
    def point(x, y):
        return pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(-y))
    for entity in dxf_entities(path):
        shape = pcbnew.PCB_SHAPE(board)
        shape.SetLayer(pcbnew.User_1)
        shape.SetWidth(pcbnew.FromMM(0.15))
        shape.SetFilled(False)
        try:
            x, y = float(entity[10]), float(entity[20])
            if entity['kind'] == 'LINE':
                shape.SetShape(pcbnew.SHAPE_T_SEGMENT)
                shape.SetStart(point(x, y))
                shape.SetEnd(point(float(entity[11]), float(entity[21])))
            elif entity['kind'] == 'CIRCLE':
                shape.SetShape(pcbnew.SHAPE_T_CIRCLE)
                shape.SetCenter(point(x, y))
                shape.SetEnd(point(x + float(entity[40]), y))
            else:
                shape.SetShape(pcbnew.SHAPE_T_ARC)
                radius = float(entity[40])
                start, end = float(entity[50]), float(entity[51])
                sweep = (end - start) % 360
                def polar(angle):
                    angle = math.radians(angle)
                    return point(x + radius * math.cos(angle), y + radius * math.sin(angle))
                shape.SetArcGeometry(polar(start), polar(start + sweep / 2), polar(start + sweep))
        except (KeyError, ValueError) as exc:
            raise ExportError(f'Invalid drill map geometry in {path.name}') from exc
        board.Add(shape)
    return board


def save_map_board(board, project, directory):
    import pcbnew
    directory.mkdir()
    destination = directory / project.board.name
    # Serialize only the drawing board; do not load/switch/save editor projects.
    pcbnew.PCB_IO_KICAD_SEXPR().SaveBoard(str(destination), board)
    # Preserve title-block/project variables, not the PCB or schematic contents.
    data = {'text_variables': project.data.get('text_variables', {})}
    destination.with_suffix('.kicad_pro').write_text(json.dumps(data), encoding='utf-8')
    return destination
