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


def get_indent(line, tab_width):
    tab, idx = " " * tab_width, 0
    while line.body.lstrip("#").find(tab, idx * tab_width) != -1:
        idx += 1
    return idx

def has_indented_comments(line):
    return line.body.startswith(" ")


class TEXT_OT_toggle_comment(bpy.types.Operator):
    bl_idname = "text.toggle_comment"
    bl_label = "Toggle Comment"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(self, context):
        return (context.area.type == 'TEXT_EDITOR' and context.space_data.text)

    def execute(self, context):

        # push two undos because blender sucks
        bpy.ops.ed.undo_push(message=self.bl_idname)

        st = context.space_data
        # tab_width = st.tab_width
        txt = st.text
        all_lines = txt.lines[:]
        inline = False
        index = all_lines.index
        bpy_ops_text = bpy.ops.text
        # print(txt.current_character)

        # selection range
        lin_a = txt.current_line_index
        lin_b = index(txt.select_end_line)
        col_a = txt.current_character
        col_b = txt.select_end_character
        # selected TextLine objects
        start, end = sorted((lin_a, lin_b))
        sel_lines = all_lines[start:end + 1]
        self.txt, self.index = txt, index

        # select line if only one, otherwise commenting will fail
        if len(sel_lines) == 1:
            # inline = True
            bpy_ops_text.select_line(False)
        print("preee", txt.current_character)

        # favor commenting if mixed lines
        non_empty = (l for l in sel_lines if l.body.strip())
        if all(l.body.startswith("#") for l in non_empty):

            # check indented comments since blender skips those
            # if all(has_indented_comments(l) for l in sel_lines):
            #     for l in sel_lines:
            #         indent = (" " * tab_width) * get_indent(l, tab_width)
            #         if indent:
            #             bod = l.body.lstrip().replace("#", "", 1)#.lstrip()
            #             l.body = indent + bod.lstrip()

            bpy_ops_text.uncomment()
            comment = False
        else:
            bpy_ops_text.comment()
            comment = True

        # nudge selection indices due to comment
        col_a += 1 if col_a and comment else -1 if col_a else 0
        col_b += 1 if col_b and comment else -1 if col_b else 0
        # ensure caret doesn't jump
        print("post", txt.current_character)
        set_select(self, lin_a, col_a, lin_b, col_b)

        # ensure caret index is not higher than body length
        # assert txt.select_end_character <= len(txt.select_end_line.body)
        # if inline:
        #     while txt.select_end_character > len(txt.select_end_line.body):
        #         print("moving")
        #         bpy.ops.text.move(type='PREVIOUS_CHARACTER')
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
