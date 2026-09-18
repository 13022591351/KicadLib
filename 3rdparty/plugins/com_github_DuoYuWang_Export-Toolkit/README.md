# Export-Toolkit

Production release exports for KiCad 10 on Unix-like systems. The PCB toolbar
and CLI share the same options and export workflow. All PDFs, STEP models,
Gerbers, drills, IPC netlists and source POS tables come from KiCad's native
exporters. BOM and final POS data come from PCB footprints through KiCad's
Python API, with configurable component placement corrections.

## Requirements and startup

- KiCad 10 with `kicad-cli` and its `pcbnew` Python module.
- `wxPython` for the toolbar dialog; the CLI does not create a window.
- `7zz` or `7z` with 7z format support.
- System `libzstd` for reading embedded drawing sheets; checked at startup.
- Poppler's `pdfunite` and `pdfinfo` for PCB/PCBA PDF assembly (`poppler-utils` on
  Debian/Ubuntu). These are checked before export when either PDF is selected.
  KiCad renders every page and drawing sheet; Poppler reads page sizes/counts
  and concatenates the vector pages. Other output selections do not need Poppler.
- PyMuPDF in KiCad's Python environment for PDF font deduplication. Checked
  before generating any selected PDF (including Fab PDFs in an SMT package).
  No runtime installation is attempted. Gerber/BOM/POS/STEP-only exports do not
  require it. Existing `pymupdf` or compatible `fitz` imports are supported.

Keep this directory in KiCad's third-party `plugins/` directory and the matching
icon directory in `resources/`. Refresh action plugins or reopen the PCB Editor
to find **Export-Toolkit** on the toolbar / External Plugins menu.

Run the CLI with a Python interpreter that can import KiCad's `pcbnew`:

```sh
python3 /path/to/com_github_DuoYuWang_Export-Toolkit/cli.py check
python3 /path/to/com_github_DuoYuWang_Export-Toolkit/cli.py export \
  --project /path/to/Board/Board.kicad_pro
```

Startup checks dependencies. `EXPORT_TOOLKIT_KICAD_CLI` and `EXPORT_TOOLKIT_7Z`
can select executables. The toolbar uses KiCad's embedded Python and loaded PCB.
The archiver must be installed on the system;
the plugin does not include a `bin/` directory or download executable tools.

The interface and export messages use English. The log displays native KiCad
CLI output using a temporary copy of your settings with English selected.
Your KiCad interface language, library paths and color themes are preserved.

The dialog stacks Outputs and Processing on the left, with release notes and
output text on the right. Its initial height fits the contents and remains
resizable. A **Run summary** box below the options has five rows
and two columns: labels on the left and live values on the right for Steps,
Warnings, Errors, Git additions and Git deletions. The output view uses a monospace font and colors
for steps, successes, warnings and errors. Counters update during the action;
the current stage appears below the log, beside Close and Export.
Starting an action resets the displayed log and counters, preserving the last
successful check time.
The CLI continues to print plain text.

Drawing sheets may be embedded or referenced by a path such as
`${KICAD_DYW_DIR}/template/My-Sheet.kicad_wks`. Path variables are read
from KiCad Configure Paths and the process environment.

KiCad 10's built-in `VCSHASH` and `VCSSHORTHASH` take precedence over CLI variable
overrides, and the CLI can render them as `no hash` even in a Git project.
For these fields, Toolkit prepares an export-only drawing sheet in the work
directory with ordinary text-variable names and passes the Git HEAD value via
KiCad's native `--drawing-sheet` and `--define-var` options. Original external
and embedded sheets remain unchanged, including their built-in VCS tokens.
The short ID is eight characters; the full ID matches the release notes.
Without Git or a HEAD commit, the fields display `no hash`. No commits are created.

## Options

`export-toolkit-options.json` lives beside the project. The dialog loads it at
startup and saves it when **Export** is pressed. The CLI loads the same file;
explicit command-line arguments override it for that invocation. Add
`--save-options` to persist CLI changes. A different JSON can be selected with
`--config`.

| JSON option | Default | Meaning |
| --- | --- | --- |
| `pcb_package` | `true` | PCB fabrication 7z, including NET |
| `smt_package` | `true` | BOM/POS and optional Fab PDFs in an SMT 7z |
| `schematic_pdf` | `true` | All schematic pages with drawing sheets, original foreground colors and no page background color |
| `pcb_pdf` | `true` | One black-and-white PCB PDF: layers at 1:1, then framed drill maps, with continuous page numbering |
| `pcba_pdf` | `false` | Enable a separate two-page PCBA PDF; also requires nonblank `pcba_comment` |
| `pcba_comment` | `""` | Replace Comment 1 in the PCBA drawing sheet; blank disables PCBA export |
| `fab_pdf` | `true` | Both SMT inspection PDFs; applies when SMT export is enabled |
| `step_lite` | `false` | Board and populated components |
| `step_full` | `false` | Board, populated components, copper, via holes, silkscreen and solder mask |
| `alternative_edge` | `false` | Use `Fab.EdgeCuts` for PCB manufacturing outputs |
| `vcut` | `false` | Overlay `Fab.VCut` after choosing the manufacturing outline |
| `auto_translate` | `true` | Apply the component placement correction database |
| `all_active_layers` | `false` | Include all enabled layers in the Gerber export |
| `extra_layers` | `""` | Additional Gerber layer names, comma-separated |
| `strict` | `false` | Fail on missing MPN |
| `open_output` | `true` | Open the result folder in the system file manager after a successful GUI export |

Boolean CLI options use hyphens and support `--no-...`. For example:

```sh
# Quick export: skip both STEP conversions and the two Fab inspection PDFs.
python3 /path/to/com_github_DuoYuWang_Export-Toolkit/cli.py export \
  --project /path/to/Board/Board.kicad_pro \
  --no-step-lite --no-step-full --no-fab-pdf

# Full release suitable for a CI job. No display/session is required.
python3 /path/to/com_github_DuoYuWang_Export-Toolkit/cli.py export \
  --project /path/to/Board/Board.kicad_pro \
  --step-lite --step-full --strict \
  --release-notes-file /path/to/changes.md
```

The PCB, project and root schematic must have the same filename stem and live
in the same directory so native KiCad exporters load the selected project's
settings. Both `export` and `validate`, including explicit `--board` and
`--schematic` paths, enforce this binding before running native commands.
The root schematic supplies the shared schematic Revision. Child sheets may
have different names and reside in subdirectories; all pages are exported.
Save the project, schematic and PCB before exporting.
The toolbar checks the editor's loaded PCB (`pcbnew.GetBoard()`) against the
saved board and stops if they differ. CLI and native exports read the original
saved input paths. Source PCB, rule files and schematics are not copied for export.
Framed drill maps use generated drawing-only boards and minimal project-variable
files in the work directory; they do not contain or change source pads, tracks,
zones or schematics.
These temporary drawings use the file-format reader/writer directly, avoiding
the project-loading helper that resets the editor's global drawing-sheet state.

The **ERC / DRC + Save** button sits at the left of the bottom button row.
It runs native schematic ERC first, followed by one native PCB DRC run with
schematic parity, zone refill and PCB save. Only active errors fail this action;
warnings and findings explicitly excluded by KiCad are allowed. The project's
severity settings are respected, including `footprint_symbol_field_mismatch`
for custom fields such as `MPN`. Set that rule to Error in Board Setup if field
mismatches must fail checks. An unavailable parity check is reported as a failure.
Parity means checking consistency; the plugin does not update the PCB from the
schematic. Perform actual schematic-to-PCB updates in KiCad.

**Export** uses the saved design and existing copper fills directly. It does not
run ERC/DRC, refill zones, save the PCB, or block on missing/failed check history.
The former `refill_zones` export option has been removed; old JSON entries with
that name are ignored. Run the check action explicitly when required.

The check action uses `pcb drc --schematic-parity --refill-zones --save-board`
against the original PCB, with its original project and `.kicad_dru` rules.
KiCad saves the refilled PCB even when its DRC report contains errors. The
same dialog can then export that saved PCB while the editor remains unchanged.
Reload the PCB in the editor before further editing so its older in-memory
contents cannot overwrite the saved copper.

After checks, the log shows `git diff` filenames and added/deleted line counts
against HEAD, including staged and unstaged changes within the project directory.
Untracked files are ignored. This is read-only: nothing is committed, staged or
reverted. Git is optional. No repository, no initial commit or no Git executable
only makes the diff summary unavailable; checks and exports still work.

Only one timestamp is saved: `last_check_success_at` in the existing
`export-toolkit-options.json`. It is updated when the full ERC/DRC action succeeds
and preserved on failure. The GUI and generated release notes show this as
**Last successful ERC/DRC**. Checks performed manually in KiCad are not imported;
without a recorded success, the display reads **Not recorded**. The timestamp is
historical information and never gates export.

For a headless check/refill/save action, use the separate CLI command:

```sh
python3 /path/to/com_github_DuoYuWang_Export-Toolkit/cli.py validate \
  --project /path/to/Board/Board.kicad_pro \
  --report /path/to/check-result.json
```

For CI, run `validate` and continue to `export` only when it exits with status 0.
Both commands run without creating windows.

Manufacturing outline selection uses native plot layers without rewriting the
PCB. Independent Fab PDFs use KiCad's in-memory plot controller. Layer visibility
is temporarily changed on the loaded board and restored from a copied layer set;
the source `.kicad_prl` is never opened for writing or created by Fab export.
Output artifacts, check reports and private native settings are generated in
`Export/Export-Toolkit-<Project>-work/`, a visible directory reserved for Toolkit.
After acquiring the project lock, each action clears its own interrupted work
and starts with an empty directory. The work directory is removed on success or
failure. Generated drill-page boards/settings are removed too. Completed releases
stay in place until all new outputs are ready. Publication keeps the old directory
at `Export/.<Project>-<SCHRev>.previous` until the new directory is committed;
failed commits roll back. Interrupted commits are recovered under the project
lock on the next run. The reserved previous-release directory is outside the
work directory, so failure cleanup cannot delete the only surviving release.
Other versions and manually managed files outside these reserved directories
are preserved. The zero-byte `.export-toolkit.lock` file intentionally remains.

## Output

```text
Export/<Project>-<SCHRev>/
  <Project>-PCB-<PCBRev>.7z
  <Project>-SMT-<SCHRev>.7z
  <Project>-SCH-<SCHRev>.pdf
  <Project>-PCB-<PCBRev>.pdf
  <Project>-PCBA-<SCHRev>.pdf           # when checked and pcba_comment is nonblank
  <Project>-CAD-lite-<SCHRev>.step       # when enabled
  <Project>-CAD-full-<SCHRev>.step       # when enabled
  RELEASE_NOTES.md
```

The PCB package contains Gerbers, PTH/NPTH drill files, Gerber drill maps, and
`<Project>-NET-<PCBRev>.ipc`. The SMT package contains
`<Project>-BOM-<SCHRev>.csv`, `<Project>-POS-<SCHRev>.csv`, and, when enabled,
`<Project>-FFab-<SCHRev>.pdf` / `<Project>-BFab-<SCHRev>.pdf`.
No `designators.csv` is generated.

The multipage PCB PDF contains every enabled copper layer plus front/back silk,
paste, mask and Fab layers, with an outline on every page, drawing sheets,
black-and-white output, and actual-size drill marks. DNP crossout uses KiCad's native Fab option.
PTH and NPTH drill maps follow the layer pages, then any native blind/buried via
layer-pair maps. They use the same drawing sheet, paper size, title-block fields,
Revision and Git values as the PCB. All pages share the final sheet count; for
example, 16 PCB layers plus PTH/NPTH produce sheets 1/18 through 18/18. The
original drawing sheet is never edited. First-page-only sheet decorations are
omitted on the appended pages. If no custom sheet is selected, the installed
KiCad `pagelayout_default.kicad_wks` template is used.

KiCad generates the hole symbols and diameter/count legends as native DXF
vectors. Toolkit transfers those vectors to separate drawing-only boards, then
KiCad renders their PDF pages with the project drawing sheet. This avoids
ordinary PCB pad/via drill marks leaking into the wrong drill map. The drawings
always retain their original PCB coordinates at 1:1, including the native drill
table position. Export does not check for overlap or automatically scale, center,
move or rearrange any drawing content. Space for the drawing sheet and drill
table is managed in the design. PCB layers, drill maps and their drawing sheets
use KiCad's native black-and-white plot option. Schematic PDFs keep their theme's
foreground colors but omit the page background using `--no-background-color`;
editor theme settings are not changed. KiCad's empty NPTH map is retained when no NPTH
holes exist. The final PDF is assembled without rasterizing any page.

Drill maps are included even if the PCB fabrication package is disabled. Its
Excellon drill files and Gerber drill maps are unchanged.

The two inspection PDFs are black-and-white, have no title frame, use native
automatic scale, and share a single option. The back is mirrored. Additional
pad outlines and pad numbers are not enabled.

All completed PCB, PCBA, schematic and Fab PDFs undergo lossless embedded-font
deduplication before archiving and generating release checksums. Only identical
font programs with matching stream metadata share a single `FontFile` reference;
font descriptors, styles, character maps, text and graphics are not merged or
changed. This does not subset fonts or change the selected typeface. A large font
collection still occupies one full embedded copy after deduplication.

PDFs with no duplicate font data are left byte-for-byte unchanged. Rewritten
files are first saved to a sibling temporary file and checked for page count,
page geometry, drawing streams, bookmarks and metadata before atomic replacement;
failures leave the original staged PDF intact. Index tables reconstructed while
reading a Poppler-merged PDF must be valid after rewriting. The log shows the
number of duplicate font streams removed and the before/after size. For merged
documents this runs after the final merge, removing duplicates across pages too.

The **PCBA PDF** checkbox and **PCBA PDF Comment 1** text box are independent of
those inspection PDFs and the PCB PDF. Both values are cached in the project's
`export-toolkit-options.json` on export or dialog close and restored on next open.
Empty or whitespace-only input disables the checkbox and PCBA export. When
checked with nonblank text, it creates `<Project>-PCBA-<SCHRev>.pdf`, e.g.
`STAR-X3-PCBA-v1.0.0.pdf`, containing:

1. `F.Fab` + `F.SilkS` + `Edge.Cuts` + `Dwgs.User` (User.Drawings).
2. `B.Fab` + `B.SilkS` + `Edge.Cuts` + `Dwgs.User` (User.Drawings).

Fab is the first layer on each page, so the drawing-sheet layer identifier is
`F.Fab` / `B.Fab`, not the silkscreen layer. Silkscreen remains overlaid.

Both composite pages are black-and-white, unmirrored, at 1:1 in the original PCB
coordinates, with the PCB's original paper size and drawing sheet. Page numbers
are 1/2 and 2/2. Both the filename and drawing-sheet `${REVISION}` (legacy `%R`)
use the schematic Revision. The source PCB Revision and ordinary PCB PDF are
unchanged. The entered text replaces `${COMMENT1}` (legacy `%C0`) only in
the PCBA drawing sheet; other comments, PCB/SCH PDFs and source files are not
changed. A drawing sheet must contain that variable to display the override.
KiCad renders each composite page, and Poppler joins the two vector pages.
Use `--pcba-pdf --pcba-comment "Assembly instructions"` in the CLI. Either
`--no-pcba-pdf` or `--pcba-comment ""` disables the saved setting for one invocation.
PCBA PDF can be the only output;
as with other selections, publication replaces the same-version release with
the selected outputs rather than appending to an existing release.
For each inspection PDF, only its Fab layer and `Edge.Cuts` are made visible
in the original project's local settings. This keeps unrelated drawing layers
out of native automatic scaling and centering. Visibility is restored even if
export fails; the editor's layer state and source PCB are preserved.

Manufacturing outline selection first replaces `Edge.Cuts` with `Fab.EdgeCuts`
when selected, then overlays `Fab.VCut` when selected. Missing/empty selected
layers cause an error. This affects Gerbers, drill maps and the combined PCB PDF.
Both STEP files and the independent Fab PDFs always use the original `Edge.Cuts`.

The two STEP presets match these native export settings:

| Native STEP setting | Lite | Full |
| --- | --- | --- |
| Board body and all eligible components | On | On |
| Cut via holes in the board body | Off | On |
| Silkscreen and solder mask | Off | On |
| Tracks/vias, pads, filled zones and inner copper | Off | On |
| Fuse shapes / fill all vias | Off | Off |

Both use the default variant, drill/place origin, and a tight `0.001 mm` outline
tolerance. Both exclude DNP and unspecified footprint types, substitute matching
STEP/IGS models for VRML models, and allow overwriting the temporary output.
STEP optimization is enabled (P-curves are not written). Component and net
filters are empty. Model checks skip the excluded components too. Missing models
are reported as warnings and do not trigger strict MPN checks.

BOM, POS and both STEP exports exclude KiCad DNP components; BOM/POS also obey
their respective exclusion attributes. Fab PDFs retain DNP components with
crossout. The BOM CSV columns are `Index`, `Designator`, `Value`, `Description`,
`Footprint`, `Quantity`, `Manufacturer`, `Manufacturer Part Number`, `MPN replace`.
`Index` starts at 1 and numbers the final grouped rows, excluding the header.
The component's `MPN` property supplies `Manufacturer Part Number`; `MPN2`
supplies the optional `MPN replace` column. A missing `MPN2` leaves that cell
blank and does not replace the primary MPN or trigger a missing-MPN warning by
itself. Manufacturer information is taken only from PCB fields: update the PCB
from the schematic to transfer `MPN2` before exporting. BOM/POS generation does
not read a schematic BOM or use it as a fallback. An empty Manufacturer is valid.
The BOM groups matching components into one row with joined designators and a
total quantity. Footprint names omit the library prefix:
`Capacitor_SMD:C_1206_3216Metric` is written as `C_1206_3216Metric`.
The full library identity is retained internally for grouping, so identically
named footprints from different libraries are not inadvertently combined.
Different `MPN2` values also produce separate BOM groups, preserving replacement
part information for each set of designators.
The POS CSV columns are `Index`, `Designator`, `Mid X`, `Mid Y`, `Rotation`, and
`Layer`. `Index` starts at 1 and numbers the final exported component rows after
all exclusions, independently of BOM group indices.

POS coordinates use mm and the drill/place origin. Anchor/centroid selection,
bottom-side `180 - angle` transformation, optional database offsets and manual
`FT Rotation Offset`, `FT Position Offset`, `FT Origin`, `FT Layer Override`
fields follow the upstream plugin. Disabling automatic corrections still keeps
manual corrections and the component-side coordinate convention.

## Release notes and publication

The project-root `RELEASE_NOTES.md` contains only user-maintained change text.
The dialog loads and edits that source file. The CLI reads it by default;
`--release-notes-file` can supply another source for one invocation. The delivered
`RELEASE_NOTES.md` adds a `What's Changed` heading around this text. Its header and
checksum section are always regenerated and are not editable inputs. There are
no hidden markers or warning sections. Metadata and
SHA-256 checksums of the final selected outputs are generated automatically;
the notes file itself is excluded from the checksum list.

Everything is generated and archives are verified in the visible work directory
under `Export`. Once the new outputs are complete, the new directory replaces the
old one with the recoverable publication procedure above. Unselected outputs from
an older run therefore cannot remain in the release. One project export runs at
a time. Design inputs, hierarchical schematics (including external sheets), local
settings and external drawing sheets are fingerprinted before export and checked
again before publication. A change aborts publication and preserves the previous
release. KiCad `_autosave-*` recovery copies found during directory scanning are
ignored: creating, updating or removing them does not indicate a saved design
change. Explicitly selected files and referenced hierarchical sheets remain
guarded regardless of their names.
This does not snapshot or monitor external footprint/3D libraries; do not
edit those libraries while exporting.

The CLI does not create a missing project-root notes file. The GUI intentionally
saves its editable export options and change notes when Export is clicked.

If a separately generated artifact has been added to a release, refresh its
checksum table under the project lock without rerunning design exporters:

```sh
python3 cli.py refresh-manifest --project /path/to/MyBoard.kicad_pro
```

This preserves the existing header and user change text. It updates checksums of
files actually present; it does not certify that separately added artifacts came
from the same source revision.

CLI success returns `0`, export failures return `1`, invalid arguments return `2`,
and interruption returns `130`.
Diagnostics and warnings go to the terminal. Release notes contain no warnings.
Native stdout/stderr are drained and displayed during execution, with an elapsed
time/last-output message every 30 seconds. Some KiCad operations remain silent
while computing; silence alone never cancels a job. Each STEP export has a
30-minute default limit, adjustable in the CLI with `--step-timeout SECONDS`.
The GUI's Close button becomes Cancel during export. Cancellation/timeout stops
the active command and its descendants before workspace cleanup. In-process
KiCad plots can only observe cancellation between native calls. The separate
ERC/DRC-and-save action retains its non-cancellable UI behavior.
An optional `--report /path/to/export-result.json` provides a versioned JSON result
containing status, output filenames, SHA-256, tool versions, effective options,
warnings, the last successful check time, and any failure. The `validate` report
includes ERC/DRC/parity counts and issues plus the Git diff summary. This is the
integration boundary for future private
Forgejo runners and LLM review tools; the plugin makes no LLM or server API calls.
The report is optional and separate from the release notes. Each run replaces
the report at the supplied path using a completed temporary file. A read-only
previous report can be replaced when its parent directory permits replacement.
Expected validation/dependency/native export failures use concise error messages.
Unexpected Python/API errors include a full traceback in CLI standard error or
the GUI log, and in the optional JSON report's `traceback` field. Diagnostic
tracebacks are not included in release notes.
Only the separate check action requests a zone refill and PCB save.
Disabling both STEP exports skips model checks and conversions.

## KiCad compatibility

Target: KiCad 10.x. Native options are checked against the installed CLI's help
instead of assuming a particular patch version. An unavailable required option
produces a clear error. PDF naming variations across KiCad 10 are handled by
moving the native PDF without changing its contents.

See [LICENSE](LICENSE) for license information.
