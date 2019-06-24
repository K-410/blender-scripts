# Local Scene is a (simple) substitute for missing Local View in Blender 2.80
# Since Local View now is fully supported, this no longer has any purpose.
#
# Limitations:
# -   Can't have multiple Local Scenes. Local Scene is applied in all viewports
# -   Restore View setting doesn't use smooth view
# -   Deleting an object moved to Local Scene does not remove it from the
#     original scene

import blf
import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty,
                       FloatVectorProperty, IntProperty, StringProperty)
from mathutils import Matrix

bl_info = {
    "name":         "Local Scene",
    "description":  "Add a Local Scene mode that isolates selection to a new "
                    "scene called 'Local Scene'. A substitute for missing "
                    "Local Mode",
    "author":       "iceythe",
    "version":      (1, 0, 0),
    "blender":      (2, 80, 0),
    "location":     "In 3D View, Alt-Q hotkey",
    "category":     "3D View",
}

dns = bpy.app.driver_namespace


def addon_prefs():
    user_prefs = bpy.context.preferences
    addon = user_prefs.addons[__name__]
    return addon.preferences


def get_non_local_scenes():
    local = bpy.data.scenes.get(addon_prefs().local_scene_name)
    return set(s for s in bpy.data.scenes if s != local)


def get_objects(scene):
    a, b = scene.collection.objects, scene.objects
    return set((x for y in (a, b) for x in y))


def store_scene(scene):
    addon_prefs().original_scene = scene.name


def restore_scene(context):
    bpy.ops.view3d.local_scene_text(state=False)
    if retrieve_scene() is not None:
        context.window.scene = retrieve_scene()
    else:
        Scenes = get_non_local_scenes()
        context.window.scene = Scenes[0]
    # bpy.ops.view3d.local_scene_text(state=False)


def retrieve_scene():
    scene = bpy.data.scenes.get(addon_prefs().original_scene)
    return scene


def view_selected(context):
    if context.mode == 'OBJECT':
        bpy.ops.view3d.view_selected('INVOKE_DEFAULT', False)
    else:
        bpy.ops.object.editmode_toggle(False)
        bpy.ops.view3d.view_selected('INVOKE_DEFAULT', False)
        bpy.ops.object.editmode_toggle(False)


def store_view(context):
    prefs = addon_prefs()
    r3d = context.region_data
    context.scene['view_matrix'] = r3d.view_matrix
    prefs.view_distance = r3d.view_distance
    prefs.view_location = r3d.view_location


def restore_view(context):
    prefs = addon_prefs()
    r3d = context.region_data
    v_mat = 'view_matrix'
    try:
        r3d.view_matrix = Matrix(context.scene[v_mat])
    except KeyError:
        print("Local Scene Addon: Addon was reloaded while "
              "Local Scene was in effect. Reverting to defaults.")
    r3d.view_distance = prefs.view_distance
    r3d.view_location = prefs.view_location


@bpy.app.handlers.persistent
def local_scene_handler(dummy):
    dns['vpt_size'] = 16
    if 'Local Scene' in bpy.context.scene.name:
        bpy.ops.view3d.local_scene_text(state=True)


def get_handler(arg):
    handler_list = []

    if arg == 'POST':
        for h in bpy.app.handlers.load_post:
            if h.__name__ == 'local_scene_handler':
                handler_list.append(h)
        return handler_list

    elif arg == 'PRE':
        for h in bpy.app.handlers.load_pre:
            if h.__name__ == 'local_scene_load_pre':
                handler_list.append(h)

        return handler_list
    return []


@bpy.app.handlers.persistent
def local_scene_load_pre(scene):
    bpy.ops.view3d.local_scene_text(state=False)


def add_handlers():
    if not get_handler('POST'):
        bpy.app.handlers.load_post.append(local_scene_handler)
    if not get_handler('PRE'):
        bpy.app.handlers.load_pre.append(local_scene_load_pre)


def local_scene_remove_handlers():
    if get_handler('POST'):
        for h in get_handler('POST'):
            bpy.app.handlers.load_post.remove(h)
    if get_handler('PRE'):
        for h in get_handler('PRE'):
            bpy.app.handlers.load_pre.remove(h)


def draw_handler_remove(context):
    vpt = addon_prefs().vpt
    if vpt in dns:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(dns[vpt], 'WINDOW')
        except ValueError:
            print("Local Scene Addon: No handler found")
        del dns[vpt]
    refresh_viewport(context)


def refresh_viewport(context):
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()
    context.view_layer.update()


class LocalScene(bpy.types.Operator):
    """Isolates selection to a new scene"""
    bl_idname = "view3d.local_scene_mode"
    bl_label = "Local Scene"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return (context.selected_objects or
                bpy.data.scenes.get(addon_prefs().local_scene_name))

    def execute(self, context):

        D = bpy.data
        Colls = D.collections
        Scenes = D.scenes

        user_prefs = context.preferences
        prefs = user_prefs.addons[__name__].preferences
        zoom_selected = prefs.zoom_selected
        local_coll_name = prefs.local_coll_name

        local_scene = bpy.data.scenes.get(addon_prefs().local_scene_name)
        if context.scene is local_scene:
            if len(bpy.data.scenes) == 1:
                scene = D.scenes.new('Scene')
                store_scene(scene)

            scene = retrieve_scene()
            for obj in (get_objects(local_scene) - get_objects(scene)):
                scene.collection.objects.link(obj)
            Scenes.remove(local_scene)

            local_coll = Colls.get(local_coll_name)
            if local_coll:
                if local_coll is not None:
                    Colls.remove(local_coll)
            restore_scene(context)
            if prefs.restore_view:
                restore_view(context)

        else:
            store_scene(context.scene)
            bpy.ops.view3d.local_scene_text(state=True)
            sel = context.selected_objects

            if any(sel):
                if prefs.restore_view:
                    store_view(context)

                objs_to_link = set()
                for obj in context.selected_objects:
                    objs_to_link.add(obj)
                ao = context.active_object
                objs_to_link.add(ao) if ao else None

                if zoom_selected:
                    if not context.selected_objects and context.object:
                        context.object.select_set(True)
                        view_selected(context)
                        context.object.select_set(False)
                    else:
                        view_selected(context)

                if prefs.copy_scene:
                    bpy.ops.scene.new(type='EMPTY')
                    local_scene = context.scene
                    local_scene.name = 'Local Scene'
                else:
                    local_scene = bpy.data.scenes.new('Local Scene')
                    context.window.scene = local_scene

                if local_coll_name not in Colls:
                    local_coll = Colls.new(local_coll_name)
                else:
                    local_coll = Colls.get(local_coll_name)

                local_scene.collection.children.link(local_coll)
                [local_coll.objects.link(o) for o in objs_to_link]

                for obj in context.view_layer.objects:
                    obj.select_set(True)
                context.view_layer.objects.active = ao
        return {'FINISHED'}


class LocalSceneViewportText(bpy.types.Operator):
    """Viewport Text Draw"""
    bl_idname = "view3d.local_scene_text"
    bl_label = "Local Scene Viewport Text"
    bl_options = {'REGISTER'}

    state: bpy.props.BoolProperty(
        description="Used to determine whether the text should show by passing"
        "the 'state' kwarg to the operator", name='State', default=False)

    handle = None

    def execute(self, context):
        user_prefs = context.preferences
        prefs = user_prefs.addons[__name__].preferences
        font_size = prefs.vpt_size
        sv3d = bpy.types.SpaceView3D
        state = self.state
        vpt = prefs.vpt

        if state:
            draw_handler_remove(context)
            dns['vpt_size'] = font_size
            self.handle = sv3d.draw_handler_add(
                self.draw_callback, (None, None),
                'WINDOW', 'POST_PIXEL')

            dns[vpt] = self.handle
            refresh_viewport(context)
        else:
            draw_handler_remove(context)
        return {'FINISHED'}

    @staticmethod
    def draw_callback(self, context):
        user_prefs = bpy.context.preferences
        prefs = user_prefs.addons[__name__].preferences
        use_vpt = prefs.use_vpt

        if use_vpt:
            area = bpy.context.area
            regions = area.regions
            font_size = prefs.vpt_size
            header_h = regions[1].height
            h_enabled = header_h > 5
            h_at_top = regions[1].y != regions[4].y

            vpt_text = prefs.vpt_text
            align_v = prefs.vpt_align_v
            font_id = 0
            v_minus = font_size * 0.65
            h_minus = (len(vpt_text) / 2) * (font_size / 2)

            pos_y = 0
            if h_enabled:
                if h_at_top:
                    if align_v == 'TOP':
                        pos_y = area.height - (35 + v_minus)
                else:
                    if align_v == 'TOP':
                        pos_y = area.height - (header_h - 10 + v_minus)
                    else:
                        pos_y = 40
            else:
                if align_v == 'TOP':
                    pos_y = area.height - (header_h + 15 + v_minus)
            center = True
            if center:
                c = area.width / 2

                pos_x = int(c - h_minus)

            blf.position(font_id, pos_x, pos_y, 0)
            blf.size(font_id, font_size, 72)
            blf.draw(font_id, vpt_text)
            blf.disable(font_id, 2)


class LocalScenePreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    vpt = "local_scene_handler"
    local_scene_name = 'Local Scene'
    local_coll_name = 'Local Scene Collection'
    view_distance: FloatProperty()
    view_location: FloatVectorProperty()

    vpt_align_h_items = [("CENTER",  "Center",   "", 1),
                         ("LEFT",    "Left",     "", 2),
                         ("RIGHT",   "Right",    "", 3)]

    vpt_align_v_items = [
        ("TOP",     "Top",      "", 1), ("BOTTOM",  "Bottom",   "", 2)]

    state: bpy.props.BoolProperty(
        description="Used to determine whether the text should show by passing"
        " the 'state' kwarg to the operator", name='State', default=False)

    restore_view: BoolProperty(
        name='Restore Views', default=True, description="When enabled, exiting"
        " Local Scene will restore viewport")

    zoom_selected: BoolProperty(
        name='Frame Selected', default=True, description="Frame selected "
        "objects when entering Local Scene")

    copy_scene: BoolProperty(
        name='Copy Scene Settings', default=True, description="Copy settings "
        "from original scene to Local Scene. If unchecked, Local Scene is "
        "created using default settings")

    use_vpt: BoolProperty(
        name='Enable Viewport Text', default=True, description="Enables "
        "viewport text to indicate when Local Scene is active")

    vpt_size: IntProperty(
        name='Font Size', default=11, soft_max=30, soft_min=8, description=""
        "Font size for Local Scene viewport text")

    vpt_text: StringProperty(
        name='Text', default='Local Scene', description="Viewport text to show"
        "when Local Scene is active")

    vpt_align_h: EnumProperty(
        name='Horizontal Alignment', default='CENTER', description="Horizontal"
        "alignment of viewport text", items=vpt_align_h_items)

    vpt_align_v: EnumProperty(
        name='Vertical Alignment', default='TOP', description="Vertical "
        "alignment of viewport text", items=vpt_align_v_items)

    original_scene: StringProperty(name="Scene", default='Scene')

    def draw(self, context):
        use_vpt = self.use_vpt

        layout = self.layout

        row = layout.row()
        split = row.split(factor=0.5)
        split.prop(self, "copy_scene")
        split.prop(self, "restore_view")

        row = layout.row()
        split = row.split(factor=0.5)
        split.prop(self, "zoom_selected")
        split.prop(self, "use_vpt")
        layout.separator()

        if use_vpt:
            row = layout.row()
            split = row.split(factor=0.5)
            split.label(text="Viewport Text")
            split.label(text="Font Size")

            row = layout.row()
            split = row.split(factor=0.5)
            split.prop(self, "vpt_text", text="")
            split.prop(self, "vpt_size", text="")

            row = layout.row()
            split = row.split(factor=0.5)
            split.label(text="Horizontal Alignment")
            split.label(text="Vertical Alignment")

            row = layout.row()
            split = row.split(factor=0.5)
            split.prop(self, "vpt_align_h", text="")
            split.prop(self, "vpt_align_v", text="")

            layout.separator()
            layout.separator()


addon_keymaps = []

classes = (LocalScene, LocalSceneViewportText, LocalScenePreferences)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    wm = bpy.context.window_manager
    km = wm.keyconfigs.addon.keymaps.new(name='3D View', space_type='VIEW_3D')
    kmi = km.keymap_items.new(LocalScene.bl_idname, 'Q', 'PRESS', alt=True)
    addon_keymaps.append((km, kmi))
    add_handlers()


def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)

    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()
    local_scene_remove_handlers()
    for scene in bpy.data.scenes:
        if 'view_matrix' in scene:
            del scene['view_matrix']
    print("Local Scene Addon: Successfully unregistered")


if __name__ == "__main__":
    register()
