# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


import bpy


bl_info = {
    "name": "Save Incremental",
    "description": "Unobtrusive incremental save",
    "author": "kaio",
    "version": (1, 0, 0),
    "blender": (2, 82, 0),
    "location": "Anywhere",
    "category": "File Browser"
}


class WM_OT_save_incremental(bpy.types.Operator):
    """Save as new main file by increments of one"""
    bl_idname = "wm.save_incremental"
    bl_label = "Save Incremental"

    props = bpy.ops.wm.save_as_mainfile.get_rna_type().properties
    ann = __annotations__ = {}

    for p in "copy", "relative_remap", "compress":
        kwargs = {"name": props[p].name,
                  "default": props[p].default,
                  "description": props[p].description}
        ann[p] = getattr(bpy.props, props[p].rna_type.identifier)(**kwargs)

    del kwargs, props, ann

    def execute(self, context):
        curr_fp = context.blend_data.filepath

        kwargs = {"copy": self.copy, "relative_remap": self.relative_remap}
        kwargs["compress"] = context.preferences.filepaths.use_file_compression

        # Main file has not been saved yet, invoke file browser
        if not curr_fp:
            return bpy.ops.wm.save_as_mainfile('INVOKE_DEFAULT', **kwargs)

        from itertools import takewhile

        # Extract current file number (looks at the end of file name)
        _path = bpy.utils._os.path
        fp, ext = _path.splitext(curr_fp)
        num = "1"
        num_idx = len(list(takewhile(lambda c: c.isnumeric(), fp[::-1])))

        if num_idx:
            num = fp[-num_idx:]
            fp = fp[:-num_idx]

        increment = int(num)

        # Find first available increment
        while _path.exists(fp + str(increment) + ext):
            increment += 1

        fp += str(increment) + ext
        bpy.ops.wm.save_as_mainfile('EXEC_DEFAULT', filepath=fp, **kwargs)
        self.report({'INFO'}, f"Saved \"{_path.basename(fp)}\"")
        return {'FINISHED'}


def register():
    bpy.utils.register_class(WM_OT_save_incremental)


def unregister():
    bpy.utils.unregister_class(WM_OT_save_incremental)
