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
| `refill_zones` | `false` | Refill and save the original PCB during native DRC |
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
in the same directory, as required by native DRC schematic parity. Explicit
`--board` and `--schematic` paths are validated against this requirement. The
root/first schematic supplies the shared schematic Revision; all its pages and
child sheets are exported. Save the project, schematic and PCB before exporting.
The toolbar checks the editor's loaded PCB (`pcbnew.GetBoard()`) against the
saved board and stops if they differ. CLI and native exports read the original
saved input paths. No PCB, project, rule file or schematic is copied for export.

Every export runs native **schematic ERC**, followed by native **PCB DRC with
schematic parity**. Only active errors stop publication; warnings are allowed.
The project's severity settings are respected, including
`footprint_symbol_field_mismatch` for custom fields such as `MPN`. Set that rule
to Error in Board Setup if mismatched fields must block a release. The plugin
does not update the PCB from the schematic automatically; do that in KiCad first.
Findings explicitly excluded by KiCad do not block export. An unavailable parity
check is an error, rather than a successful check with zero findings.

When `refill_zones` is enabled, DRC runs with `--refill-zones --save-board` against
the original PCB, using its project settings and custom `.kicad_dru` rules.
KiCad saves the refilled PCB even if the subsequent DRC result blocks export.
All later exporters use those saved fills and never request another refill.
After a GUI export with refilling, reload the PCB in the editor before further
editing, so an older in-memory board cannot overwrite the newly saved copper.
Without this option, the PCB file is not written.

Manufacturing outline selection uses native plot layers without rewriting the
PCB. Independent Fab plots temporarily set the original `.kicad_prl` layer
visibility and restore its previous contents, including on export failure.
Output artifacts and check reports are staged in a temporary directory. If that
directory is on a different filesystem, only completed output files are copied
and verified next to the release before the old release is deleted and replaced.
Temporary output directories are scoped to the current user and project. After
acquiring the project export lock, each run removes that project's temporary
output directories left by an interrupted run and starts with an empty directory.
Current temporary files are removed on success or failure. Completed releases
remain in place until the new release is ready; other revisions are retained.

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

Everything is generated and archives are tested in a temporary output directory.
Completed outputs are verified on the target filesystem before the old target
version directory deleted and the new directory moved into place. Unselected
outputs from an older run therefore cannot remain in the release. Failures before
publication leave the previous version intact. One project export runs at a time.

CLI success returns `0`, export failures return `1`, invalid arguments return `2`,
and interruption returns `130`.
Diagnostics and warnings go to the terminal. Release notes contain no warnings.
An optional `--report /path/to/export-result.json` provides a versioned JSON result
containing status, output filenames, SHA-256, tool versions, effective options,
warnings, ERC/DRC counts and issues, and any failure. This is the integration boundary for future private
Forgejo runners and LLM review tools; the plugin makes no LLM or server API calls.
The report is optional and separate from the release notes. Each run replaces
the report at the supplied path using a completed temporary file. A read-only
previous report can be replaced when its parent directory permits replacement.
Expected validation/dependency/native export failures use concise error messages.
Unexpected Python/API errors include a full traceback in CLI standard error or
the GUI log, and in the optional JSON report's `traceback` field. Diagnostic
tracebacks are not included in release notes.
No exporter requests a zone refill unless `refill_zones` was explicitly enabled.
Disabling both STEP exports skips model checks and conversions.

## Compatibility and development

`core.py` controls checks, execution order and publication. `exports.py` contains
the individual export jobs, shared filenames and STEP presets. `native.py` and
`boards.py` call the KiCad exporters. POS generation uses the public
`PlacementRules.calculate()` interface; the original rule order and correction
data are preserved. `errors.py` supplies `ExportError` and shared diagnostics.

Workflow tests execute the real orchestrator with substituted CLI export calls,
alongside native plotting tests. GUI state/diagnostic tests use control doubles
and create no windows; subprocess tests exercise event callbacks and child cleanup.

Target: KiCad 10.x. Native options are checked against the installed CLI's help
instead of assuming a particular patch version. PDF naming variations across
KiCad 10 are handled by moving the native PDF without changing its contents.
Runtime and visual validation currently use KiCad 10.0.6; required PDF/BOM
interfaces were also checked against the KiCad 10.0.0 source. This does not claim
that every patch release has been tested.

```sh
python3 -m pytest /path/to/com_github_DuoYuWang_Export-Toolkit/tests
```

See [LICENSE](LICENSE) for license information.
