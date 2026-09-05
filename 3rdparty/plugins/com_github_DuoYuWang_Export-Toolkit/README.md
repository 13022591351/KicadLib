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
| `schematic_pdf` | `true` | All schematic pages with drawing sheets |
| `pcb_pdf` | `true` | One color multipage PCB PDF, scale 1:1 |
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
saved input paths. No PCB, project, rule file or schematic is copied for export.

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
PCB. Independent Fab plots temporarily set the original `.kicad_prl` layer
visibility and restore its previous contents, including on export failure.
Output artifacts, check reports and private native settings are generated in
`Export/Export-Toolkit-<Project>-work/`, a visible directory reserved for Toolkit.
After acquiring the project lock, each action clears its own interrupted work
and starts with an empty directory. The work directory is removed on success or
failure. No project input files are copied. Completed releases stay in place
until all new outputs are ready; then the old same-version release is deleted
and the new release is moved into place. Other versions and manually managed
files outside the reserved work directory are preserved.

## Output

```text
Export/<Project>-<SCHRev>/
  <Project>-PCB-<PCBRev>.7z
  <Project>-SMT-<SCHRev>.7z
  <Project>-SCH-<SCHRev>.pdf
  <Project>-PCB-<PCBRev>.pdf
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
color, and actual-size drill marks. DNP crossout uses KiCad's native Fab option.
The two inspection PDFs are black-and-white, have no title frame, use native
automatic scale, and share a single option. The back is mirrored. Additional
pad outlines and pad numbers are not enabled.
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
crossout. The BOM CSV reads the component's `MPN` property and exports it under
the `Manufacturer Part Number` column, alongside `Manufacturer` and
the built-in component `Description`. An empty Manufacturer is valid. Only these
manufacturer fields are used. Manufacturer information is taken only from PCB
fields. BOM/POS generation does not read a schematic BOM or use it as a fallback.
The POS CSV contains only `Designator`, `Mid X`, `Mid Y`, `Rotation`, and `Layer`.

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
under `Export`. Once the new outputs are complete, the old same-version release
directory is deleted and the new directory is moved into place. Unselected
outputs from an older run therefore cannot remain in the release. Failures before
publication leave the previous version intact. One project export runs at a time.

CLI success returns `0`, export failures return `1`, invalid arguments return `2`,
and interruption returns `130`.
Diagnostics and warnings go to the terminal. Release notes contain no warnings.
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
