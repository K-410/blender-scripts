import bpy

bl_info = {
    "name": "Text Insert 2",
    "description": "",
    "author": "kaio",
    "version": (1, 0, 0),
    "blender": (2, 80, 0),
    "location": "Text Editor",
    "category": "Misc"
}

BR_L = {"(": ")", "[": "]", "{": "}"}
BR_R = {value: key for key, value in BR_L.items()}
BR_U = {"\"", "\'"}


def indexof(txt, line):
    return txt.lines[:].index(line)


def is_left_brac(in_chr):
    return BR_L.get(in_chr, False)


def is_right_brac(in_chr):
    return BR_R.get(in_chr, False)


def is_uniform_brac(in_chr):
    return in_chr in BR_U


def is_match(chr_a, chr_b):
    if chr_b in BR_R and chr_a in BR_L:
        if BR_L[chr_a] == chr_b:
            return True

    elif chr_b in BR_U and chr_a in BR_U:
        if chr_b == chr_a:
            return True
    return False


def is_char_ahead(txt):
    return len(txt.select_end_line.body) > txt.select_end_character


def get_char_ahead(txt):
    return txt.select_end_line.body[txt.select_end_character]


def is_no_selection(txt):
    return (txt.current_line == txt.select_end_line and
            txt.current_character == txt.select_end_character)


def delete_prev_next():
    bpy.ops.text.delete(type='PREVIOUS_CHARACTER')
    bpy.ops.text.move(type='NEXT_CHARACTER')
    return bpy.ops.text.delete(type='PREVIOUS_CHARACTER')


def swallow_brac():
    bpy.ops.text.delete(type='PREVIOUS_CHARACTER')
    return bpy.ops.text.move(type='NEXT_CHARACTER')


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

    # else:
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
            col_a, col_b = col_b, col_a + 1
    else:
        col_a, col_b = col_a + 1, col_b + 1
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


def delete_backspace(txt):
    bod = txt.select_end_line.body
    caret = txt.select_end_character

    if is_char_ahead(txt):

        if is_no_selection(txt):
            # delete prev/next brackets if they match
            if is_match(bod[caret - 1], bod[caret]):
                return delete_prev_next()

    return bpy.ops.text.delete(type='PREVIOUS_CHARACTER')


class TEXT_OT_insert2_internal(bpy.types.Operator):
    """Internal operator handling text operations"""
    bl_idname = "text.insert2_internal"
    bl_label = "Insert 2 Internal"
    bl_options = {'INTERNAL'}

    _selection = [...] * 7
    _unicodes = {"@", "£", "$", "€", "~", "|", "µ", "¤"}
    store: bpy.props.BoolProperty(options={'SKIP_SAVE', 'HIDDEN'})
    delete: bpy.props.BoolProperty(options={'SKIP_SAVE', 'HIDDEN'})

    # TODO use event.unicode to get typed character

    def invoke(self, context, event):
        txt = context.space_data.text

        # delete opposite matching bracket if it exists
        if self.delete:
            return delete_backspace(txt)

        ctrl = event.ctrl
        alt = event.alt

        # ignore ctrl, but allow non-ascii chars to pass
        if alt and not ctrl and event.unicode not in self._unicodes:
            return {'PASS_THROUGH'}

        if self.store:
            # store selection before text.insert since it overwrites it
            __class__._selection = selection_as_string(txt)
            return {'FINISHED'}

        txt_sel, inline, reverse,\
            lin_a, lin_b, col_a, col_b = __class__._selection
        bod = txt.select_end_line.body
        caret = txt.select_end_character

        try:
            in_chr = event.unicode  # get the typed character
            r_brac = is_left_brac(in_chr)
            if r_brac:
                if is_char_ahead(txt):
                    chr_r = get_char_ahead(txt)
                    # don't surround unless next char is whitespace or none
                    # or if next character is not the matching bracket
                    if chr_r != " " and chr_r != BR_L.get(in_chr):
                        if lin_a == lin_b and col_a == col_b:
                            return {'FINISHED'}

                return surround(self, txt, in_chr, r_brac)

            elif is_right_brac(in_chr):  # typed char is right bracket
                if is_char_ahead(txt) and bod[caret] in BR_R:
                    return swallow_brac()  # swallow the typed char

            elif is_uniform_brac(in_chr):  # handle (ticks, quotes) differently
                if is_char_ahead(txt):

                    # check if it matches with typed and no selection
                    if bod[caret] == in_chr and not txt_sel:
                        return swallow_brac()

                # don't count escaped chars
                uni_count = bod.count(in_chr) - bod.count("\\" + in_chr)
                if float.is_integer(uni_count * 0.5):  # surround if even
                    if is_char_ahead(txt):
                        if bod[caret] != " ":
                            pass
                        else:
                            if bod[caret] == " ":
                                return surround(self, txt, in_chr, in_chr)
                else:
                    if is_char_ahead(txt) and bod[caret] != " ":
                        if txt_sel or bod[caret] in BR_R:
                            return surround(self, txt, in_chr, in_chr)
                    else:
                        return surround(self, txt, in_chr, in_chr)

        except IndexError:
            # bug with non-ascii characters being counted differently
            # see https://developer.blender.org/T65843
            return {'CANCELLED'}

        __class__._selection = [...] * 7

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

        # disable default textinput insert kmi
        kmidef = km.keymap_items.get('text.insert')
        kmidef.active = False
        new = km.keymap_items.new

        kmi = new("TEXT_OT_insert2", 'TEXTINPUT', 'ANY')
        cls._keymaps.append((km, kmi, kmidef))

        # disable default backspace delete kmi
        kmidef = get_default_kmi(km, "text.delete", "BACK_SPACE", "PRESS")
        assert kmidef is not None and kmidef.type == "BACK_SPACE"
        kmidef.active = False
        kmi = new("TEXT_OT_insert2_internal", 'BACK_SPACE', 'PRESS')
        kmi.properties.delete = 1
        cls._keymaps.append((km, kmi, kmidef))

    @classmethod
    def _remove(cls):
        for km, kmi, kmidef in cls._keymaps:
            km.keymap_items.remove(kmi)
            if hasattr(kmidef, "active"):
                kmidef.active = True
        cls._keymaps.clear()


# find a kmi from blender's default keymap
def get_default_kmi(km, kmi_idname, kmi_type, kmi_value):
    matches = (k for k in km.keymap_items if k.idname == kmi_idname)
    for kmi in matches:
        if kmi_type == kmi.type:
            if kmi_value == kmi.value:
                return kmi


# Insert 2 is called by text input and executes a chain of operators
class TEXT_OT_insert2(bpy.types.Macro):
    bl_idname = 'text.insert2'
    bl_label = "Insert 2"
    bl_options = {'UNDO', 'MACRO', 'INTERNAL'}

    @classmethod
    def _setup(cls):

        # store text selection for later
        cls.define("TEXT_OT_insert2_internal").properties.store = 1

        # because blender can't undo properly without it
        cls.define("ED_OT_undo_push").properties.message = cls.bl_label

        # actual text input operator
        # TODO replace with event.unicode XXX needs a lot of behavior rewrite
        cls.define("TEXT_OT_insert")

        # surround, swallow, special behavior etc.
        cls.define("TEXT_OT_insert2_internal")


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
