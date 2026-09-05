"""Individual native exports and the shared release naming/STEP conventions."""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .boards import layer_names, plot_gerbers, temporary_visible_layers, write_drills_and_job
from .native import Native, archive, require_file
from .project import Project
from .tables import adapt_tables
from .errors import ExportError

OUTPUT_NAMES = {
    'pcb_package': ('PCB', 'pcb_revision', '7z'),
    'smt_package': ('SMT', 'sch_revision', '7z'),
    'pcb_pdf': ('PCB', 'pcb_revision', 'pdf'),
    'schematic_pdf': ('SCH', 'sch_revision', 'pdf'),
    'fab_front': ('FFab', 'sch_revision', 'pdf'),
    'fab_back': ('BFab', 'sch_revision', 'pdf'),
    'step_lite': ('CAD-lite', 'sch_revision', 'step'),
    'step_full': ('CAD-full', 'sch_revision', 'step'),
    'bom': ('BOM', 'sch_revision', 'csv'),
    'pos': ('POS', 'sch_revision', 'csv'),
    'net': ('NET', 'pcb_revision', 'ipc'),
}
STEP_COMMON = ('--force', '--no-dnp', '--no-unspecified', '--subst-models',
               '--drill-origin', '--min-distance', '0.001mm')
STEP_FULL = ('--include-tracks', '--include-pads', '--include-zones', '--include-inner-copper',
             '--cut-vias-in-body', '--include-silkscreen', '--include-soldermask')


def output_name(project, kind):
    label, revision, extension = OUTPUT_NAMES[kind]
    return f'{project.name}-{label}-{getattr(project, revision)}.{extension}'


@dataclass
class ExportJobs:
    """The shared inputs for a single export run; no project files are copied."""
    project: Project
    options: dict
    board: object
    native: Native
    work: Path
    release: Path
    sevenzip: str
    log: Callable
    warn_mpn: Callable
    heartbeat: Optional[Callable] = None

    def path(self, kind, directory=None):
        return (self.release if directory is None else directory) / output_name(self.project, kind)

    def pack(self, source, kind):
        archive(self.sevenzip, source, self.path(kind), self.log, heartbeat=self.heartbeat)

    def export_pcb_package(self, outline):
        directory = self.work / 'fabrication'
        directory.mkdir()
        layers = gerber_layers(self.board, self.options)
        self.log('KiCad: plotting Gerbers, drills, drill maps and Gerber job.')
        gerbers = plot_gerbers(self.board, directory, layers, outline)
        write_drills_and_job(self.board, directory, outline, gerbers)
        netlist = self.path('net', directory)
        self.native.run(['pcb', 'export', 'ipcd356'], ['--output', netlist, self.project.board])
        require_file(netlist)
        self.pack(directory, 'pcb_package')

    def export_smt_package(self):
        directory = self.work / 'assembly'
        directory.mkdir()
        raw_pos = self.work / 'native-pos.csv'
        self.native.run(['pcb', 'export', 'pos'], [
            '--output', raw_pos, '--side', 'both', '--format', 'csv', '--units', 'mm',
            '--use-drill-file-origin', '--exclude-dnp', self.project.board])
        adapt_tables(self.board, raw_pos, self.path('bom', directory), self.path('pos', directory),
                     self.options['auto_translate'], self.warn_mpn)
        if self.options['fab_pdf']:
            self.export_fab_pdfs(directory)
        self.pack(directory, 'smt_package')

    def export_fab_pdfs(self, directory):
        import pcbnew
        for kind, layer, mirror in [('fab_front', pcbnew.F_Fab, False), ('fab_back', pcbnew.B_Fab, True)]:
            # KiCad's automatic scale follows visible layers. Restore the local
            # visibility file even if the native exporter fails.
            with temporary_visible_layers(self.project.board, [layer, pcbnew.Edge_Cuts]):
                self.native.pdf(self.project.board, self.path(kind, directory),
                                [pcbnew.BOARD.GetStandardLayerName(layer), 'Edge.Cuts'],
                                fab=True, mirror=mirror)

    def export_pcb_pdf(self, outline):
        import pcbnew
        layers = [pcbnew.BOARD.GetStandardLayerName(i) for i in self.board.GetEnabledLayers().CuStack()]
        layers += ['F.SilkS', 'B.SilkS', 'F.Paste', 'B.Paste', 'F.Mask', 'B.Mask', 'F.Fab', 'B.Fab']
        self.native.pdf(self.project.board, self.path('pcb_pdf'), layers,
                        worksheet=self.project.worksheet('pcb'),
                        common_layers=[pcbnew.BOARD.GetStandardLayerName(i) for i in outline])

    def export_schematic_pdf(self):
        destination = self.path('schematic_pdf')
        args = ['--output', destination]
        worksheet = self.project.worksheet('sch')
        if worksheet:
            args += ['--drawing-sheet', worksheet]
        self.native.run(['sch', 'export', 'pdf'], [*args, *self.native.definitions(), self.project.schematic])
        require_file(destination)

    def export_step(self, kind):
        destination = self.path('step_' + kind)
        args = ['--output', destination, *STEP_COMMON]
        if kind == 'full':
            args += STEP_FULL
        self.native.run(['pcb', 'export', 'step'], [*args, self.project.board])
        require_file(destination)


def gerber_layers(board, options):
    import pcbnew
    enabled = list(board.GetEnabledLayers().Seq())
    standard = [*board.GetEnabledLayers().CuStack(), pcbnew.F_SilkS, pcbnew.B_SilkS,
                pcbnew.F_Mask, pcbnew.B_Mask, pcbnew.F_Paste, pcbnew.B_Paste, pcbnew.Edge_Cuts]
    layers = list(enabled) if options['all_active_layers'] else [i for i in standard if i in enabled]
    custom = layer_names(board)
    for name in options['extra_layers'].split(','):
        name = name.strip()
        if not name:
            continue
        match = next((i for i in enabled if pcbnew.BOARD.GetStandardLayerName(i) == name), custom.get(name))
        if match is None:
            raise ExportError(f'Additional layer not found: {name}')
        if match not in layers:
            layers.append(match)
    return list(dict.fromkeys(layers))
