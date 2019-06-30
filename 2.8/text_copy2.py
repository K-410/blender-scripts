import bpy

bl_info = {
    "name": "Text Copy 2",
    "description": "Convenience operators for text editor",
    "author": "kaio",
    "version": (1, 0, 2),
    "blender": (2, 80, 0),
    "location": "Text Editor",
    "category": "Misc"
}


class TEXT_OT_smart_cut_and_copy(bpy.types.Operator):
    """Cut or copy line at caret if no selection is made
    Ctrl-C, Ctrl-X, Ctrl-V"""
    bl_idname = 'text.smart_cut_and_copy'
    bl_label = 'Smart Cut and Copy'
    bl_options = {'REGISTER', 'UNDO'}

    _actions = (
        ('CUT', 'Cut', '', 0),
        ('COPY', 'Copy', '', 1),
        ('PASTE', 'Paste', '', 2))

    action: bpy.props.EnumProperty(items=_actions, options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return context.area.type == 'TEXT_EDITOR' and context.space_data.text

    @classmethod
    def prepare_cursor(cls, text):

        curl = text.current_line
        sell = text.select_end_line
        curc = text.current_character
        selc = text.select_end_character
        size = len(text.lines)

        if curl == sell and curc == selc:
            cls._whole_line = True

            bpy.ops.text.move(type='LINE_BEGIN')

            # if line is soft-wrapped, move cursor to true start
            while text.select_end_character:
                bpy.ops.text.move(type='PREVIOUS_LINE')

            bpy.ops.text.move_select(type='NEXT_LINE')

            # if line is soft-wrapped, select until true end
            while (text.select_end_character and
                   text.current_line_index < size - 1):
                bpy.ops.text.move_select(type='NEXT_LINE')
        else:
            cls._whole_line = False

    def execute(self, context):
        text = context.space_data.text
        whole_line = getattr(__class__, "_whole_line", False)

        if self.action == 'CUT':
            self.prepare_cursor(text)
            return bpy.ops.text.cut()

        if self.action == 'COPY':
            self.prepare_cursor(text)
            return bpy.ops.text.copy()

        if self.action == 'PASTE':
            if whole_line:
                bpy.ops.text.move(type='LINE_BEGIN')
            return bpy.ops.text.paste()

        return {'CANCELLED'}

    @classmethod
    def _setup(cls):
        cls._keymaps = []
        kc = bpy.context.window_manager.keyconfigs.addon.keymaps
        get, new = kc.get, kc.new
        km = get('Text', new(name='Text', space_type='TEXT_EDITOR'))

        new = km.keymap_items.new
        kmi = new(cls.bl_idname, 'X', 'PRESS', ctrl=True)
        kmi.properties['action'] = 0
        cls._keymaps.append((km, kmi))

        kmi = new(cls.bl_idname, 'C', 'PRESS', ctrl=True)
        kmi.properties['action'] = 1
        cls._keymaps.append((km, kmi))

        kmi = new(cls.bl_idname, 'V', 'PRESS', ctrl=True)
        kmi.properties['action'] = 2
        cls._keymaps.append((km, kmi))

    @classmethod
    def _remove(cls):
        for km, kmi in cls._keymaps:
            km.keymap_items.remove(kmi)
        cls._keymaps.clear()


def classes():
    mod = globals().values()
    return [i for i in mod if hasattr(i, 'mro') and
            bpy.types.bpy_struct in i.mro() and
            i.__module__ == __name__]


def register():
    for cls in classes():
        bpy.utils.register_class(cls)
        if hasattr(cls, '_setup'):
            cls._setup()


def unregister():
    for cls in reversed(classes()):
        if hasattr(cls, '_remove'):
            cls._remove()
        bpy.utils.unregister_class(cls)
