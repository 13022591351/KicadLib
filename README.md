# KicadLib

Shared libraries and resources for KiCad 10.

## Configure Paths

Download or clone this repository to a permanent location. Throughout this guide,
`/<YOUR_PATH>/KicadLib/` represents the **absolute path to this repository**.
Replace `<YOUR_PATH>`, including the angle brackets, with the path to the folder
containing your KicadLib checkout.

1. Open the KiCad Project Manager.
2. Select **Preferences > Configure Paths**.
3. Add or update the following variables:

| Environment variable | Absolute path | Purpose |
| --- | --- | --- |
| `KICAD_DYW_DIR` | `/<YOUR_PATH>/KicadLib/` | Repository root. |
| `KICAD10_3RD_PARTY` | `/<YOUR_PATH>/KicadLib/3rdparty/` | Third-party content directory. |
| `KICAD_USER_TEMPLATE_DIR` | `/<YOUR_PATH>/KicadLib/template/` | User project template directory. |

Enter all three values as independent, full absolute paths. The order in which
KiCad resolves these variables is not user-configurable, so do not reference
another variable inside a path value.

Click **OK** to save, then restart KiCad to load the updated paths.

## Add the Global Library Tables

Use KiCad 10's **Table** library type to add the repository's library tables as
nested entries in your global library tables. This makes the libraries listed
in each file available to all projects. See the
[KiCad library table documentation](https://docs.kicad.org/10.0/en/getting_started_in_kicad/getting_started_in_kicad.html#_library_and_library_table_basics).

### Footprint Libraries

1. Open **Preferences > Manage Footprint Libraries**.
2. Select the **Global Libraries** tab.
3. Click the arrow beside the folder button and select **Table**.
4. Browse to `/<YOUR_PATH>/KicadLib/fp-lib-table` and open it.
5. Give the entry a unique nickname, such as `KicadLib-Footprints`, and leave it enabled.
6. Confirm that its library path is `/<YOUR_PATH>/KicadLib/fp-lib-table`, then click **OK**.

The [fp-lib-table](fp-lib-table) file registers the repository's footprint libraries.
The folder-menu procedure is described in the
[KiCad footprint library documentation](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html#_adding_table_entries).

### Symbol Libraries

1. Open **Preferences > Manage Symbol Libraries**.
2. Select the **Global Libraries** tab.
3. Click the arrow beside the folder button and select **Table**.
4. Browse to `/<YOUR_PATH>/KicadLib/sym-lib-table` and open it.
5. Give the entry a unique nickname, such as `KicadLib-Symbols`, and leave it enabled.
6. Confirm that its library path is `/<YOUR_PATH>/KicadLib/sym-lib-table`, then click **OK**.

The [sym-lib-table](sym-lib-table) file registers the repository's symbol libraries.
The folder-menu procedure is described in the
[KiCad symbol library documentation](https://docs.kicad.org/10.0/en/eeschema/eeschema.html#_adding_table_entries).

Keep the existing global library entries when adding these two tables. The supplied
tables use `KICAD_DYW_DIR` to locate their libraries, so configure that variable
before loading them.

## Chinese Monospaced Font

[fonts/SarasaFixedSC](fonts/SarasaFixedSC/) contains **Sarasa Fixed SC 1.0.41**,
the Simplified Chinese monospaced family without programming ligatures. The four
included TTF files provide Regular, Bold, Italic, and Bold Italic styles.
The fonts are free to use, including commercially, under the bundled
[SIL Open Font License 1.1](fonts/SarasaFixedSC/LICENSE).
Source: [official release](https://github.com/be5invis/Sarasa-Gothic/releases/tag/v1.0.41),
**Single Family & Language TTF Package > SC > Fixed**.

### Install on Linux

Install the fonts for your current user; no administrator privileges are needed.
Replace the repository path below before running these commands:

```sh
mkdir -p "$HOME/.local/share/fonts/SarasaFixedSC"
cp "/<YOUR_PATH>/KicadLib/fonts/SarasaFixedSC/"*.ttf "$HOME/.local/share/fonts/SarasaFixedSC/"
cp "/<YOUR_PATH>/KicadLib/fonts/SarasaFixedSC/LICENSE" "$HOME/.local/share/fonts/SarasaFixedSC/"
fc-cache -f "$HOME/.local/share/fonts/SarasaFixedSC"
fc-list ':family=Sarasa Fixed SC' family style
```

The last command should list all four styles. Close and reopen KiCad after
installation so the font appears in its font selectors.

### Set the Schematic Default Font

1. Open the Schematic Editor.
2. Select **Preferences > Preferences > Schematic Editor > Display Options**.
3. Set **Default font** to **Sarasa Fixed SC**, then click **OK**.

This is a user preference. Text with an explicitly assigned font retains that
font. To update existing schematic text, use **Edit > Edit Text and Graphic
Properties**, select the desired scope, and set its font to **Sarasa Fixed SC**.
See the [KiCad schematic font documentation](https://docs.kicad.org/10.0/en/eeschema/eeschema.html#fonts).

### Use the Font in the PCB Editor

KiCad 10's PCB Editor does not provide the same global **Default font** selector.
Select **Sarasa Fixed SC** in the **Font** field when adding or editing text
(`E`). For existing board text, use **Edit > Edit Text and Graphic Properties**,
select the required object types and layers, and set the font there.

Select the family **Sarasa Fixed SC** and use the **Bold** and **Italic** controls
to choose emphasis; enabling both uses the Bold Italic style. Mirrored text and
**Knockout** (negative text in a solid rectangle) are controlled by KiCad.
Knockout is available for ordinary PCB text, not text boxes.
See the [KiCad PCB text documentation](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html#text).

### Share Designs and Export in CI

Assign the font explicitly to design text that must retain its appearance across
machines. In **Schematic Setup > Embedded Files** and **Board Setup > Embedded
Files**, enable **Embed fonts** and save the design. Alternatively, install the
same four TTF files on each workstation and CI runner used for export.
