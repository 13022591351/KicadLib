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
