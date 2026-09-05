"""Generate manufacturing tables from KiCad's PCB footprint data."""
import csv
from collections import Counter

from .placement import PlacementRules, footprint_get_field, footprint_has_field

BOM_FIELDS = ['Designator', 'Value', 'Footprint', 'Quantity', 'Manufacturer',
              'Manufacturer Part Number', 'Description']
POS_FIELDS = ['Designator', 'Mid X', 'Mid Y', 'Rotation', 'Layer']


def read_csv(path):
    with open(path, newline='', encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def write_csv(path, fields, rows):
    with open(path, 'w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def adapt_tables(board, native_pos, bom_path, pos_path, auto_translate=True, warn=print):
    import pcbnew
    fps = sorted(board.GetFootprints(), key=lambda fp: fp.GetReference().upper())
    metadata = {}
    for fp in fps:
        ref = fp.GetReference()
        if fp.IsDNP() or '**' in ref or fp.GetAttributes() & pcbnew.FP_EXCLUDE_FROM_BOM:
            continue
        def field(key):
            value = footprint_get_field(fp, key) if footprint_has_field(fp, key) else ''
            return value.strip()
        values = {'Manufacturer': field('Manufacturer'),
                  'Manufacturer Part Number': field('MPN'),
                  'Description': field('Description')}
        if not values['Manufacturer Part Number']:
            warn(f'{ref}: missing MPN.')
        metadata[id(fp)] = values
    counts = Counter(fp.GetReference().upper() for fp in fps)
    bom_counts, pos_counts = counts.copy(), counts.copy()
    def designator(fp, remaining):
        ref = fp.GetReference().upper()
        suffix = ''
        if remaining[ref] > 1:
            suffix = '_' + str(remaining[ref])
            remaining[ref] -= 1
        return ref + suffix
    grouped = {}
    for fp in fps:
        ref = fp.GetReference()
        if fp.IsDNP() or '**' in ref or fp.GetAttributes() & pcbnew.FP_EXCLUDE_FROM_BOM:
            continue
        values = metadata[id(fp)]
        library = str(fp.GetFPID().GetLibNickname())
        item = str(fp.GetFPID().GetLibItemName())
        footprint = f'{library}:{item}' if library else item
        key = (fp.GetValue(), footprint, *values.values())
        ref_out = designator(fp, bom_counts)
        if key in grouped:
            grouped[key]['Designator'] += ', ' + ref_out
            grouped[key]['Quantity'] += 1
        else:
            grouped[key] = dict(Designator=ref_out, Value=fp.GetValue(), Footprint=footprint,
                                Quantity=1, **values)
    write_csv(bom_path, BOM_FIELDS, grouped.values())
    # A native POS export determines eligible references (KiCad DNP/POS flags).
    native_refs = Counter(r.get('Ref', r.get('Reference', r.get('Designator', '')))
                          for r in read_csv(native_pos))
    rules, positions = PlacementRules(), []
    for fp in fps:
        ref = fp.GetReference()
        if not native_refs[ref] or fp.IsDNP() or fp.GetAttributes() & pcbnew.FP_EXCLUDE_FROM_POS_FILES or '**' in ref:
            continue
        native_refs[ref] -= 1
        placement = rules.calculate(fp, board.GetDesignSettings().GetAuxOrigin(), auto_translate)
        positions.append(dict(Designator=designator(fp, pos_counts), **placement))
    write_csv(pos_path, POS_FIELDS, positions)
