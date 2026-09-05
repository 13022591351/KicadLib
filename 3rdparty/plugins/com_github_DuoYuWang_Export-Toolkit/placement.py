"""Component placement rules adapted from Benny Megidish's Fabrication Toolkit.

Apache-2.0; see LICENSE. The placement rules and transformation data originate
from https://github.com/bennymeg/Fabrication-Toolkit. The data was converted from
CSV to JSON. KiCad supplies the native position export; this adapter preserves
the reference plugin's centroids, angles and offsets.
"""
import json
import math
import re
from pathlib import Path
from typing import Tuple
import pcbnew
from .errors import ExportError


def footprint_has_field(fp, name):
    return fp.HasField(name) if hasattr(fp, 'HasField') else fp.HasFieldByName(name)


def footprint_get_field(fp, name):
    field = fp.GetField(name) if hasattr(fp, 'GetField') else fp.GetFieldByName(name)
    return field.GetText() if field else ''


def duplicate_footprint(fp):
    try:
        duplicate = fp.Duplicate(False)
    except TypeError:
        duplicate = fp.Duplicate()
    return pcbnew.Cast_to_FOOTPRINT(duplicate) if hasattr(pcbnew, 'Cast_to_FOOTPRINT') else duplicate


def footprint_to_degrees(fp):
    fp.SetOrientationDegrees(0)


class PlacementRules:
    def __init__(self):
        self._rules = json.loads(Path(__file__).with_name('transformations.json').read_text())

    def _get_footprint_rotation(self, footprint):
        return footprint.GetOrientation().AsDegrees() if hasattr(footprint.GetOrientation(), 'AsDegrees') else footprint.GetOrientation() / 10.0

    def _get_footprint_position(self, footprint):
        """Calculate position based on center of pads / bounding box."""
        origin_type = self._get_origin_from_footprint(footprint)

        footprint_rotation = self._get_footprint_rotation(footprint)
        footprint_rotated = footprint_rotation % 90 != 0

        # if the footprint is not rotated by a multiple of 90 degrees, 
        # the bounding boxes will be off, so we create a temporary copy that is rotated to 0
        if footprint_rotated:
            footprint = duplicate_footprint(footprint)
            footprint_to_degrees(footprint)

        if origin_type == 'Anchor':
            position = footprint.GetPosition()
        else: # if type_origin == 'Center' or anything else
            pads = footprint.Pads()
            if len(pads) > 0:
                # get bounding box based on pads only to ignore non-copper layers, e.g. silkscreen
                bbox = pads[0].GetBoundingBox()         # start with small bounding box
                for pad in pads:
                    bbox.Merge(pad.GetBoundingBox())    # expand bounding box
                position = bbox.GetCenter()
            else:
                position = footprint.GetPosition()      # if we have no pads we fallback to anchor

        if footprint_rotated:
            # now we determine the offset of the "true" position relative to the "KiCAD" position & apply the footprints rotation

            raw_pos = footprint.GetPosition()
            relative_position = (position[0] - raw_pos[0], position[1] - raw_pos[1])

            rsin = math.sin(footprint_rotation / 180 * math.pi)
            rcos = math.cos(footprint_rotation / 180 * math.pi)

            relative_position = ( relative_position[0] * rcos + relative_position[1] * rsin, -relative_position[0] * rsin + relative_position[1] * rcos )

            position = (raw_pos[0] + relative_position[0], raw_pos[1] + relative_position[1])

        return position

    def _find_rule(self, footprint, library=None):
        """Preserve the reference rule order: footprint match, then library match."""
        for rule in self._rules:
            pattern = rule['name']
            segments = footprint.split(':')
            target = footprint if ':' in pattern else segments[1] if len(segments) > 1 else segments[0]
            if re.search(pattern, target):
                return rule
        if library:
            for rule in self._rules:
                if re.search(rule['name'], library):
                    return rule
        return None

    def calculate(self, footprint, origin, auto_translate=True):
        """Return POS coordinates/rotation/side, applying one matched correction rule."""
        layer = self._get_layer_override_from_footprint(footprint)
        position = self._get_footprint_position(footprint)
        x, y = (position[0] - origin[0]) / 1e6, -(position[1] - origin[1]) / 1e6
        rotation = self._get_footprint_rotation(footprint)
        offset = self._get_position_offset_from_footprint(footprint)
        rule = None
        if auto_translate:
            rule = self._find_rule(str(footprint.GetFPID().GetLibItemName()),
                                   str(footprint.GetFPID().GetLibNickname()))
            if rule:
                offset = offset[0] + float(rule['x']), offset[1] + float(rule['y'])
        sine, cosine = math.sin(math.radians(rotation)), math.cos(math.radians(rotation))
        if layer == 'bottom':
            dx, dy = offset[0] * cosine + offset[1] * sine, offset[0] * sine - offset[1] * cosine
            output_rotation = 180.0 - rotation
        else:
            dx, dy = offset[0] * cosine - offset[1] * sine, offset[0] * sine + offset[1] * cosine
            output_rotation = rotation
        if rule:
            output_rotation += float(rule['rotation'])
        output_rotation = (output_rotation + self._get_rotation_offset_from_footprint(footprint)) % 360.0
        return {'Mid X': x + dx, 'Mid Y': y + dy, 'Rotation': output_rotation, 'Layer': layer}

    def _get_layer_override_from_footprint(self, footprint) -> str:
        '''Get the layer override from standard symbol fields.'''
        keys = ['FT Layer Override']
        fallback_keys = ['Layer Override', 'LayerOverride']

        layer = {
            pcbnew.F_Cu: 'top',
            pcbnew.B_Cu: 'bottom',
        }.get(footprint.GetLayer())

        for key in keys + fallback_keys:
            if footprint_has_field(footprint, key):
                temp_layer = footprint_get_field(footprint, key)
                if len(temp_layer) > 0:
                    if (temp_layer[0] == 'b' or temp_layer[0] == 'B'):
                        layer = "bottom"
                        break
                    elif (temp_layer[0] == 't' or temp_layer[0] == 'T'):
                        layer = "top"
                        break

        return layer

    def _get_rotation_offset_from_footprint(self, footprint) -> float:
        '''Get the rotation offset from standard symbol fields.'''
        keys = ['FT Rotation Offset']
        fallback_keys = ['Rotation Offset', 'RotOffset']

        offset = ""

        for key in keys + fallback_keys:
            if footprint_has_field(footprint, key):
                offset = footprint_get_field(footprint, key)
                break

        if offset is None or offset == "":
            return 0.0
        else:
            try:
                return float(offset)
            except ValueError:
                raise ExportError("Rotation offset of {} is not a valid number".format(footprint.GetReference()))

    def _get_position_offset_from_footprint(self, footprint) -> Tuple[float, float]:
        '''Get the position offset from standard symbol fields.'''
        keys = ['FT Position Offset']
        fallback_keys = ['Position Offset', 'PosOffset']

        offset = ""

        for key in keys + fallback_keys:
            if footprint_has_field(footprint, key):
                offset = footprint_get_field(footprint, key)
                break

        if offset == "":
            return (0.0, 0.0)
        else:
            try:
                offset = offset.split(",")
                return (float(offset[0]), float(offset[1]))
            except (ValueError, IndexError):
                raise ExportError("Position offset of {} is not a valid pair of numbers".format(footprint.GetReference()))

    def _get_origin_from_footprint(self, footprint) -> str:
        '''Get the origin from standard symbol fields.'''
        keys = ['FT Origin']
        fallback_keys = ['Origin']

        attributes = footprint.GetAttributes()

        # determine origin type by package type
        if attributes & pcbnew.FP_SMD:
            origin_type = 'Anchor'
        else:
            origin_type = 'Center'

        for key in keys + fallback_keys:
            if footprint_has_field(footprint, key):
                origin_type_override = str(footprint_get_field(footprint, key)).strip().capitalize()

                if origin_type_override in ['Anchor', 'Center']:
                    origin_type = origin_type_override
                break

        return origin_type
