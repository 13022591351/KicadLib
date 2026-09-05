"""KiCad entry point. Importing the CLI never imports wx or registers a GUI."""
import sys

if __package__ and 'pcbnew' in sys.modules:
    try:
        import wx
        if wx.GetApp() is not None:
            from .gui import ExportToolkitPlugin
            ExportToolkitPlugin().register()
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Export-Toolkit registration failed')
