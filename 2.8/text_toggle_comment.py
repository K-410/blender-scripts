import bpy

bl_info = {
    "name": "Toggle Comment",
    "description": "Add comment toggling in Text Editor on CTRL D",
    "author": "kaio",
    "version": (1, 0, 0),
    "blender": (2, 81, 0),
    "location": "Text Editor",
    "category": "Misc"
}


class TEXT_OT_toggle_comment(bpy.types.Operator):
    bl_idname = "text.toggle_comment"
    bl_label = "Toggle Comment"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return getattr(context.space_data, "text", False)

    def execute(self, context):
        bpy_ops_text = bpy.ops.text
        txt = context.space_data.text
        all_lines = txt.lines[:]
        index = all_lines.index

        # selection range as indices
        lin_a = txt.current_line_index
        lin_b = index(txt.select_end_line)
        col_a = txt.current_character
        col_b = txt.select_end_character

        start, end = sorted((lin_a, lin_b))
        sel = all_lines[start:end + 1]
        self.txt = txt

        # select line if only one, otherwise commenting will fail
        if len(sel) == 1:
            bpy_ops_text.select_line()

        # favor commenting if mixed lines
        non_empty = [l for l in sel if l.body.strip()]
        if all(l.body.startswith("#") for l in non_empty):

            type = 'UNCOMMENT'
            comment = False
        else:
            type = 'COMMENT'
            comment = True

        bpy_ops_text.comment_toggle(type=type)
        # nudge selection range due to comment
        col_a += 1 if col_a and comment else -1 if col_a else 0
        col_b += 1 if col_b and comment else -1 if col_b else 0

        # ensure caret doesn't jump, restore selection
        prev = 'PREVIOUS_CHARACTER'
        next = 'NEXT_CHARACTER'
        up = 'PREVIOUS_LINE'
        dn = 'NEXT_LINE'

        while txt.current_line_index != lin_a:
            cur = txt.current_line_index
            bpy_ops_text.move(type=cur > lin_a and up or dn)

        last = next_last = None
        while txt.current_character != col_a:
            cur = txt.current_character
            # workaround for tab being treated as single character
            if cur == next_last:
                break
            bpy_ops_text.move(type=cur > col_a and prev or next)
            next_last, last = last, cur

        while index(txt.select_end_line) != lin_b:
            end = index(txt.select_end_line)
            bpy_ops_text.move_select(type=end > lin_b and up or dn)

        last = next_last = None
        while txt.select_end_character != col_b:
            end = txt.select_end_character
            if end == next_last:
                break
            bpy_ops_text.move_select(type=end > col_b and prev or next)
            next_last, last = last, end

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
