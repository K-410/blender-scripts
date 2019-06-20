import bpy

bl_info = {
    "name": "Text Smart Insert",
    "description": "",
    "author": "kaio",
    "version": (1, 0, 0),
    "blender": (2, 80, 0),
    "location": "Text Editor",
    "category": "Misc"
}

BRACKETS = {"(": ")", "[": "]", "{": "}"}
BRAC_REV = {value: key for key, value in BRACKETS.items()}
BRAC_UNI = {"\"", "\'"}


def set_select(txt, lin_a, col_a, lin_b, col_b):
    move, move_select = bpy.ops.text.move, bpy.ops.text.move_select
    prev, next = 'PREVIOUS_CHARACTER', 'NEXT_CHARACTER'
    up, dn = 'PREVIOUS_LINE', 'NEXT_LINE'

    while txt.current_line_index != lin_a:
        cur = txt.current_line_index
        move(False, type=up if cur > lin_a else dn)

    last = next_last = None
    while txt.current_character != col_a:
        cur = txt.current_character

        # workaround for tab being treated as single character
        if cur == next_last:
            break
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


def indexof(txt, line):
    return txt.lines[:].index(line)


def selection_as_string(txt):
    lin_a = txt.current_line_index
    lin_b = indexof(txt, txt.select_end_line)
    col_a = txt.current_character
    col_b = txt.select_end_character

    # store text without copying it to clipboard
    asc_idx = sorted((lin_a, lin_b))
    reverse = asc_idx != list((lin_a, lin_b))
    selslice = slice(*[(i, j + 1) for i, j in [asc_idx]][0])
    selection = [line.body for line in txt.lines[selslice]]
    inline = False

    if lin_a == lin_b:
        inline = True
        txt_sel = "\n".join(selection)[slice(*sorted((col_a, col_b)))]
        return txt_sel, inline, reverse, lin_a, lin_b, col_a, col_b

    else:
        if reverse:
            col_a, col_b = reversed((col_a, col_b))

        selection[0] = selection[0][col_a::]
        selection[-1] = selection[-1][:col_b]
        txt_sel = "\n".join(selection)
        return txt_sel, inline, reverse, lin_a, lin_b, col_a, col_b


def surround(self, txt, left, right):
    buffer, inline, reverse, lin_a,\
        lin_b, col_a, col_b = self._selection
    bpy.ops.text.insert(text=f"{buffer}{right}")

    # adjust selection indices to follow inserted chars
    if not inline:
        if not reverse:
            col_a += 1
        else:
            col_a, col_b = col_b, col_a
            col_b += 1
    else:
        col_a += 1
        col_b += 1
    set_select(txt, lin_a, col_a, lin_b, col_b)
    return {'FINISHED'}


def swallow(txt, pair):
    left, right = pair
    lin_a = txt.current_line_index
    lin_b = indexof(txt, txt.select_end_line)
    col_a = txt.current_character
    col_b = txt.select_end_character

    # swallowing brackets only works with no selection
    if col_a == col_b and lin_a == lin_b:
        if col_a == txt.current_line.body.find(right, col_a):
            if txt.current_line.body[col_a] == right:
                return bpy.ops.text.move(type="NEXT_CHARACTER")
    bpy.ops.text.insert(text=right)


def is_left_brac(in_chr):
    return BRACKETS.get(in_chr, False)


def is_right_brac(in_chr):
    return BRAC_REV.get(in_chr, False)


def is_uniform_brac(in_chr):
    return in_chr in BRAC_UNI


def swallow_brac():
    bpy.ops.text.delete(type='PREVIOUS_CHARACTER')
    return bpy.ops.text.move(type='NEXT_CHARACTER')


class TEXT_OT_smart_insert_internal(bpy.types.Operator):
    """Internal operator handling text operations"""
    bl_idname = "text.smart_insert_internal"
    bl_label = "Smart Insert Internal"
    bl_options = {'INTERNAL'}

    store: bpy.props.BoolProperty(options={'SKIP_SAVE', 'HIDDEN'})
    delete: bpy.props.BoolProperty(options={'SKIP_SAVE', 'HIDDEN'})

    # XXX use event.ascii or event.unicode to get typed character

    def invoke(self, context, event):
        print("ran")
        if self.delete:
            print("deleting")
            return bpy.ops.text.delete(type='PREVIOUS_CHARACTER')

        ctrl = event.ctrl
        alt = event.alt

        if alt and not ctrl:
            return {'PASS_THROUGH'}

        txt = context.space_data.text

        if self.store:
            # store selection before text.insert since it overwrites it
            __class__._selection = selection_as_string(txt)
            return {'FINISHED'}

        txt_sel, inline, reverse,\
            lin_a, lin_b, col_a, col_b = __class__._selection
        bod = txt.select_end_line.body
        caret = txt.select_end_character

        try:
            # get the typed character
            in_chr = bod[caret - 1]

            # make surround
            r_brac = is_left_brac(in_chr)
            if r_brac:

                # don't surround unless next char is whitespace or none:
                if len(bod) > caret:
                    if bod[caret] != " ":
                        if not __class__._selection:
                            print("not")
                            return {'FINISHED'}

                return surround(self, txt, in_chr, r_brac)

            # typed char is right bracket
            elif is_right_brac(in_chr):

                if len(bod) > caret and bod[caret] in BRAC_REV:
                    # swallow the typed char
                    return swallow_brac()

            # handle uniform brackets (ticks, quotes) differently
            elif is_uniform_brac(in_chr):

                # check if char ahead
                if len(bod) > caret:

                    # check if it matches with typed and no selection
                    if bod[caret] == in_chr and not txt_sel:
                        return swallow_brac()

                # don't count escaped quotes(like "\"", "\'")
                esc_substr = bod.count("\\" + in_chr)
                uni_brac_count = bod.count(in_chr) - esc_substr

                # surround if uni bracket count is even
                if float.is_integer(uni_brac_count * 0.5):

                    # check if char ahead, and not whitespace
                    if len(bod) > caret:
                        if bod[caret] != " ":
                            pass
                        else:
                            if bod[caret] == " ":
                                return surround(self, txt, in_chr, in_chr)
                else:
                    if len(bod) > caret and bod[caret] != " ":

                        if txt_sel or bod[caret] in BRAC_REV:
                            return surround(self, txt, in_chr, in_chr)
                    else:
                        return surround(self, txt, in_chr, in_chr)

        except IndexError:
            print("Illegal characters - bug?")
            return {'CANCELLED'}

        __class__._selection = ""

        # workaround for ctrl+backspace
        if ctrl and event.type == 'BACK_SPACE' and event.value == 'PRESS':
            return bpy.ops.text.delete(False, type='PREVIOUS_WORD')

        return {'FINISHED'}

    @classmethod
    def _setup(cls):
        cls._keymaps = []
        kc = bpy.context.window_manager.keyconfigs
        km = kc.default.keymaps.get('Text')
        if not km:
            return 0.1

        # disable default textinput kmi
        kmidef = km.keymap_items.get('text.insert')
        kmidef.active = False

        idname = "TEXT_OT_smart_insert"
        kmi = km.keymap_items.new(idname, 'TEXTINPUT', 'ANY')
        cls._keymaps.append((km, kmi, kmidef))

        # km = kc.addon.keymaps.get('Text')
        # if not km:
        #     km = kc.addon.keymaps.new('Text', space_type="TEXT_EDITOR")
        # kmi = km.keymap_items.new(idname, 'BACK_SPACE', 'PRESS')
        # kmi.properties['delete'] = 1
        # cls._keymaps.append((km, kmi, None))

    @classmethod
    def _remove(cls):
        for km, kmi, kmidef in cls._keymaps:
            km.keymap_items.remove(kmi)
            if hasattr(kmidef, "active"):
                kmidef.active = True
        cls._keymaps.clear()


# Smart Insert Macro is called by text input and executes a chain of operators
class TEXT_OT_smart_insert(bpy.types.Macro):
    bl_idname = 'text.smart_insert'
    bl_label = "Smart Insert"
    bl_options = {'UNDO', 'MACRO', 'INTERNAL'}

    @classmethod
    def _setup(cls):

        # store text selection for later
        cls.define("TEXT_OT_smart_insert_internal").properties.store = 1

        # because blender can't undo properly without it
        cls.define("ED_OT_undo_push").properties.message = cls.bl_label

        # actual text input operator
        cls.define("TEXT_OT_insert")

        # where the magic happens. surround, swallow, etc.
        cls.define("TEXT_OT_smart_insert_internal")


# dynamically get registerable blender classes
def classes():
    mod = globals().values()
    return [i for i in mod if hasattr(i, 'mro')
            and bpy.types.bpy_struct in i.mro()
            and i.__module__ == __name__]


def register():
    for cls in classes():
        bpy.utils.register_class(cls)
        if hasattr(cls, '_setup'):
            bpy.app.timers.register(cls._setup)


def unregister():
    for cls in reversed(classes()):
        if hasattr(cls, '_remove'):
            cls._remove()
        bpy.utils.unregister_class(cls)
