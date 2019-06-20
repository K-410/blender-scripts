import bpy
import mathutils
import blf

bl_info = {
    "name": "Move Origin",
    "description": "",
    "author": "kaio",
    "version": (1, 0, 0),
    "blender": (2, 80, 0),
    "location": "3D View",
    "category": "Object"
}


def bound_box_center(obj):
    accum = mathutils.Vector()
    for co in obj.bound_box:
        accum += obj.matrix_world @ mathutils.Vector(co)
    return accum * .125


def weighted_center(obj):
    accum = mathutils.Vector()
    for v in obj.data.vertices:
        accum += obj.matrix_world @ v.co
    return accum / len(obj.data.vertices)


def draw_text(font_id, str_list, area, dim_y):
    line_spacing = [(dim_y * 2) * i for i in range(len(str_list))]
    scale = bpy.context.preferences.view.ui_scale
    font_size = round(11 * scale)
    x = (20 * scale) + area.regions[2].width
    y = area.height - (line_spacing[1] * 8 * scale)

    for ofs_y, string in zip(line_spacing, str_list):
        blf.shadow(font_id, 3, 0, 0, 0, 0.75)
        blf.enable(font_id, blf.SHADOW)
        blf.position(font_id, x, y - (ofs_y * scale), 0)
        blf.size(font_id, font_size, 72)
        blf.color(font_id, 1, 1, 1, 1)

        if isinstance(string, tuple):
            blf.color(font_id, 1, 1, 0, 1)
            ofs_x = 0

            for substring in string:
                blf.position(font_id, x + ofs_x, y - (ofs_y * scale), 0)
                ofs_x += (blf.dimensions(0, "M")[0] + 30) * scale
                blf.draw(font_id, substring)
                blf.color(font_id, 1, 1, 1, 1)
        else:
            blf.draw(font_id, string)


class OBJECT_OT_move_origin(bpy.types.Operator):
    bl_idname = "object.move_origin"
    bl_label = "Move Origin"

    _handler = _context = None

    @classmethod
    def poll(self, context):
        return (context.area.type == 'VIEW_3D' and
                context.mode == 'OBJECT' and
                len(context.selected_objects) == 1 and
                context.selected_objects.pop() is context.object and
                context.object.type == 'MESH')

    @classmethod
    def _add_handler(cls, context):
        font_id = 0
        str_list = [
            'Move Origin is active',
            '']
        prefs = context.preferences.addons[__name__].preferences
        if prefs.show_hints:
            str_list.extend([
                '',
                ('Space', ' Accept'),
                ('Enter', ' Accept'),
                "",
                ('Esc', ' Cancel'),
                "",
                ('Tab', ' Toggle Snap'),
                ('F', ' Show In Front'),
                ('Alt R', ' Reset Rotation'),
                '',
                ('B', ' Bounding Box Center'),
                ('M', ' Weighted Center'),
                ('C', ' Grid Center')])
        dim_y = blf.dimensions(font_id, "M")[1]
        draw_args = font_id, str_list, context.area, dim_y
        args = draw_text, draw_args, 'WINDOW', 'POST_PIXEL'
        cls._remove_handler(context)

        setattr(cls, '_handler', context.space_data.draw_handler_add(*args))

    @classmethod
    def _remove_handler(cls, context):
        handler = getattr(cls, '_handler', None)
        if handler is not None:
            try:
                context.space_data.draw_handler_remove(handler, 'WINDOW')
            except ValueError:
                pass
        setattr(cls, '_handler', None)

    def commit(self, context):
        origin_helper = self.origin_helper
        helper_mat = origin_helper.matrix_world
        obj = self.obj

        # in case the user gets smart and tries
        # to delete the object and commit changes.
        try:
            move = helper_mat.inverted() @ obj.matrix_world
            obj.matrix_world @= move.inverted()
            obj.data.transform(move)

        except ReferenceError:
            return self.cancel(context)

        obj.select_set(True)
        bpy.data.objects.remove(origin_helper)
        context.view_layer.objects.active = obj
        return {'FINISHED'}

    def cancel(self, context):
        try:
            context.scene.collection.objects.unlink(self.origin_helper)
            bpy.data.objects.remove(self.origin_helper)
            self.obj.select_set(True)
            context.view_layer.objects.active = self.obj

        except ReferenceError:
            helper = bpy.data.objects.get(self.helper_name)
            if helper is not None:
                bpy.data.objects.remove(helper)

        self.report({'INFO'}, "Move Origin: Cancelled")

        return {'CANCELLED'}

    def modal(self, context, event):
        etype, value = event.type, event.value
        origin_helper = self.origin_helper
        obj = self.obj

        if event.alt and etype == 'R' and value == 'PRESS':
            origin_helper.rotation_euler.zero()
            return {'RUNNING_MODAL'}

        if etype in ('F', 'B', 'M', 'C', 'TAB') and value == 'PRESS':
            if etype == 'F':
                origin_helper.show_in_front ^= True
            elif etype == 'B':
                origin_helper.matrix_world.translation = bound_box_center(obj)
            elif etype == 'M':
                origin_helper.matrix_world.translation = weighted_center(obj)
            elif etype == 'C':
                origin_helper.matrix_world.translation = 0, 0, 0
            elif etype == 'TAB':
                context.tool_settings.use_snap ^= True
            return {'RUNNING_MODAL'}

        if context.selected_objects != [origin_helper] or etype == 'ESC':
            return self.cancel(context)

        if etype in {'SPACE', 'RET'} and value == 'PRESS':
            return self.commit(context)
        return {'PASS_THROUGH'}

    def __del__(self):
        context = getattr(__class__, '_context', None)
        if context is not None:
            self._remove_handler(self._context)
            self._context.area.tag_redraw()

    def invoke(self, context, event):
        setattr(__class__, '_context', context)
        obj = context.object
        origin_helper = bpy.data.objects.new(f"{obj.name} Origin", None)
        origin_helper.matrix_world = obj.matrix_world
        origin_helper.empty_display_type = 'ARROWS'
        origin_helper.show_name = True
        helper_dim = (obj.dimensions / 3) / (sum(obj.scale) / 3)
        origin_helper.empty_display_size = sum(helper_dim) / 1.5
        context.scene.collection.objects.link(origin_helper)
        context.view_layer.objects.active = origin_helper
        obj.select_set(False)
        origin_helper.select_set(True)
        self.obj = obj
        self.origin_helper = origin_helper
        context.window_manager.modal_handler_add(self)
        self.helper_name = origin_helper.name
        self._add_handler(context)
        return {'RUNNING_MODAL'}


class OBJECT_MT_move_origin(bpy.types.Menu):
    bl_label = 'Move Origin'

    def draw(self, context):
        self.layout.operator("object.move_origin")


class MoveOrigin_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    ann = __annotations__ = dict()

    ann['show_hints'] = bpy.props.BoolProperty(
        name="Show Viewport Hints", default=True, description="Enable to show "
        "operator hints in the viewport")

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.alignment = 'CENTER'
        col = row.column()

        col.separator(factor=2)
        col.prop(self, "show_hints")
        col.separator(factor=2)
        col.label(text="Usage:")
        col.separator(factor=1.5)
        col.label(text="1. Object Menu > Move Origin")
        col.label(text="2. Transform the helper")
        col.label(text="3. Press spacebar or enter")
        col.separator(factor=2)


def _classes():
    import inspect
    import sys

    for _, item in inspect.getmembers(sys.modules[__name__]):
        if inspect.isclass(item) and item.__module__ == __name__:
            yield item


classes = tuple(_classes())


def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)
    bpy.types.VIEW3D_MT_object.prepend(OBJECT_MT_move_origin.draw)


def unregister():
    from bpy.utils import unregister_class
    bpy.types.VIEW3D_MT_object.remove(OBJECT_MT_move_origin.draw)
    for cls in reversed(classes):
        unregister_class(cls)
