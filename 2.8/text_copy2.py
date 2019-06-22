import bpy

bl_info = {
    "name": "Text Copy 2",
    "description": "Convenience operators for text editor",
    "author": "kaio",
    "version": (1, 0, 0),
    "blender": (2, 80, 0),
    "location": "Text Editor",
    "category": "Misc"
}


def get_cursor_pos(context, text):
    line = text.current_line_index
    column = text.current_character
    x, y = context.space_data.region_location_from_cursor(line, column)
    return x, y + 10


class TEXT_OT_smart_cut_and_copy(bpy.types.Operator):
    """Cut or copy line at caret if no selection is made
    Ctrl-C, Ctrl-X, Ctrl-V"""
    bl_idname = 'text.smart_cut_and_copy'
    bl_label = 'Smart Cut and Copy'

    _smart_cut = _smart_copy = False
    _last_action = 'INLINE'
    _last_buffer = None

    buffer = None

    _actions = (
        ('CUT', 'Cut', '', 0),
        ('COPY', 'Copy', '', 1),
        ('PASTE', 'Paste', '', 2))

    action: bpy.props.EnumProperty(items=_actions, options={'HIDDEN'})

    @classmethod
    def poll(self, context):
        return context.area.type == 'TEXT_EDITOR' and context.space_data.text

    # True if text has no selection
    def no_selection(self, text):
        return (text.current_line == text.select_end_line and
                text.current_character == text.select_end_character)

    def indexof(self, line, lines):
        for idx, ln in enumerate(lines):
            if ln == line:
                return idx

    def clipboard(self, context):
        return context.window_manager.clipboard

    def copy_selection(self, context, txt):
        wm = context.window_manager
        line_a = txt.current_line_index
        line_b = self.indexof(txt.select_end_line, txt.lines)

        cur_chr = txt.current_character
        end_chr = txt.select_end_character

        asc_idx = sorted((line_a, line_b))
        reverse = asc_idx != list((line_a, line_b))

        selection_slice = slice(*[(i, j + 1) for i, j in [asc_idx]][0])
        selection = [line.body for line in txt.lines[selection_slice]]

        if line_a == line_b:
            inline = "\n".join(selection)[slice(*sorted((cur_chr, end_chr)))]
            wm.clipboard = __class__.buffer = inline
            return

        if reverse:
            cur_chr, end_chr = reversed((cur_chr, end_chr))

        selection[0] = selection[0][cur_chr::]
        selection[-1] = selection[-1][:end_chr]

        wm.clipboard = __class__.buffer = "\n".join(selection)

    def execute(self, context):
        cls = __class__
        wm = context.window_manager
        bpy_ops_text = bpy.ops.text
        text = context.space_data.text
        no_selection = self.no_selection(text)
        x, y = get_cursor_pos(context, text)

        # workaround for buggy text editor undo
        bpy.ops.ed.undo_push(message="Smart Cut/Copy")
        bpy.ops.ed.undo_push(message="Smart Cut/Copy")

        cur_ind = text.current_line_index
        end_ind = text.lines[:].index(text.select_end_line)
        topmost = (cur_ind, end_ind) == (0, 0)

        if self.action == 'CUT':
            cls._smart_cut = False
            cls._last_action = 'INLINE'

            if no_selection:
                cls._smart_cut = True
                cls._last_action = 'LINE'

                # workaround for topmost line
                if topmost:
                    print("cut topmost")
                    bpy_ops_text.select_line()
                    self.copy_selection(context, text)
                    bpy_ops_text.cut()
                    bpy_ops_text.delete(type="NEXT_CHARACTER")
                    wm.clipboard = __class__.buffer = "\n" + __class__.buffer
                    return {'FINISHED'}

                bpy_ops_text.move(type='LINE_END')
                bpy_ops_text.move_select(type='PREVIOUS_LINE')
                bpy_ops_text.move_select(type='LINE_END')
                self.copy_selection(context, text)
                bpy_ops_text.cut()
                return bpy_ops_text.cursor_set(x=x, y=y)

            return bpy_ops_text.cut()

        if self.action == 'COPY':
            cls._smart_copy = False
            cls._last_action = 'INLINE'

            if no_selection:
                cls._smart_copy = True
                cls._last_action = 'LINE'

                # workaround for topmost line
                if topmost:
                    bpy_ops_text.select_line()
                    self.copy_selection(context, text)
                    bpy_ops_text.copy()
                    bpy_ops_text.move(type="LINE_END")
                    wm.clipboard = __class__.buffer = "\n" + __class__.buffer
                    return {'FINISHED'}

                bpy_ops_text.move(type='PREVIOUS_LINE')
                bpy_ops_text.move(type='LINE_END')
                bpy_ops_text.move_select(type='NEXT_LINE')
                bpy_ops_text.move_select(type='LINE_END')
                self.copy_selection(context, text)
                return bpy_ops_text.cursor_set(x=x, y=y)
            self.copy_selection(context, text)
            print("RAN")
            return {'FINISHED'}

        if self.action == 'PASTE':
            if ((cls._smart_cut or cls._smart_copy) and
               cls.buffer == wm.clipboard):

                if cls._last_action == 'LINE':

                    # workaround for topmost line cutting and pasting
                    if topmost:
                        bpy_ops_text.move(type='FILE_TOP')

                        if cls.buffer.startswith("\n"):
                            wm.clipboard = cls.buffer[1:] + "\n"

                        bpy_ops_text.paste()
                        wm.clipboard = cls.buffer

                    else:
                        bpy_ops_text.move(type='PREVIOUS_LINE')
                        bpy_ops_text.move(type='LINE_END')
                        bpy_ops_text.paste()
                    bpy_ops_text.cursor_set(x=x, y=y)
                    return {'FINISHED'}
            return bpy_ops_text.paste()

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
    return [i for i in mod if hasattr(i, 'mro')
            and bpy.types.bpy_struct in i.mro()
            and i.__module__ == __name__]


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
