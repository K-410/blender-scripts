import bpy

bl_info = {
    "name": "Toggle Comment",
    "description": "Toggle Comment",
    "author": "kaio",
    "version": (1, 0, 0),
    "blender": (2, 80, 0),
    "location": "Text Editor",
    "category": "Misc"
}


# restore text selection
def set_select(self, lin_a, col_a, lin_b, col_b):
    txt, index = self.txt, self.index
    prev, next = 'PREVIOUS_CHARACTER', 'NEXT_CHARACTER'
    up, dn = 'PREVIOUS_LINE', 'NEXT_LINE'
    bpy_ops_text = bpy.ops.text

    while txt.current_line_index != lin_a:
        cur = txt.current_line_index
        bpy_ops_text.move(False, type=up if cur > lin_a else dn)

    last = next_last = None
    while txt.current_character != col_a:
        cur = txt.current_character
        # workaround for tab being treated as single character
        if cur == next_last:
            break
        bpy_ops_text.move(False, type=prev if cur > col_a else next)
        next_last, last = last, cur

    while index(txt.select_end_line) != lin_b:
        end = index(txt.select_end_line)
        bpy_ops_text.move_select(False, type=up if end > lin_b else dn)

    last = next_last = None
    while txt.select_end_character != col_b:
        end = txt.select_end_character
        if end == next_last:
            break
        bpy_ops_text.move_select(False, type=prev if end > col_b else next)
        next_last, last = last, end


class TEXT_OT_toggle_comment(bpy.types.Operator):
    bl_idname = "text.toggle_comment"
    bl_label = "Toggle Comment"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.area.type == 'TEXT_EDITOR' and context.space_data.text)

    def execute(self, context):

        # push two undos because blender sucks
        bpy.ops.ed.undo_push(message=self.bl_idname)

        txt = context.space_data.text
        all_lines = txt.lines[:]
        index = all_lines.index

        # selection range as indices
        lin_a = txt.current_line_index
        lin_b = index(txt.select_end_line)
        col_a = txt.current_character
        col_b = txt.select_end_character

        start, end = sorted((lin_a, lin_b))
        sel_lines = all_lines[start:end + 1]
        self.txt, self.index = txt, index

        # select line if only one, otherwise commenting will fail
        if len(sel_lines) == 1:
            bpy.ops.text.select_line(False)

        # favor commenting if mixed lines
        non_empty = (l for l in sel_lines if l.body.strip())
        if all(l.body.startswith("#") for l in non_empty):

            bpy.ops.text.uncomment()
            comment = False
        else:
            bpy.ops.text.comment()
            comment = True

        # nudge selection range due to comment
        col_a += 1 if col_a and comment else -1 if col_a else 0
        col_b += 1 if col_b and comment else -1 if col_b else 0

        # ensure caret doesn't jump
        set_select(self, lin_a, col_a, lin_b, col_b)
        return {'FINISHED'}

    @classmethod
    def _setup(cls):
        keymaps = cls._keymaps = []
        kc = bpy.context.window_manager.keyconfigs.addon.keymaps
        km = kc.get('Text', kc.new(name='Text', space_type='TEXT_EDITOR'))
        kmi = km.keymap_items.new(cls.bl_idname, 'D', 'PRESS', ctrl=True)
        keymaps.append((km, kmi))

    @classmethod
    def _remove(cls):
        for km, kmi in cls._keymaps:
            km.keymap_items.remove(kmi)
        cls._keymaps.clear()


def register():
    bpy.utils.register_class(TEXT_OT_toggle_comment)
    TEXT_OT_toggle_comment._setup()


def unregister():
    TEXT_OT_toggle_comment._remove()
    bpy.utils.unregister_class(TEXT_OT_toggle_comment)
