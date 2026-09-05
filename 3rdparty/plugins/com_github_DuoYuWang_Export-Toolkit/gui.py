"""KiCad toolbar UI; native board operations stay on the editor's main thread."""
from pathlib import Path
import sys

import pcbnew
import wx

from .config import load_options, save_options, load_last_check, last_check_label
from .boards import board_content
from .checks import check_project
from .dependencies import check_dependencies
from .errors import ExportError, log_exception
from .core import export_project
from .project import Project
from .release import load_notes, save_user_notes

HERE = Path(__file__).resolve().parent
OUTPUTS = [
    ('pcb_package', 'PCB fabrication package (.7z)'),
    ('smt_package', 'SMT package: BOM and POS (.7z)'),
    ('schematic_pdf', 'Schematic PDF with drawing sheets'),
    ('pcb_pdf', 'PCB PDF: all copper and manufacturing layers'),
    ('fab_pdf', 'SMT inspection PDFs: F.Fab and mirrored B.Fab'),
    ('step_lite', 'STEP lite: board and components'),
    ('step_full', 'STEP full: board, parts, copper, holes, silk, mask'),
]
PROCESSING = [
    ('alternative_edge', 'Replace Edge.Cuts with Fab.EdgeCuts'),
    ('vcut', 'Overlay Fab.VCut after outline selection'),
    ('auto_translate', 'Apply automatic placement corrections'),
    ('all_active_layers', 'Export all enabled Gerber layers'),
    ('strict', 'Strict checks for MPN'),
    ('open_output', 'Open release folder after export'),
]


class ExportDialog(wx.Dialog):
    def __init__(self, board, project):
        super().__init__(None, title='Export-Toolkit', size=(790, 840),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.board, self.project = board, project
        self.busy = False
        self.saved_editor_content = None
        self.controls = {}
        self.options = load_options(project.file.parent)
        layout = wx.BoxSizer(wx.VERTICAL)
        header = wx.BoxSizer(wx.HORIZONTAL)
        heading = wx.StaticText(self, label=f'{project.name}  |  PCB {project.pcb_revision}  |  SCH {project.sch_revision}')
        header.Add(heading, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        label = last_check_label(load_last_check(project.file.parent))
        self.history = wx.StaticText(self, label=label, style=wx.ALIGN_RIGHT | wx.ST_ELLIPSIZE_MIDDLE)
        self.history.SetMinSize((1, -1))
        self.history.SetToolTip(label)
        header.Add(self.history, 1, wx.ALIGN_CENTER_VERTICAL)
        layout.Add(header, 0, wx.EXPAND | wx.ALL, 12)
        layout.Add(wx.StaticText(self, label='Save the schematic and PCB first. Run checks separately; Export uses saved files.'),
                   0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        columns = wx.BoxSizer(wx.HORIZONTAL)
        for label, definitions in [('Outputs', OUTPUTS), ('Processing', PROCESSING)]:
            section = wx.StaticBoxSizer(wx.VERTICAL, self, label)
            for key, title in definitions:
                control = wx.CheckBox(self, label=title)
                control.SetValue(self.options[key])
                self.controls[key] = control
                section.Add(control, 0, wx.ALL, 5)
            columns.Add(section, 1, wx.EXPAND | wx.ALL, 6)
        layout.Add(columns, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        extra = wx.BoxSizer(wx.HORIZONTAL)
        extra.Add(wx.StaticText(self, label='Additional Gerber layers:'), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.extra = wx.TextCtrl(self, value=self.options['extra_layers'])
        self.extra.SetHint('Comma-separated layer names')
        extra.Add(self.extra, 1)
        layout.Add(extra, 0, wx.EXPAND | wx.ALL, 12)
        layout.Add(wx.StaticText(self, label='Changes (project RELEASE_NOTES.md):'), 0, wx.LEFT | wx.RIGHT, 12)
        self.notes = wx.TextCtrl(self, value=load_notes(project.file.parent), style=wx.TE_MULTILINE)
        layout.Add(self.notes, 1, wx.EXPAND | wx.ALL, 12)
        layout.Add(wx.StaticText(self, label=f'Output: {project.release_dir}'), 0, wx.LEFT | wx.RIGHT, 12)
        self.log = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        self.log.SetMinSize((-1, 120))
        layout.Add(self.log, 1, wx.EXPAND | wx.ALL, 12)
        self.gauge = wx.Gauge(self)
        layout.Add(self.gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.generate = wx.Button(self, label='Export')
        self.close = wx.Button(self, wx.ID_CANCEL, label='Close')
        self.check = wx.Button(self, label='ERC / DRC + Save')
        self.check.SetToolTip('Run ERC, then DRC with schematic parity and zone refill. '
                              'KiCad saves the refilled PCB even when DRC reports errors.')
        buttons.Add(self.check, 0, wx.ALL, 6)
        buttons.AddStretchSpacer()
        buttons.Add(self.close, 0, wx.ALL, 6)
        buttons.Add(self.generate, 0, wx.ALL, 6)
        layout.Add(buttons, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(layout)
        self.SetMinSize((760, 720))
        self.Centre()
        self.controls['smt_package'].Bind(wx.EVT_CHECKBOX, self.sync_controls)
        self.generate.Bind(wx.EVT_BUTTON, self.on_export)
        self.check.Bind(wx.EVT_BUTTON, self.on_check)
        self.close.Bind(wx.EVT_BUTTON, self.on_close)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda event: self.gauge.Pulse(), self.timer)
        self.sync_controls()

    def sync_controls(self, event=None):
        self.controls['fab_pdf'].Enable(not self.busy and self.controls['smt_package'].GetValue())

    def on_close(self, event):
        if self.busy:
            return
        self.Destroy()

    def on_export(self, event):
        self.run_job(export=True)

    def on_check(self, event):
        self.run_job(export=False)

    def run_job(self, *, export):
        try:
            check_dependencies(gui=True)
            options = {key: control.GetValue() for key, control in self.controls.items()}
            options['extra_layers'] = self.extra.GetValue()
            if export:
                save_options(self.project.file.parent, options)
                save_user_notes(self.project.file.parent, self.notes.GetValue())
            self.project = Project.open(self.project.file, self.project.board, self.project.schematic)
            code = 1
            report = {}
            self.disabled_windows = None
            try:
                self.begin_export()
                current_editor = board_content(self.board)
                # A preceding check can have saved new fills through the CLI.
                # Keep using those saved inputs while the editor still matches
                # the pre-check contents; never save the stale editor over them.
                editor = None if self.saved_editor_content == current_editor else self.board
                kwargs = dict(board=editor, log=self.append_log, report=report,
                              heartbeat=lambda: wx.SafeYield(self, True))
                if export:
                    export_project(self.project, options, notes=self.notes.GetValue(), **kwargs)
                else:
                    check_project(self.project, **kwargs)
                code = 0
            except Exception as exc:
                log_exception(exc, self.append_log, report)
            finally:
                if report.get('board_saved'):
                    self.saved_editor_content = current_editor
                    self.append_log('DRC saved the refilled PCB. Export will use this saved file. '
                                    'Reload it in PCB Editor before further editing.')
                label = last_check_label(load_last_check(self.project.file.parent))
                self.history.SetLabel(label)
                self.history.SetToolTip(label)
                del self.disabled_windows
                self.finished(code, options, export=export)
        except Exception as exc:
            log_exception(exc, self.append_log)
            wx.MessageBox(str(exc), 'Export-Toolkit', wx.OK | wx.ICON_ERROR, self)

    def begin_export(self):
        self.busy = True
        self.log.Clear()
        for control in [*self.controls.values(), self.extra, self.notes, self.check, self.generate, self.close]:
            control.Enable(False)
        self.timer.Start(120)
        # Board operations stay on the GUI thread; SafeYield during child
        # processes keeps this dialog responsive while editor windows are disabled.
        self.disabled_windows = wx.WindowDisabler(self)

    def append_log(self, message):
        self.log.AppendText(message + '\n')
        self.log.Update()

    def finished(self, code, options, *, export=True):
        self.timer.Stop()
        self.gauge.SetValue(100 if code == 0 else 0)
        self.busy = False
        for control in [*self.controls.values(), self.extra, self.notes, self.check, self.generate, self.close]:
            control.Enable(True)
        self.sync_controls()
        self.SetTitle('Export-Toolkit — ' + ('Complete' if code == 0 else 'Failed'))
        if export and code == 0 and options['open_output']:
            if not wx.LaunchDefaultApplication(str(self.project.release_dir)):
                self.log.AppendText('Could not open the release folder in the system file manager.\n')


class ExportToolkitPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = 'Export-Toolkit'
        self.category = 'Manufacturing'
        self.description = 'Native KiCad fabrication, assembly, PDF and STEP release exports'
        self.show_toolbar_button = True
        self.icon_file_name = str(HERE / 'icon.png')
        self.dark_icon_file_name = str(HERE / 'icon.png')

    def Run(self):
        try:
            check_dependencies(gui=True)
            board = pcbnew.GetBoard()
            if not board or not board.GetFileName():
                raise ExportError('Save the PCB and schematic in a KiCad project before exporting.')
            project = Project.open(Path(board.GetFileName()).with_suffix('.kicad_pro'))
            ExportDialog(board, project).Show()
        except Exception as exc:
            log_exception(exc, lambda message: print(message, file=sys.stderr))
            wx.MessageBox(str(exc), 'Export-Toolkit', wx.OK | wx.ICON_ERROR)
