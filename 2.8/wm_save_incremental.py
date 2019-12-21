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
    "blender": (2, 81, 0),
    "location": "Anywhere",
    "category": "File Browser"
}


class WM_OT_save_incremental(bpy.types.Operator):
    """Save as new main file by increments of one"""
    bl_idname = "wm.save_incremental"
    bl_label = "Save Incremental"

    props = bpy.ops.wm.save_as_mainfile.get_rna_type().properties
    ann = __annotations__ = {}

    for p in "copy", "relative_remap":
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

        prefs = context.preferences.addons[__name__].preferences
        show_notification = prefs.show_notification

        bpy.ops.wm.save_as_mainfile('EXEC_DEFAULT', filepath=fp, **kwargs)

        if show_notification:
            self.report({'INFO'}, f"Saved \"{_path.basename(fp)}\"")
        return {'FINISHED'}


def _update(self, context):
    from bpy.types import TOPBAR_MT_file as cls
    if self.show_in_file_menu:
        elems = ["layout.operator(\"wm.save_incremental\")"]
        find_string = "\"wm.save_as_mainfile\", text=\"Save Copy...\""
        return inject(cls, find_string, elems)
    _remove(cls)


def _remove(cls):
    draw = inject.namespace.get("draw")
    if draw:
        draw_funcs = cls.draw._draw_funcs
        idx = draw_funcs.index(draw)
        draw_funcs[idx] = cls._backup
        del cls._backup


class SaveIncrementalPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    show_in_file_menu: bpy.props.BoolProperty(
        name="Show in File Menu", default=True, update=_update)

    show_notification: bpy.props.BoolProperty(
        name="Show Notification", default=True)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.scale_y = 1.25
        split = layout.split(factor=0.6)
        col = split.column()
        # print()
        col.prop(self, "show_notification")
        col.prop(self, "show_in_file_menu")
        col = split.column()


def inject(cls, find_string, elems):
    import inspect

    src = inject.src = getattr(inject, "src", None)
    # print(repr(src))
    if src is None:
        try:
            _src = inspect.getsource(cls.draw)
            src = inject.src = _src.splitlines()
        except (TypeError, OSError):
            print("%s: Invalid draw function in %s" % (__name__, cls))
            return

        def indent_get(body):
            for idx, char in enumerate(body):
                if char != " ":
                    return idx
            return 0

        def find(contents, string):
            for idx, line in enumerate(contents):
                if string in line:
                    return idx
            raise ValueError

        for idx, line in enumerate(src):
            if line.find("def draw(self, context):") != -1:
                start = next(idx for (idx, c) in enumerate(line) if c != " ")
            if line.find(find_string) != -1:
                indent2 = " " * indent_get(line)
                for elem in reversed(elems):
                    src.insert(idx + 1, indent2 + elem)
                break
        else:
            print("%s: Couldn't inject, string not found" % __name__)
            return

        inject.namespace = {}
        inject.start = start

    start = inject.start
    namespace = inject.namespace
    namespace.update(vars(inspect.getmodule(cls)))
    new_src = "\n".join(line[start:] for line in src)
    exec(new_src, namespace)

    draw_funcs = getattr(cls.draw, "_draw_funcs", None)
    if draw_funcs is None:
        def _draw(self, context):
            pass
        cls.append(_draw)
        cls.draw._draw_funcs.remove(_draw)
        draw_funcs = cls.draw._draw_funcs

    for idx, func in enumerate(draw_funcs):

        if func.__module__ == cls.__module__ and \
           func not in func.__globals__.values():

            cls._backup = func
            draw_funcs[idx] = namespace['draw']
            break
    else:
        raise


def register():
    bpy.utils.register_class(WM_OT_save_incremental)
    bpy.utils.register_class(SaveIncrementalPreferences)

    context = bpy.context
    prefs = context.preferences.addons[__name__].preferences

    _update(prefs, context)


def unregister():
    cls = bpy.types.TOPBAR_MT_file
    _remove(cls)
    bpy.utils.unregister_class(SaveIncrementalPreferences)
    bpy.utils.unregister_class(WM_OT_save_incremental)
