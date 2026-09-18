"""Individual native exports and the shared release naming/STEP conventions."""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .boards import layer_names, plot_gerbers, plot_fab_pdf, write_drills_and_job
from .native import Native, archive, merge_pdfs, pdf_info, require_file
from .project import Project
from .tables import adapt_tables
from .errors import ExportError
from .worksheets import document_worksheet, numbered_worksheet, prepare_worksheet
from .pdf_fonts import deduplicate_pdf_fonts

OUTPUT_NAMES = {
    'pcb_package': ('PCB', 'pcb_revision', '7z'),
    'smt_package': ('SMT', 'sch_revision', '7z'),
    'pcb_pdf': ('PCB', 'pcb_revision', 'pdf'),
    'pcba_pdf': ('PCBA', 'sch_revision', 'pdf'),
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

    def optimize_pdf(self, path):
        deduplicate_pdf_fonts(path, self.log, heartbeat=self.heartbeat)

    def export_pcb_package(self, outline):
        directory = self.work / 'fabrication'
        directory.mkdir()
        layers = gerber_layers(self.board, self.options)
        self.log('KiCad: plotting Gerbers, drills, drill maps and Gerber job.')
        gerbers = plot_gerbers(self.board, directory, layers, outline, self.heartbeat)
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
            if self.heartbeat:
                self.heartbeat()
            self.log('KiCad: plotting ' + kind + ' PDF (in-memory visibility).')
            plot_fab_pdf(self.board, self.path(kind, directory), layer, mirror)
            self.optimize_pdf(self.path(kind, directory))

    def export_pcb_pdf(self, outline):
        import pcbnew
        from .drill_maps import native_maps, map_board, save_map_board
        layers = [pcbnew.BOARD.GetStandardLayerName(i) for i in self.board.GetEnabledLayers().CuStack()]
        layers += ['F.SilkS', 'B.SilkS', 'F.Paste', 'B.Paste', 'F.Mask', 'B.Mask', 'F.Fab', 'B.Fab']
        self.log('KiCad: generating drill map drawings for the PCB document.')
        maps = native_maps(self.board, self.work / 'drill-maps', outline)
        worksheet = document_worksheet(self.project, self.work, self.native.executable)
        total = len(layers) + len(maps)
        layer_pdf = self.work / 'pcb-layers.pdf'
        self.native.pdf(self.project.board, layer_pdf, layers,
                        worksheet=numbered_worksheet(worksheet, self.work, total),
                        common_layers=[pcbnew.BOARD.GetStandardLayerName(i) for i in outline])
        count, _ = pdf_info(layer_pdf)
        if count != len(layers):
            raise ExportError(f'Expected {len(layers)} PCB layer pages; KiCad produced {count}.')
        pages = [layer_pdf]
        for page, (label, dxf) in enumerate(maps, len(layers) + 1):
            drawing = map_board(self.board, dxf, label)
            document = save_map_board(drawing, self.project, self.work / f'drill-page-{page}')
            pdf = document.parent / 'drill.pdf'
            self.log(f'KiCad: drill map {label}, sheet {page}/{total}, scale 1:1, original PCB coordinates.')
            self.native.pdf(document, pdf, ['User.1'], common_layers=[],
                            worksheet=numbered_worksheet(worksheet, self.work, total, page))
            if pdf_info(pdf)[0] != 1:
                raise ExportError(f'Expected one PDF page for the {label} drill map.')
            pages.append(pdf)
        merge_pdfs(pages, self.path('pcb_pdf'), heartbeat=self.heartbeat)
        if pdf_info(self.path('pcb_pdf'))[0] != total:
            raise ExportError('Assembled PCB PDF page count does not match the drawing sheets.')
        self.optimize_pdf(self.path('pcb_pdf'))
        self.log(f'PCB PDF assembled: {total} sheets with matching drawing sheets and continuous numbering.')

    def export_schematic_pdf(self):
        destination = self.path('schematic_pdf')
        args = ['--output', destination, '--no-background-color']
        worksheet = prepare_worksheet(self.project, 'sch', self.work)
        if worksheet:
            args += ['--drawing-sheet', worksheet]
        self.native.run(['sch', 'export', 'pdf'], [*args, *self.native.definitions(), self.project.schematic])
        require_file(destination)
        self.optimize_pdf(destination)

    def export_pcba_pdf(self):
        """Two composite pages, with export-only SCH Revision and Comment 1."""
        directory = self.work / 'pcba'
        directory.mkdir()
        worksheet = document_worksheet(self.project, directory, self.native.executable)
        pages = []
        for number, side in enumerate(('F', 'B'), start=1):
            pdf = directory / f'{side}.pdf'
            self.log(f'KiCad: PCBA {side} page {number}/2, scale 1:1, original PCB coordinates.')
            # KiCad labels a composite plot using its first layer. Keep Fab
            # first for the drawing-sheet layer identity; retain silk overlay.
            self.native.pdf(self.project.board, pdf,
                            [f'{side}.Fab', f'{side}.SilkS', 'Edge.Cuts', 'Dwgs.User'],
                            common_layers=[], single_page=True,
                            worksheet=numbered_worksheet(worksheet, directory, 2, number,
                                                         comment1=self.options['pcba_comment'],
                                                         revision=self.project.sch_revision))
            if pdf_info(pdf)[0] != 1:
                raise ExportError(f'Expected one composite PCBA {side} page.')
            pages.append(pdf)
        destination = self.path('pcba_pdf')
        merge_pdfs(pages, destination, heartbeat=self.heartbeat)
        if pdf_info(destination)[0] != 2:
            raise ExportError('Expected exactly two PCBA PDF pages.')
        self.optimize_pdf(destination)
        self.log('PCBA PDF assembled: 2 framed, black-and-white sheets at 1:1.')

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
