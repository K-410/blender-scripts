import bpy

bl_info = {
    "name": "Expand to Brackets",
    "description": "Expands text selection at cursor to closest brackets",
    "author": "kaio",
    "version": (1, 0, 0),
    "blender": (2, 81, 0),
    "location": "Text Editor, Alt-A",
    "category": "Text Editor"
}


class TEXT_OT_expand_to_brackets(bpy.types.Operator):
    """Expands selection at cursor to closest brackets"""
    bl_idname = "text.expand_to_brackets"
    bl_label = "Expand to Brackets"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return getattr(context.space_data, "text", False)

    def select(self, txt, lin_a, col_a, lin_b, col_b):
        def indexof(txt, line):
            for idx, lin in enumerate(txt.lines):
                if line == lin:
                    return idx

        move, move_select = bpy.ops.text.move, bpy.ops.text.move_select
        prev, next = 'PREVIOUS_CHARACTER', 'NEXT_CHARACTER'
        up, dn = 'PREVIOUS_LINE', 'NEXT_LINE'
        indentation = txt.indentation
        txt.indentation = 'TABS'

        while txt.current_line_index != lin_a:
            cur = txt.current_line_index
            move(False, type=up if cur > lin_a else dn)

        last = next_last = None
        while txt.current_character != col_a:
            cur = txt.current_character

            move(False, type=prev if cur > col_a else next)
            next_last, last = last, txt.current_character

        while indexof(txt, txt.select_end_line) != lin_b:
            end = indexof(txt, txt.select_end_line)
            move_select(False, type=up if end > lin_b else dn)

        last = next_last = None
        while txt.select_end_character != col_b:
            end = txt.select_end_character
            if end == next_last:
                break
            move_select(False, type=prev if end > col_b else next)
            next_last, last = last, txt.select_end_character
        txt.indentation = indentation
        return {'FINISHED'}

    def execute(self, context):
        txt = context.space_data.text
        bod = txt.current_line.body
        curl = txt.current_line_index

        curc, selc = sorted((txt.current_character, txt.select_end_character))
        pos = range(curc, selc + 1)

        bopen = {k: v for k, v in zip("([{", ")]}")}
        bquot = {k: v for k, v in zip("\"'", "\"'")}
        bclose = {v: k for k, v in bopen.items()}

        # grow selection if at bracket/quote boundary
        if curc and selc < len(bod):
            if (bopen.get(bod[curc - 1]) == bod[selc] or
               bquot.get(bod[curc - 1]) == bod[selc]):
                return self.select(txt, curl, curc - 1, curl, selc + 1)

        # find quotes leading up to cursor
        bpre = []
        for i, c in enumerate(bod):
            if c in bquot and i < pos[0]:
                if bpre and c == bpre[-1][1]:
                    bpre.pop()
                elif c not in bpre:
                    bpre.append((i, c))

        # skip inner, escapable single-quotes
        if len(bpre) > 1 and bpre[-1][1] == "\'":
            bpre.pop()

        # determine if cursor is inside a quote
        if bpre and not (len(bpre) / 2).is_integer():
            qi, q = bpre[-1]
            for i, c in enumerate(bod[qi + 1:], qi + 1):
                if c == q:
                    return self.select(txt, curl, qi + 1, curl, i)

        # find the first (open) bracket leading up to cursor
        stack = []
        inner = outer = -1
        for i, c in enumerate(bod):
            if i < pos[0]:
                if c in bopen:
                    stack.append((i, c))
                elif stack and bclose.get(c) == stack[-1][1]:
                    stack.pop()
        if stack:
            inner = stack[-1][0]

            # find the first (closed) bracket after cursor
            stack2 = []
            for i, c in enumerate(bod[inner:], inner):
                if i >= pos[-1]:
                    if c in bopen:
                        stack2.append(c)
                    elif c in bclose:
                        if stack2 and bclose.get(c) == stack2[-1]:
                            stack2.pop()
                        elif bclose.get(c) == bod[inner]:
                            outer = i
                            break
            if outer != -1:
                return self.select(txt, curl, inner + 1, curl, outer)
        return {'CANCELLED'}

    @classmethod
    def _setup(cls):
        cls._keymaps = []
        kc = bpy.context.window_manager.keyconfigs.addon.keymaps
        km = kc.get('Text', kc.new(name='Text', space_type='TEXT_EDITOR'))
        kmi = km.keymap_items.new(cls.bl_idname, 'A', 'PRESS', alt=1)
        cls._keymaps.append((km, kmi))

    @classmethod
    def _remove(cls):
        for km, kmi in cls._keymaps:
            km.keymap_items.remove(kmi)
        cls._keymaps.clear()


def register():
    bpy.utils.register_class(TEXT_OT_expand_to_brackets)
    TEXT_OT_expand_to_brackets._setup()


def unregister():
    TEXT_OT_expand_to_brackets._remove()
    bpy.utils.unregister_class(TEXT_OT_expand_to_brackets)
