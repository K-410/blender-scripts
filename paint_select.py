import bpy
import bmesh
from bpy.props import BoolProperty
from math import isclose

bl_info = {
    "name": "Paint Select",
    "description": (""),
    "author": "kaio",
    "version": (1, 0, 0),
    "blender": (2, 80, 0),
    "location": "3D View",
    "category": "3D View"
}


class VIEW3D_OT_paint_select(bpy.types.Operator):
    bl_idname = "view3d.paint_select"
    bl_label = "Paint Select"
    bl_options = {'REGISTER', 'UNDO'}

    extend: BoolProperty(name="Extend", default=False)
    deselect: BoolProperty(name="Deselect", default=False)
    toggle: BoolProperty(name="Toggle", default=False)

    def modal(self, context, event):

        if event.type == 'MOUSEMOVE':
            event_xy = event.mouse_region_x, event.mouse_region_y
            threshold = self.drag_threshold
            init_xy = self.init_xy
            z = zip(init_xy, event_xy)

            if not all(isclose(x, y, abs_tol=threshold) for x, y in z):

                extend = True if not self.deselect else False

                bpy.ops.view3d.select(
                    'INVOKE_DEFAULT',
                    extend=extend,
                    toggle=self.toggle,
                    deselect=self.deselect)

        if event.type == 'LEFTMOUSE':
            if event.value == 'RELEASE':
                return {'FINISHED'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        bm = bmesh.from_edit_mesh(context.object.data)
        ts = context.tool_settings
        msm = ts.mesh_select_mode[:]

        self.drag_threshold = context.preferences.inputs.drag_threshold
        self.init_xy = event.mouse_region_x, event.mouse_region_y

        elem = None

        if msm == (False, False, True):
            elem = bm.faces
        elif msm == (True, False, False):
            elem = bm.verts
        elif msm == (False, True, False):
            elem = bm.edges

        if not elem:
            return {'CANCELLED'}

        presel = set(el for el in elem if not el.select)

        bpy.ops.view3d.select(
            'INVOKE_DEFAULT',
            extend=False,
            toggle=self.toggle,
            deselect=self.deselect)

        postsel = set(el for el in elem if not el.select)

        diff = postsel - presel
        if not diff:
            diff = presel - postsel

        elem.ensure_lookup_table()
        if self.toggle and diff:
            self.deselect = not elem[tuple(diff)[0].index].select

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}


keymaps = []


def register():
    bpy.utils.register_class(VIEW3D_OT_paint_select)

    wm = bpy.context.window_manager
    km = wm.keyconfigs.addon.keymaps.new(name='Mesh')

    kmi = km.keymap_items.new(
        VIEW3D_OT_paint_select.bl_idname, 'LEFTMOUSE', 'PRESS')
    kmi.properties['extend'] = 0
    kmi.properties['toggle'] = 0
    kmi.properties['deselect'] = 0
    keymaps.append((km, kmi))

    kmi = km.keymap_items.new(
        VIEW3D_OT_paint_select.bl_idname, 'LEFTMOUSE', 'PRESS', shift=True)
    kmi.properties['extend'] = 1
    kmi.properties['toggle'] = 1
    kmi.properties['deselect'] = 0
    keymaps.append((km, kmi))


def unregister():
    bpy.utils.unregister_class(VIEW3D_OT_paint_select)
    for km, kmi in keymaps:
        km.keymap_items.remove(kmi)
    keymaps.clear()
