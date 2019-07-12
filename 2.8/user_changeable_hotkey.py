# example showing how to draw addon keymap items in preferences
# and letting the user change the value

# works by storing kmi values in addon preferences, then retrieved
# from preferences when the addon is registered (blender startup)
import bpy


bl_info = {
    "name": "*User Changeable Hotkey",
    "description": "How to allow users change addon hotkeys",
    "author": "kaio",
    "version": (1, 0, 0),
    "blender": (2, 80, 0),
    "location": "3D View",
    "category": "3D View",
}


class SomePreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    kmi_type: bpy.props.StringProperty()
    kmi_value: bpy.props.StringProperty()
    kmi_alt: bpy.props.BoolProperty()
    kmi_ctrl: bpy.props.BoolProperty()
    kmi_shift: bpy.props.BoolProperty()

    def draw(self, context):
        layout = self.layout
        col = layout.column()
        kmi = self.ensure_kmi()

        if kmi:
            draw_kmi(kmi, layout, col, 1, 1)

    # when the user changes a key, the ui is redrawn and this is
    # called to sync kmi_type, kmi_alt, kmi_ctrl and kmi_shift
    # with actual kmi values
    def ensure_kmi(self):
        try:
            kmi = addon_keymaps[0][1]
        except IndexError:
            return False

        else:
            # it's important to use conditionals because
            # this runs every time the ui is redrawn
            if kmi.type != self.kmi_type:
                self.kmi_type = kmi.type
            if kmi.value != self.kmi_value:
                self.kmi_value = kmi.value
            if kmi.alt != self.kmi_alt:
                self.kmi_alt = kmi.alt
            if kmi.ctrl != self.kmi_ctrl:
                self.kmi_ctrl = kmi.ctrl
            if kmi.shift != self.kmi_shift:
                self.kmi_shift = kmi.shift
        return kmi


# ui draw function for kmi
# a more complete version can be found in scripts/modules/rna_keymap_ui.py
def draw_kmi(kmi, layout, col, kmi_count, kmi_idx):
    map_type = kmi.map_type

    col = col.column(align=True)
    row = col.row()
    row.scale_y = 1.3
    split = row.split()
    row = split.row()
    row.alignment = 'RIGHT'
    row.label(text="Hotkey")
    row = split.row(align=True)
    row.prop(kmi, "type", text="", full_event=True)
    split.separator(factor=0.5)

    col.separator(factor=3)
    row = col.row()
    split = row.split()
    row = split.row()
    row.alignment = 'RIGHT'
    row.label(text="Type")
    row = split.row()
    row.prop(kmi, "value", text="")
    split.separator(factor=0.5)

    if map_type not in {'TEXTINPUT', 'TIMER'}:

        col.separator(factor=3)
        row = col.row()
        split = row.split()
        row = split.row()
        row.alignment = 'RIGHT'
        row.label(text="Modifier")

        row = split.row(align=True)
        row.prop(kmi, "any", toggle=True)
        row.prop(kmi, "shift", toggle=True)
        row.prop(kmi, "ctrl", toggle=True)
        split.separator(factor=0.5)

        row = col.row(align=True)
        split = row.split()
        split.separator()

        row = split.row(align=True)
        row.prop(kmi, "alt", toggle=True)
        row.prop(kmi, "oskey", text="Cmd", toggle=True)
        row.prop(kmi, "key_modifier", text="", event=True)
        split.separator(factor=0.5)


addon_keymaps = []


def register():
    bpy.utils.register_class(SomePreferences)

    p = bpy.context.preferences.addons[__name__].preferences

    # during addon registration, get the kmi values stored in preferences.
    # if they are none (usually after install), resort to default value
    default_type = "W"
    default_value = "PRESS"

    kmi_type = p.kmi_type or default_type
    kmi_value = p.kmi_value or default_value
    print(kmi_value)
    print(12345)

    alt = p.kmi_alt or 0
    ctrl = p.kmi_ctrl or 0
    shift = p.kmi_shift or 0

    kc = bpy.context.window_manager.keyconfigs.addon
    km = kc.keymaps.get('3D View')
    if not km:
        km = kc.keymaps.new('3D View', space_type='VIEW_3D')

    kwargs = {'alt': alt, 'ctrl': ctrl, 'shift': shift}
    kmi = km.keymap_items.new(
        "object.select_all", kmi_type, kmi_value, **kwargs)
    addon_keymaps.append((km, kmi))


def unregister():
    bpy.utils.unregister_class(SomePreferences)
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()
