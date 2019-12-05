# cleanup redundant functions
# move small, single-use functions into execute body
# fix surround being triggered erroneously
# add auto-indent on line break if previous char is a left bracket
# remove undo macro and undo push after fix https://developer.blender.org/D5222

# added move toggle operator

# TODO design: move all behavior into one operator
# TODO disable surround if line is commented
# TODO add comment sign on line break on commented lines
import bpy

bl_info = {
    "name": "Text Insert 2",
    "description": "",
    "author": "kaio",
    "version": (1, 0, 0),
    "blender": (2, 80, 0),
    "location": "Text Editor",
    "category": "Text Editor"
}
_BRACKETS = "()", ")(", "[]", "][", "{}", "}{", "\"\"", "\'\'"
BRACKETS = {left: right for left, right in _BRACKETS}
BRACKETS_L = {"(": ")", "[": "]", "{": "}"}
BRACKETS_R = {value: key for key, value in BRACKETS_L.items()}
BRACKETS_U = {"\"", "\'"}
BRACKETS_ALL = {*BRACKETS_L.keys(), *BRACKETS_R.keys(), *BRACKETS_U}


def is_match(chr_a, chr_b):
    if chr_b in BRACKETS_R and chr_a in BRACKETS_L:
        if BRACKETS_L[chr_a] == chr_b:
            return True

    elif chr_b in BRACKETS_U and chr_a in BRACKETS_U:
        if chr_b == chr_a:
            return True
    return False


def swallow_brac():
    bpy.ops.text.delete(type='PREVIOUS_CHARACTER')
    return bpy.ops.text.move(type='NEXT_CHARACTER')


def selection_as_string(txt):
    curl = txt.current_line_index
    sell = txt.select_end_line_index
    curc = txt.current_character
    selc = txt.select_end_character

    a, b = sorted((curl, sell))
    selection = [line.body for line in txt.lines[a:b + 1]]

    reverse = False
    inline = curl == sell
    if inline:
        curc, selc = sorted((curc, selc))
        sel_string = "".join(selection)[curc:selc]

    else:
        if (a, b) != (curl, sell):
            reverse = True
            curc, selc = selc, curc

        selection[0] = selection[0][curc:]
        selection[-1] = selection[-1][:selc]
        sel_string = "\n".join(selection)
    return sel_string, inline, reverse, curl, sell, curc, selc


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
    txt.select_set(lin_a, col_a, lin_b, col_b)
    return {'FINISHED'}


def delete_backspace(txt):
    bod = txt.select_end_line.body
    caret = txt.select_end_character

    if len(bod) > caret:

        if (txt.current_line == txt.select_end_line and
           txt.current_character == txt.select_end_character):
            # delete prev/next brackets if they match
            if is_match(bod[caret - 1], bod[caret]):
                bpy.ops.text.delete(type='PREVIOUS_CHARACTER')
                bpy.ops.text.move(type='NEXT_CHARACTER')
                return bpy.ops.text.delete(type='PREVIOUS_CHARACTER')

    return bpy.ops.text.delete(type='PREVIOUS_CHARACTER')


class TEXT_OT_insert2_internal(bpy.types.Operator):
    """Internal operator handling text operations"""
    bl_idname = "text.insert2_internal"
    bl_label = "Insert 2 Internal"
    bl_options = {'INTERNAL'}

    _selection = [...] * 7
    _unicodes = {"@", "£", "$", "€", "~", "|", "µ", "¤", "[", "]", "{", "}"}
    store: bpy.props.BoolProperty(options={'SKIP_SAVE', 'HIDDEN'})
    delete: bpy.props.BoolProperty(options={'SKIP_SAVE', 'HIDDEN'})

    # TODO use event.unicode to get typed character

    @classmethod
    def poll(cls, context):
        return getattr(context, "edit_text", None)

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
        end = txt.select_end_character

        if len(bod) > txt.select_end_character:
            chr_next = bod[end]
        else:
            chr_next = ""
        try:
            in_chr = event.unicode  # get the typed character
            r_brac = BRACKETS_L.get(in_chr)
            if r_brac:
                if chr_next:
                    # don't surround unless next char is whitespace or none
                    # or if next character is not the matching bracket
                    if chr_next != " " and chr_next not in BRACKETS_ALL:
                        # check if next chr is the matching bracket
                        if (chr_next == BRACKETS_R[BRACKETS_L[in_chr]] or
                           chr_next not in BRACKETS_ALL or
                           chr_next in BRACKETS_L):
                            # check if no selection
                            if lin_a == lin_b and col_a == col_b:
                                return {'FINISHED'}
                        # check if next chr is a left bracket
                return surround(self, txt, in_chr, r_brac)

            elif in_chr in BRACKETS_R:  # typed char is right bracket
                r_brac = BRACKETS_L.get(BRACKETS_R[in_chr])
                if BRACKETS_R[in_chr] in BRACKETS_L:
                    # swallow only if the bracket types are identical
                    if chr_next == r_brac:
                        return swallow_brac()  # swallow the typed char

            elif in_chr in BRACKETS_U:  # see if typed is quotation marks
                if chr_next:

                    # check if it matches with typed and no selection
                    if chr_next == in_chr and not txt_sel:
                        return swallow_brac()

                # don't count escaped chars
                uni_count = bod.count(in_chr) - bod.count("\\" + in_chr)
                if float.is_integer(uni_count * 0.5):  # surround if even
                    if chr_next:
                        if chr_next != " ":
                            pass
                        else:
                            if chr_next == " ":
                                return surround(self, txt, in_chr, in_chr)
                else:
                    if chr_next and chr_next != " ":
                        if txt_sel or chr_next in BRACKETS_R:
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
        kc = bpy.context.window_manager.keyconfigs
        km = kc.default.keymaps.get('Text')

        if not km:
            return 0.1

        # disable default textinput insert kmi
        kmidef = km.keymap_items.get('text.insert')
        kmidef.active = False
        new = km.keymap_items.new

        kmi = new("TEXT_OT_insert2", 'TEXTINPUT', 'ANY', head=True)
        # cls._keymaps.append((km, kmi, kmidef))

        # disable default backspace delete kmi
        kmidef = get_default_kmi(km, "text.delete", "BACK_SPACE", "PRESS")
        assert kmidef is not None and kmidef.type == "BACK_SPACE"
        kmidef.active = False
        kmi = new("TEXT_OT_insert2_internal", 'BACK_SPACE', 'PRESS')
        kmi.properties.delete = 1
        cls._keymaps = [(km, kmi, kmidef)]

    @classmethod
    def _remove(cls):
        for km, kmi, kmidef in cls._keymaps:
            km.keymap_items.remove(kmi)
            if hasattr(kmidef, "active"):
                kmidef.active = True
        cls._keymaps.clear()


# find a kmi from blender's default keymap
def get_default_kmi(km, kmi_idname, kmi_type, kmi_value):
    for kmi in (k for k in km.keymap_items if k.idname == kmi_idname):
        if kmi_type == kmi.type and kmi_value == kmi.value:
            return kmi


# Insert 2 is called by text input and executes a chain of operators
class TEXT_OT_insert2(bpy.types.Macro):
    bl_idname = 'text.insert2'
    bl_label = "Insert 2"
    bl_options = {'UNDO', 'MACRO', 'INTERNAL'}

    @classmethod
    def _setup(cls):

        # 1. TEXT_OT_insert2_internal is called with store=True and serves
        # to store any text selection, so that it can be retrieved later
        #
        # 2. TEXT_OT_insert is called for the actual input
        #
        # 3. TEXT_OT_insert2_internal is called again and handles
        # the behavioral logic like surround brackets, swallow etc.

        cls.define("TEXT_OT_insert2_internal").properties.store = 1
        # TODO replace with event.unicode XXX needs a lot of behavior rewrite
        cls.define("TEXT_OT_insert")
        cls.define("TEXT_OT_insert2_internal")


def classes():
    return [
        TEXT_OT_insert2,
        TEXT_OT_insert2_internal
    ]


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


def disable_kmi(cls, km_type='3D View', idname=None, type=None, value=None,
                alt=False, shift=False, ctrl=False, retries=3):
    if retries <= 0:
        raise ValueError("No matches or keymap wasn't ready")
    if not any((idname, type, value)):
        raise ValueError("Nothing to search for")

    kc = bpy.context.window_manager.keyconfigs.active
    km = kc.keymaps.get(km_type)
    if not km:
        raise KeyError("Keymap doesn't exist in active keyconfig")
    no_idname, no_type, no_value = not idname, not type, not value
    for kmi in km.keymap_items:
        if ((kmi.type == type or no_type) and
            (kmi.value == value or no_value) and
            (kmi.idname == idname or no_idname) and
           kmi.alt == alt and kmi.shift == shift and kmi.ctrl == ctrl):
            kmi.active = False
            if not hasattr(cls, "_disabled"):
                cls._disabled = []
            return cls._disabled.append(kmi)

    from bpy.app.timers import register
    args = km_type, idname, type, value, alt, shift, ctrl, retries - 1
    register(lambda: disable_kmi(*args), first_interval=0.2)
