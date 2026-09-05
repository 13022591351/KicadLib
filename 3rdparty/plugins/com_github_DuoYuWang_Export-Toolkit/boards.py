"""Native board inspection and plot layer selection, without project copies."""
import json
from contextlib import contextmanager
from pathlib import Path

from .errors import ExportError


@contextmanager
def temporary_visible_layers(board_file, layers):
    """Set native plot bounds through local layer visibility, then restore it."""
    import pcbnew
    path = Path(board_file).with_suffix('.kicad_prl')
    previous = path.read_bytes() if path.exists() else None
    settings = json.loads(previous) if previous is not None else {}
    visible = pcbnew.LSET()
    for layer in layers:
        visible.AddLayer(layer)
    settings.setdefault('board', {})['visible_layers'] = visible.FmtHex()
    try:
        path.write_text(json.dumps(settings, indent=2) + '\n', encoding='utf-8')
        yield
    finally:
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(previous)


def layer_names(board):
    return {board.GetLayerName(layer): layer for layer in board.GetEnabledLayers().Seq()}


def drawing_items(board):
    yield from board.GetDrawings()
    for footprint in board.GetFootprints():
        yield from footprint.GraphicalItems()


def manufacturing_layers(board, alternative=False, vcut=False):
    import pcbnew
    names = layer_names(board)
    for enabled, name in ((alternative, 'Fab.EdgeCuts'), (vcut, 'Fab.VCut')):
        if enabled and name not in names:
            raise ExportError(f'Enabled custom layer not found: {name}')
        if enabled and not any(item.GetLayer() == names[name] for item in drawing_items(board)):
            raise ExportError(f'Enabled custom layer is empty: {name}')
    layers = [names['Fab.EdgeCuts'] if alternative else pcbnew.Edge_Cuts]
    if vcut:
        layers.append(names['Fab.VCut'])
    return layers


def check_models(board, project, warn=print):
    import pcbnew
    for fp in board.GetFootprints():
        # Both STEP presets exclude DNP and unspecified footprint types.
        if fp.IsDNP() or not fp.GetAttributes() & (pcbnew.FP_SMD | pcbnew.FP_THROUGH_HOLE):
            continue
        # SWIG vector iteration yields model copies; indexed access is mutable.
        for index in range(len(fp.Models())):
            model = fp.Models()[index]
            original = model.m_Filename
            if not original or original.startswith('kicad-embed://'):
                continue
            path = project.expand_path(original)
            # Keep unresolved built-in KiCad model variables for KiCad to resolve.
            if '${' in str(path):
                try:
                    expanded = pcbnew.ExpandEnvVarSubstitutions(original, board.GetProject())
                    path = project.expand_path(expanded)
                except (AttributeError, TypeError):
                    pass
            candidates = [path]
            if path.suffix.lower() in ('.wrl', '.vrml'):
                candidates = [path.with_suffix(ext) for ext in ('.step', '.stp', '.igs', '.iges')]
            if not any(p.is_file() for p in candidates):
                warn(f'{fp.GetReference()}: STEP-compatible 3D model not found: {original}')


def save_board(board, path):
    import pcbnew
    path.parent.mkdir(parents=True, exist_ok=True)
    original_name = board.GetFileName()
    try:
        if not pcbnew.SaveBoard(str(path), board, True):
            raise ExportError(f'KiCad could not save board: {path}')
    finally:
        board.SetFileName(original_name)


def board_content(board):
    """Compare native serializations in memory; KiCad's zone order can vary."""
    import pcbnew
    from .project import parse_sexpr
    formatter = pcbnew.STRING_FORMATTER()
    pcbnew.PCB_IO_KICAD_SEXPR().FormatBoardToFormatter(formatter, board)
    tree = parse_sexpr(formatter.GetString())
    return sorted(json.dumps(item, ensure_ascii=False) for item in tree[1:])


def plot_gerbers(board, directory, layers, outline):
    """Plot Gerbers using KiCad; select the outline without editing the PCB."""
    import pcbnew
    from .native import require_file
    controller = pcbnew.PLOT_CONTROLLER(board)
    options = controller.GetPlotOptions()
    options.SetOutputDirectory(str(directory))
    options.SetPlotFrameRef(False)
    options.SetAutoScale(False)
    options.SetScale(1)
    options.SetMirror(False)
    options.SetUseGerberProtelExtensions(True)
    options.SetUseGerberX2format(False)
    options.SetIncludeGerberNetlistInfo(True)
    options.SetUseAuxOrigin(True)
    options.SetSubtractMaskFromSilk(True)
    options.SetGerberPrecision(6)
    options.SetDrillMarksType(0)
    options.SetPlotOnAllLayersSequence(pcbnew.LSEQ())
    files = {}
    try:
        for layer in layers:
            controller.SetLayer(layer)
            name = pcbnew.BOARD.GetStandardLayerName(layer)
            if not controller.OpenPlotfile(name.replace('.', '_'), pcbnew.PLOT_FORMAT_GERBER, name):
                raise ExportError(f'KiCad could not open the {name} Gerber.')
            sequence = pcbnew.LSEQ()
            for selected in outline if layer == pcbnew.Edge_Cuts else [layer]:
                sequence.push_back(selected)
            if not controller.PlotLayers(sequence):
                raise ExportError(f'KiCad could not plot the {name} Gerber.')
            files[layer] = Path(controller.GetPlotFileName())
            controller.ClosePlot()
    finally:
        controller.ClosePlot()
    for path in files.values():
        require_file(path)
    return files


@contextmanager
def temporary_outline(board, outline):
    """Native drill maps/job metadata need the selected outline as Edge.Cuts.

    Change only layer assignments in the loaded board, then restore them. This
    board is never saved and the project files remain at their original paths.
    """
    import pcbnew
    changed = []
    try:
        for item in drawing_items(board):
            layer = item.GetLayer()
            target = layer
            if layer == pcbnew.Edge_Cuts and layer not in outline:
                target = pcbnew.Dwgs_User
            elif layer in outline:
                target = pcbnew.Edge_Cuts
            if target != layer:
                changed.append((item, layer))
                item.SetLayer(target)
        yield
    finally:
        for item, layer in reversed(changed):
            item.SetLayer(layer)


def write_drills_and_job(board, directory, outline, gerbers):
    """Write native PTH/NPTH drills, Gerber drill maps and Gerber job metadata."""
    import pcbnew
    from .native import require_file
    with temporary_outline(board, outline):
        writer = pcbnew.EXCELLON_WRITER(board)
        writer.SetOptions(False, False, board.GetDesignSettings().GetAuxOrigin(), False)
        writer.SetFormat(True)
        writer.SetRouteModeForOvalHoles(True)
        writer.SetMapFileFormat(pcbnew.PLOT_FORMAT_GERBER)
        if not writer.CreateDrillandMapFilesSet(str(directory), True, True):
            raise ExportError('KiCad could not write drill files and maps.')
        job = pcbnew.GERBER_JOBFILE_WRITER(board)
        for layer, path in gerbers.items():
            job.AddGbrFile(layer, path.name)
        destination = directory / (Path(board.GetFileName()).stem + '-job.gbrjob')
        if not job.CreateJobFile(str(destination)):
            raise ExportError('KiCad could not write the Gerber job file.')
        require_file(destination)
