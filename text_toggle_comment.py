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


class TEXT_OT_toggle_comment(bpy.types.Operator):
    bl_idname = "text.toggle_comment"
    bl_label = "Toggle Comment"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(self, context):
        return (context.area.type == 'TEXT_EDITOR' and
                context.space_data.text)

    def get_indent(self, body, tab):
        indent = 0
        while body.find(" " * tab, indent * tab) != -1:
            indent += 1
        return indent

    # detect indented comments since blender doesn't
    def indented_comments(self, context, lines):
        tab = context.space_data.tab_width
        processed = []

        for line in lines:
            body = line.body
            if body.startswith(" "):
                if body.lstrip().startswith("#"):
                    processed.append(self.get_indent(body, tab))
                    continue
            processed.append(False)
        return any(processed), all(processed)

    def set_selection(self, text, index, selection, comment):
        line_a, col_a, line_b, col_b = selection
        bpy_ops_text = bpy.ops.text

        # keep relative selection, compensate for "#"
        col_a += 1 if col_a and comment else -1 if col_a else 0
        col_b += 1 if col_b and comment else -1 if col_b else 0

        while text.current_line_index != line_a:
            bpy_ops_text.move(
                type='PREVIOUS_LINE'
                if text.current_line_index > line_a else 'NEXT_LINE')

        last = next_last = None
        while text.current_character != col_a:
            # workaround for tab being treated as single character
            if text.current_character == next_last:
                break
            bpy_ops_text.move(
                type='PREVIOUS_CHARACTER'
                if text.current_character > col_a else 'NEXT_CHARACTER')
            next_last, last = last, text.current_character

        while index(text.select_end_line) != line_b:
            bpy_ops_text.move_select(
                type='PREVIOUS_LINE'
                if index(text.select_end_line) > line_b else 'NEXT_LINE')

        last = next_last = None
        while text.select_end_character != col_b:
            if text.select_end_character == next_last:
                break
            bpy_ops_text.move_select(
                type='PREVIOUS_CHARACTER'
                if text.select_end_character > col_b else 'NEXT_CHARACTER')
            next_last, last = last, text.select_end_character

    def execute(self, context):
        text = context.space_data.text
        bpy_ops_text = bpy.ops.text
        index = text.lines[:].index

        # selection range
        sel_range = (
            text.current_line_index,
            text.current_character,
            index(text.select_end_line),
            text.select_end_character)

        # selected TextLine objects
        line_a, line_b = text.current_line, text.select_end_line
        line_begin, line_end = sorted((index(line_a), index(line_b)))
        lines = text.lines[line_begin:line_end + 1]

        # print(self.indented_comments(context, lines))
        # select line if only one, otherwise commenting will fail
        if len(lines) == 1:
            bpy_ops_text.select_line()

        # favor commenting if not all non-blank lines all are commented
        non_empty = (l for l in lines if l.body.strip())
        if all(l.body.lstrip().startswith("#") for l in non_empty):
            bpy_ops_text.uncomment()
            comment = False
        else:
            bpy_ops_text.comment()
            comment = True

        # ensure caret doesn't jump
        self.set_selection(text, index, sel_range, comment)
        return {'FINISHED'}

    @classmethod
    def _setup(cls):
        keymaps = cls._keymaps = []
        kc = bpy.context.window_manager.keyconfigs.addon.keymaps
        km = kc.get('Text', kc.new(name='Text', space_type='TEXT_EDITOR'))
        kmi = km.keymap_items.new(__class__.bl_idname, 'D', 'PRESS', ctrl=True)
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
