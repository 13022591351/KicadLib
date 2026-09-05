"""Presentation of native output in the GUI; CLI output remains plain text."""
import re
from dataclasses import dataclass, field

import wx

CHECK_COUNTS = re.compile(r'^(?:ERC|SYNC|DRC): (\d+) error\(s\), (\d+) warning\(s\)\.')
GIT_COUNTS = re.compile(r'^(\s+".*"\s+)(\+\d+)(\s+)(-\d+)(\s*)$')
STAGE_NAMES = {
    'sch erc': 'ERC', 'pcb drc': 'DRC / schematic parity',
    'sch export pdf': 'Schematic PDF', 'pcb export pdf': 'PCB / Fab PDF',
    'pcb export pos': 'Placement data', 'pcb export ipcd356': 'IPC netlist',
    'pcb export step': 'STEP model',
}


@dataclass
class LogSummary:
    """Counters for this displayed run, separate from the persisted success time."""
    steps: int = 0
    checks: dict = field(default_factory=dict)
    export_warnings: int = 0
    failed: bool = False
    git_seen: bool = False
    added: int = 0
    removed: int = 0

    def observe(self, message, level=None):
        stage = None
        if level == 'error':
            self.failed = True
            return stage
        for line in message.splitlines():
            text = line.strip()
            counts = CHECK_COUNTS.match(text)
            if counts:
                self.checks[text.split(':', 1)[0]] = (int(counts[1]), int(counts[2]))
            elif text.startswith('WARNING:'):
                self.export_warnings += 1
            if text.startswith('KiCad: '):
                self.steps += 1
                command = text[len('KiCad: '):]
                stage = STAGE_NAMES.get(command, 'Fabrication plots' if command.startswith('plotting Gerbers')
                                        else command)
            elif text.startswith('Git diff against HEAD'):
                self.git_seen = True
                stage = 'Git changes'
            elif text.startswith('All selected exports completed.'):
                stage = 'Publishing release'
            git = GIT_COUNTS.match(line)
            if git:
                self.git_seen = True
                self.added += int(git[2])
                self.removed += -int(git[4])
        return stage

    def fields(self):
        errors = sum(result[0] for result in self.checks.values()) or int(self.failed)
        warnings = sum(result[1] for result in self.checks.values()) + self.export_warnings
        return {
            'steps': (str(self.steps), 'section'),
            'warnings': (str(warnings), 'warning'),
            'errors': (str(errors), 'error'),
            'added': (str(self.added) if self.git_seen else '—',
                      'success' if self.added else 'info'),
            'removed': (str(self.removed) if self.git_seen else '—', 'error' if self.removed else 'info'),
        }


def log_role(line):
    text = line.strip()
    counts = CHECK_COUNTS.match(text)
    if counts:
        return 'error' if int(counts[1]) else 'warning' if int(counts[2]) else 'success'
    lower = text.lower()
    if lower.startswith(('error:', 'fatal:', 'traceback ', 'export-toolkit:')):
        return 'error'
    if lower.startswith(('warning:', 'warn:')):
        return 'warning'
    if text.startswith(('KiCad:', 'Git diff against HEAD', 'All selected exports completed.')):
        return 'section'
    if lower.startswith(('published:', 'archive verified:', 'plotted to ', 'saved board',
                         'saved erc report', 'saved drc report')) or text.endswith('PCB has been saved.'):
        return 'success'
    return 'info'


def log_styles(foreground, background):
    light = (background.Red() * 0.2126 + background.Green() * 0.7152
             + background.Blue() * 0.0722) > 128
    colors = ({'section': '#1d4ed8', 'success': '#087f5b', 'warning': '#9a5700', 'error': '#b42318'}
              if light else
              {'section': '#8ab4f8', 'success': '#83d5a6', 'warning': '#f7c66b', 'error': '#ff9b9b'})
    styles = {}
    for role, color in {'info': foreground, **colors}.items():
        style = wx.TextAttr(wx.Colour(color))
        style.SetFontWeight(wx.FONTWEIGHT_BOLD if role in ('section', 'error') else wx.FONTWEIGHT_NORMAL)
        styles[role] = style
    return styles


def append_output(control, message, styles, level=None):
    """Color each line without changing the text, indentation or traceback."""
    control.Freeze()
    try:
        for line in (message + '\n').splitlines(keepends=True):
            counts = GIT_COUNTS.match(line) if level is None else None
            if counts:
                parts = zip(('info', 'success', 'info', 'error', 'info'), counts.groups())
            else:
                parts = [(level or log_role(line), line)]
            for role, text in parts:
                control.SetDefaultStyle(styles[role])
                control.AppendText(text)
        control.SetDefaultStyle(styles['info'])
    finally:
        control.Thaw()
    control.ShowPosition(control.GetLastPosition())
    control.Update()
