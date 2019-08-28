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

    def index(self, txt, line):
        for idx, lin in enumerate(txt.lines):
            if line == lin:
                return idx

    def select(self, txt, l1, l2, c1, c2):

        move = bpy.ops.text.move
        select = bpy.ops.text.move_select

        left = 'PREVIOUS_CHARACTER'
        right = 'NEXT_CHARACTER'
        up = 'PREVIOUS_LINE'
        down = 'NEXT_LINE'

        indentation = txt.indentation
        txt.indentation = 'TABS'
        index = self.index

        while txt.current_line_index != l1:
            move(type=up if txt.current_line_index > l1 else down)

        while txt.current_character != c1:
            move(type=left if txt.current_character > c1 else right)

        while index(txt, txt.select_end_line) != l2:
            select(type=up if index(txt, txt.select_end_line) > l2 else down)

        while txt.select_end_character != c2:
            select(type=left if txt.select_end_character > c2 else right)

        txt.indentation = indentation
        return {'FINISHED'}

    def execute(self, context):
        txt = context.space_data.text
        l1, l2 = txt.current_line_index, self.index(txt, txt.select_end_line)
        start, end = sorted((l1, l2))
        c1 = txt.current_character
        c2 = txt.select_end_character
        sel = txt.lines[start: end + 1]

        # select line if only one, otherwise commenting will fail
        if len(sel) == 1:
            bpy.ops.text.select_line()

        # favor commenting if mixed lines
        non_empty = [l for l in sel if l.body.strip()]
        com = not all(l.body.startswith("#") for l in non_empty)
        bpy.ops.text.comment_toggle(type="COMMENT" if com else "UNCOMMENT")
        # nudge selection range due to comment
        c1 += 1 if c1 and com else -1 if c1 else 0
        c2 += 1 if c2 and com else -1 if c2 else 0

        return self.select(txt, l1, l2, c1, c2)

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
