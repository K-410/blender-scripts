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
        txt = context.space_data.text

        def index(_line):
            for i, line in enumerate(txt.lines):
                if line == _line:
                    return i

        # selection range as indices
        lin_a = txt.current_line_index
        lin_b = index(txt.select_end_line)
        col_a = txt.current_character
        col_b = txt.select_end_character

        start, end = sorted((lin_a, lin_b))
        sel = txt.lines[start:end + 1]
        self.txt = txt

        # select line if only one, otherwise commenting will fail
        if len(sel) == 1:
            bpy.ops.text.select_line()

        non_empty = [l for l in sel if l.body.strip()]
        type = 'COMMENT'
        comment = True
        if all(l.body.startswith("#") for l in non_empty):
            type = 'UNCOMMENT'
            comment = False

        bpy.ops.text.comment_toggle(type=type)
        # nudge selection range due to comment
        col_a += 1 if col_a and comment else -1 if col_a else 0
        col_b += 1 if col_b and comment else -1 if col_b else 0

        # ensure caret doesn't jump, restore selection
        move, select = bpy.ops.text.move, bpy.ops.text.move_select
        left, right = 'PREVIOUS_CHARACTER', 'NEXT_CHARACTER'
        up, down = 'PREVIOUS_LINE', 'NEXT_LINE'
        indentation = txt.indentation
        txt.indentation = 'TABS'
        for _ in range(abs(txt.current_line_index - lin_a)):
            move(type=up if txt.current_line_index > lin_a else down)
        for _ in range(abs(txt.current_character - col_a)):
            move(type=left if txt.current_character > col_a else right)
        for _ in range(abs(index(txt.select_end_line) - lin_b)):
            select(type=up if index(txt.select_end_line) > lin_b else down)
        for _ in range(abs(txt.select_end_character - col_b)):
            select(type=left if txt.select_end_character > col_b else right)
        txt.indentation = indentation

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
