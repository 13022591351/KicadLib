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
from .gui_log import LogSummary, append_output, log_styles

HERE = Path(__file__).resolve().parent
OUTPUTS = [
    ('pcb_package', 'PCB fabrication package (.7z)'),
    ('smt_package', 'SMT package: BOM and POS (.7z)'),
    ('schematic_pdf', 'Schematic PDF with drawing sheets'),
    ('pcb_pdf', 'PCB PDF with drawing sheets'),
    ('fab_pdf', 'F.Fab + mirrored B.Fab inspection PDFs'),
    ('step_lite', 'STEP lite: board + components'),
    ('step_full', 'STEP full: board + components + copper'),
]
PROCESSING = [
    ('alternative_edge', 'Use Fab.EdgeCuts for manufacturing'),
    ('vcut', 'Overlay Fab.VCut'),
    ('auto_translate', 'Automatic placement corrections'),
    ('all_active_layers', 'All enabled Gerber layers'),
    ('strict', 'Strict checks for MPN'),
    ('open_output', 'Open release folder after export'),
]
TOOLTIPS = {
    'pcb_pdf': 'Color multipage PDF: all copper layers, front/back silk, paste, mask and Fab, with drawing sheets.',
    'fab_pdf': 'Two inspection PDFs: F.Fab and mirrored B.Fab, with Edge.Cuts, automatic scale and no drawing sheet.',
    'step_full': 'Board, components, copper, via holes, silkscreen and solder mask.',
    'alternative_edge': 'Replace Edge.Cuts with Fab.EdgeCuts for manufacturing outputs.',
    'vcut': 'Overlay Fab.VCut after selecting the manufacturing outline.',
}


class ExportDialog(wx.Dialog):
    def __init__(self, board, project):
        super().__init__(None, title='Export-Toolkit', size=(1120, 820),
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
        self.history = wx.StaticText(self, label=label,
                                      style=wx.ALIGN_RIGHT | wx.ST_ELLIPSIZE_MIDDLE | wx.ST_NO_AUTORESIZE)
        self.history.SetMinSize((1, -1))
        self.history.SetToolTip(label)
        header.Add(self.history, 1, wx.ALIGN_CENTER_VERTICAL)
        layout.Add(header, 0, wx.EXPAND | wx.ALL, 12)
        columns = wx.BoxSizer(wx.HORIZONTAL)
        self.options_panel = wx.ScrolledWindow(self, style=wx.VSCROLL)
        self.options_panel.SetScrollRate(0, 12)
        option_layout = wx.BoxSizer(wx.VERTICAL)
        for label, definitions in [('Outputs', OUTPUTS), ('Processing', PROCESSING)]:
            section = wx.StaticBoxSizer(wx.VERTICAL, self.options_panel, label)
            for key, title in definitions:
                control = wx.CheckBox(self.options_panel, label=title)
                control.SetValue(self.options[key])
                if key in TOOLTIPS:
                    control.SetToolTip(TOOLTIPS[key])
                self.controls[key] = control
                section.Add(control, 0, wx.ALL, 5)
            option_layout.Add(section, 0, wx.EXPAND | wx.BOTTOM, 10)
        self.options_panel.SetSizer(option_layout)
        columns.Add(self.options_panel, 0, wx.EXPAND | wx.RIGHT, 16)
        self.text_panel = wx.Panel(self)
        text_layout = wx.BoxSizer(wx.VERTICAL)
        extra = wx.BoxSizer(wx.HORIZONTAL)
        extra.Add(wx.StaticText(self.text_panel, label='Additional Gerber layers:'),
                  0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.extra = wx.TextCtrl(self.text_panel, value=self.options['extra_layers'])
        self.extra.SetHint('Comma-separated layer names')
        extra.Add(self.extra, 1)
        text_layout.Add(extra, 0, wx.EXPAND | wx.BOTTOM, 12)
        text_layout.Add(wx.StaticText(self.text_panel, label="What's Changed (RELEASE_NOTES.md):"),
                        0, wx.BOTTOM, 6)
        self.notes = wx.TextCtrl(self.text_panel, value=load_notes(project.file.parent), style=wx.TE_MULTILINE)
        self.notes.SetMinSize((-1, 120))
        text_layout.Add(self.notes, 1, wx.EXPAND | wx.BOTTOM, 12)
        self.output_path = wx.StaticText(self.text_panel, label=f'Output: {project.release_dir}',
                                         style=wx.ST_ELLIPSIZE_MIDDLE)
        self.output_path.SetMinSize((1, -1))
        self.output_path.SetToolTip(str(project.release_dir))
        text_layout.Add(self.output_path, 0, wx.EXPAND | wx.BOTTOM, 10)
        self.log = wx.TextCtrl(self.text_panel, style=wx.TE_MULTILINE | wx.TE_READONLY
                               | wx.TE_DONTWRAP | wx.TE_RICH2)
        self.log.SetFont(wx.Font(wx.FontInfo(self.GetFont().GetPointSize()).Family(wx.FONTFAMILY_TELETYPE)))
        self.log.SetMinSize((-1, 200))
        self.log_styles = log_styles(self.log.GetForegroundColour(), self.log.GetBackgroundColour())
        self.log_summary = LogSummary()
        self.summary_fields = {}
        self.summary_box = wx.StaticBoxSizer(wx.VERTICAL, self.options_panel, 'Run summary')
        summary_parent = self.summary_box.GetStaticBox()
        table = wx.FlexGridSizer(rows=5, cols=2, vgap=6, hgap=14)
        table.AddGrowableCol(0, 1)
        summary_rows = [('steps', 'Steps'), ('warnings', 'Warnings'), ('errors', 'Errors'),
                        ('added', 'Git +'), ('removed', 'Git −')]
        fields = self.log_summary.fields()
        def add_cell(text, role, value=False):
            item = wx.StaticText(summary_parent, label=text, style=(wx.ALIGN_RIGHT if value else wx.ALIGN_LEFT)
                                  | wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)
            item.SetForegroundColour(self.log_styles[role].GetTextColour())
            if value:
                item.SetMinSize((64, -1))
                item.SetFont(item.GetFont().Bold())
            table.Add(item, 0, wx.EXPAND)
            return item
        for key, title in summary_rows:
            value, role = fields[key]
            add_cell(title, role)
            self.summary_fields[key] = add_cell(value, role, value=True)
        self.summary_fields['steps'].SetToolTip('Native operations started in the displayed run.')
        self.summary_fields['warnings'].SetToolTip('Active check warnings plus explicit export warnings.')
        self.summary_fields['errors'].SetToolTip('Active check errors, or one failure if the operation could not complete.')
        self.summary_fields['added'].SetToolTip('Git lines added; a dash means no Git diff has been reported.')
        self.summary_fields['removed'].SetToolTip('Git lines deleted; a dash means no Git diff has been reported.')
        self.summary_box.Add(table, 0, wx.EXPAND | wx.ALL, 12)
        option_layout.Add(self.summary_box, 0, wx.EXPAND | wx.BOTTOM, 10)
        self.options_panel.SetMinSize((option_layout.GetMinSize().GetWidth() + 18, -1))
        text_layout.Add(self.log, 3, wx.EXPAND | wx.BOTTOM, 10)
        self.gauge = wx.Gauge(self.text_panel)
        text_layout.Add(self.gauge, 0, wx.EXPAND)
        self.text_panel.SetSizer(text_layout)
        columns.Add(self.text_panel, 1, wx.EXPAND)
        layout.Add(columns, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.generate = wx.Button(self, label='Export')
        self.close = wx.Button(self, wx.ID_CANCEL, label='Close')
        self.check = wx.Button(self, label='ERC / DRC + Save')
        self.check.SetToolTip('Run ERC, then DRC with schematic parity and zone refill. '
                              'KiCad saves the refilled PCB even when DRC reports errors.')
        left_buttons = wx.BoxSizer(wx.HORIZONTAL)
        left_buttons.SetMinSize((self.options_panel.GetMinSize().GetWidth(), -1))
        left_buttons.Add(self.check, 0)
        buttons.Add(left_buttons, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 16)
        right_buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.activity = wx.StaticText(self, label='Ready',
                                      style=wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)
        self.activity.SetMinSize((150, -1))
        right_buttons.Add(self.activity, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        right_buttons.Add(self.close, 0, wx.RIGHT, 6)
        right_buttons.Add(self.generate, 0)
        buttons.Add(right_buttons, 1, wx.ALIGN_CENTER_VERTICAL)
        layout.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizer(layout)
        self.SetMinSize((1000, 700))
        # Size the initial window around its contents rather than reserving a
        # fixed tall canvas. The left pane can still scroll when resized smaller.
        body_height = max(option_layout.GetMinSize().GetHeight(), text_layout.GetMinSize().GetHeight())
        client_height = header.GetMinSize().GetHeight() + body_height + buttons.GetMinSize().GetHeight() + 48
        self.SetClientSize((self.GetClientSize().GetWidth(), client_height))
        self.Layout()
        self.options_panel.FitInside()
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

    def refresh_history(self):
        label = last_check_label(load_last_check(self.project.file.parent))
        self.history.SetLabel(label)
        self.history.SetToolTip(label)
        self.Layout()

    def refresh_summary(self):
        for key, (label, role) in self.log_summary.fields().items():
            control = self.summary_fields[key]
            control.SetLabel(label)
            control.SetForegroundColour(self.log_styles[role].GetTextColour())
        self.options_panel.Layout()
        self.options_panel.FitInside()

    def reset_output(self):
        self.log.Clear()
        self.log_summary = LogSummary()
        self.refresh_summary()

    def run_job(self, *, export):
        if self.busy:
            return
        code = 1
        report = {}
        options = {}
        current_editor = None
        self.disabled_windows = None
        try:
            # Reset this run before any dependency, filesystem or project check
            # can fail. Historical success time and the saved PCB baseline stay.
            self.begin_export(export=export)
            check_dependencies(gui=True)
            options = {key: control.GetValue() for key, control in self.controls.items()}
            options['extra_layers'] = self.extra.GetValue()
            if export:
                save_options(self.project.file.parent, options)
                save_user_notes(self.project.file.parent, self.notes.GetValue())
            self.project = Project.open(self.project.file, self.project.board, self.project.schematic)
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
            log_exception(exc, self.append_error, report)
        finally:
            try:
                if report.get('board_saved'):
                    self.saved_editor_content = current_editor
                    self.append_log('DRC saved the refilled PCB. Export will use this saved file. '
                                    'Reload it in PCB Editor before further editing.')
                self.refresh_history()
            except Exception as exc:
                code = 1
                log_exception(exc, self.append_error, report)
            finally:
                del self.disabled_windows
                self.finished(code, options, export=export)

    def begin_export(self, *, export=True):
        self.busy = True
        self.reset_output()
        self.gauge.SetValue(0)
        self.SetTitle('Export-Toolkit — ' + ('Exporting' if export else 'Checking'))
        self.activity.SetLabel('Exporting...' if export else 'Running ERC / DRC...')
        self.activity.SetForegroundColour(self.log_styles['section'].GetTextColour())
        for control in [*self.controls.values(), self.extra, self.notes, self.check,
                        self.generate, self.close]:
            control.Enable(False)
        self.timer.Start(120)
        # Board operations stay on the GUI thread; SafeYield during child
        # processes keeps this dialog responsive while editor windows are disabled.
        self.disabled_windows = wx.WindowDisabler(self)

    def append_log(self, message, level=None):
        append_output(self.log, message, self.log_styles, level)
        stage = self.log_summary.observe(message, level)
        self.refresh_summary()
        if self.busy and stage:
            self.activity.SetLabel(stage)
            self.activity.Update()

    def append_error(self, message):
        self.append_log(message, level='error')

    def finished(self, code, options, *, export=True):
        self.timer.Stop()
        self.gauge.SetValue(100 if code == 0 else 0)
        self.busy = False
        for control in [*self.controls.values(), self.extra, self.notes, self.check,
                        self.generate, self.close]:
            control.Enable(True)
        self.sync_controls()
        self.SetTitle('Export-Toolkit — ' + ('Complete' if code == 0 else 'Failed'))
        self.activity.SetLabel(('Export complete' if export else 'Checks passed') if code == 0
                               else ('Export failed' if export else 'Checks failed'))
        self.activity.SetForegroundColour(self.log_styles['success' if code == 0 else 'error'].GetTextColour())
        if export and code == 0 and options['open_output']:
            if not wx.LaunchDefaultApplication(str(self.project.release_dir)):
                self.append_log('WARNING: Could not open the release folder in the system file manager.')


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
