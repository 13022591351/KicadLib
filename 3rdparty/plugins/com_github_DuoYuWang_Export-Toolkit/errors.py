"""Expected export failures and shared GUI/CLI diagnostics."""
import traceback


class ExportError(RuntimeError):
    """An actionable validation, dependency or native export failure."""


def log_exception(exc, log, report=None):
    """Keep expected failures concise and retain unexpected exception tracebacks."""
    # Filesystem errors already identify the operation/path and remain actionable
    # even when raised directly by Python's file or directory functions.
    expected = isinstance(exc, (ExportError, OSError))
    details = None if expected else ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    if report is not None:
        report.update(success=False, error=str(exc))
        report.pop('traceback', None)
        if details:
            report['traceback'] = details
    log(f'Export-Toolkit: {exc}')
    if details:
        log(details.rstrip())
