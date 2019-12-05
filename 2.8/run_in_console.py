import bpy
from bpy_restrict_state import _RestrictContext

bl_info = {
    "name": "*Run In Console",
    "description": "Execute a text block and catch its output (prints and "
    "errors) in Blender's interactive console.",
    "author": "kaio",
    "version": (1, 0, 0),
    "blender": (2, 80, 0),
    "location": "Text Editor",
    "category": "Development"
}

_console = None
_preferences = None


def get_builtins():
    import sys
    return sys.modules['builtins']


class Context(dict):
    def __init__(self):
        super(__class__, self).__init__()
        self.__dict__ = self


c_dict = Context()


def get_bl_console():
    from console_python import get_console
    region_hash = hash(c_dict['region'])
    con, out, err = get_console(region_hash)
    return con


def get_console_spaces(context):
    """
    Three things can happen:
    1. A console is found, its area, region and space_data are returned.
    2. Multiple consoles are found, one is picked out based on
        either its list index or redirect tag.
    3. No consoles are found and the operator cancels.
    """

    spaces = [(a, a.spaces.active, a.regions[-1])
              for a in list_consoles(context)]

    if not spaces:
        return

    elif len(spaces) == 1:
        return spaces.pop()

    consoles = list_consoles(context)
    index = verify_index(context, consoles)
    for area, space, region in spaces:
        if area == consoles[index]:
            return area, space, region
    return


def set_spaces(spaces):
    for k, v in zip(('area', 'space_data', 'region'), spaces):
        c_dict[k] = v


def delayed_scrollback(items, c_dict=c_dict, type='INFO'):
    items = "".join(items)
    assert 1 is 2
    bpy.app.timers.register(
        lambda: scrollback_append(
            items, c_dict=c_dict, type=type),
        first_interval=0.5)


def scrollback_append(items, c_dict=c_dict, type='INFO'):
    """Append text to the console using bpy.ops.scrollback_append"""
    spaces = get_console_spaces(c_dict)
    if not spaces:  # default to builtin print if no console area exists
        return _print(*items)

    set_spaces(spaces)
    scrollback = bpy.ops.console.scrollback_append

    if isinstance(items, str):
        if items[-1].endswith("\n"):
            items = items[:-1]
    elif isinstance(items, list):
        items = "\n".join(items)

    text = ""
    items = [*reversed([l.replace("\t", "    ") for l in items.split("\n")])]

    while items:
        if isinstance(bpy.context, _RestrictContext):
            break
        try:
            text = items.pop()
            scrollback(c_dict, text=text, type=type)
            ok = True
        except RuntimeError:
            ok = False
            break

    if not ok:
        if text:
            items.insert(0, text)
        return delayed_scrollback("\n".join(items), c_dict, type)


def printc(*args, **kwargs):
    sep = kwargs.get('sep', " ")
    end = kwargs.get('end', "\n")
    spaces = get_console_spaces(c_dict)
    if not spaces:  # default to builtin print if no console area exists
        return _print(*args, **kwargs)
    if not args:
        scrollback_append("\n", type='OUTPUT')
        return
    scrollback_append(sep.join(str(v) for v in args) + end, type='OUTPUT')


def update_assume_print(self, context):
    if self.assume_print:
        __builtins__['print'] = printc
    else:
        __builtins__['print'] = __builtins__['_print']


class TEXT_AP_run_in_console_prefs(bpy.types.AddonPreferences):
    bl_idname = __name__

    from bpy.props import BoolProperty

    assume_print: bpy.props.BoolProperty(
        name="Assume Print (WARNING: Unstable)",
        description="Hijack prints from other scripts and display them in "
        "Blender's\nconsole. Experimental and may crash. Use at own risk",
        default=False,
        update=update_assume_print
    )

    persistent: BoolProperty(name="Persistent", description=""
                             "Access bindings in console after execution")

    clear_bindings: BoolProperty(name="Clear Bindings", description="Clear "
                                 "console bindings before running text block")

    keep_math: BoolProperty(default=True, name="Keep Math", description=""
                            "Restore math on clear")

    keep_mathutils: BoolProperty(description="Restore mathutils on clear",
                                 default=True, name="Keep Mathutils")

    keep_vars: BoolProperty(description="Restore convenience variables",
                            default=True, name="Keep C, D variables")

    show_name: BoolProperty(default=True, name="Show Name",
                            description="Display text name in console")

    show_time: BoolProperty(description="Display elapsed time after execution",
                            default=True, name="Show Elapsed", )

    del BoolProperty

    def draw(self, context):
        return TEXT_PT_run_in_console_settings.draw(self, context)


class Console:
    """
    Interpreter object kept alive while the as long as the addon
    is registered. Helps helps with measuring execution times.
    """
    __slots__ = ('__dict__',)

    def __init__(self):
        import traceback
        import contextlib
        import time
        self.modules = traceback.sys.modules

        self.template_dict = {'__name__': '__main__',
                              '__builtins__': self.modules['builtins'],
                              'print': printc}

        self.module = type('__main__', (), self.template_dict)()
        self.backup = self.modules['__main__']
        self.traceback = ""
        self.perf_time = 0

        self.exc_info = traceback.sys.exc_info
        self.print = self.modules['builtins'].print
        self.perf_counter = time.perf_counter
        self.format_exception = traceback.format_exception
        self.redirect_stderr = contextlib.redirect_stderr

    def runsource(self, source, file="<input>"):
        namespace = self.module.__dict__
        namespace.clear()
        namespace.update(self.template_dict, __file__=file)

        self.modules['__main__'] = self.module
        perf_counter = self.perf_counter

        try:
            code = compile(source, file, 'exec')

            # measure only the actual execution
            perf_start = perf_counter()
            exec(code, namespace)
            self.perf_time = perf_counter() - perf_start

        except (KeyboardInterrupt, Exception):

            trace = self.format_exception(*self.exc_info())
            self.traceback = "".join(trace[:1] + trace[2:])

        finally:
            self.modules['__main__'] = self.backup

        # store module members in blender's console
        if _preferences.persistent:

            console = get_bl_console()
            console.locals.update(self.module.__dict__)

    def runtextblock(self, text):
        source = "\n".join(l.body for l in text.lines)

        prefs = _preferences

        if prefs.show_name:

            scrollback_append(f"\n{text.name}:", type='INFO')

        if prefs.persistent and prefs.clear_bindings:

            con_locals = get_bl_console().locals
            con_locals.clear()

            if prefs.keep_math:

                mod = self.modules['math']
                for k, v in mod.__dict__.items():
                    if not k.startswith("__"):
                        con_locals[k] = v

            if prefs.keep_mathutils:

                mod = self.modules['mathutils']
                for k, v in mod.__dict__.items():
                    if not k.startswith("__"):
                        con_locals[k] = v

            if prefs.keep_vars:
                con_locals['C'] = bpy.context
                con_locals['D'] = bpy.data

        self.runsource(source, file=bpy.data.filepath + "\\" + text.name)

        if self.traceback:
            scrollback_append(self.traceback, type='ERROR')

        if prefs.show_time and getattr(self, "perf_time", 0):
            # format the numbers so they look nicer
            time_ms = self.perf_time * 1000
            precision = 3
            for num, prec in ((1e3, 0), (1e2, 1), (1e1, 2)):
                if time_ms >= num:
                    precision = prec

            perf_fmt = f"{time_ms:.{precision}f} ms"
            scrollback_append(perf_fmt, type='INFO')
            self.perf_time = 0
        self.traceback = ""


class TEXT_OT_run_in_console(bpy.types.Operator):
    bl_idname = "text.run_in_console"
    bl_label = "Run In Console"
    bl_description = ("Run current text block in the console.\n\n"
                      "Needs at least one console area open")

    @classmethod
    def _setup(cls):
        cls._keymaps = []
        kc = bpy.context.window_manager.keyconfigs.addon.keymaps
        get, new = kc.get, kc.new
        km = get("Text", new(name='Text', space_type='TEXT_EDITOR'))
        kmi = km.keymap_items.new(cls.bl_idname, 'R', 'PRESS', ctrl=True)
        cls._keymaps.append((km, kmi))

        bpy.types.TEXT_HT_header.append(cls.draw_button)
        bpy.types.CONSOLE_HT_header.append(cls.draw_redirect)
        bpy.types.TEXT_MT_context_menu.append(cls.draw_button)


    @classmethod
    def _remove(cls):
        for km, kmi in cls._keymaps:
            km.keymap_items.remove(kmi)

        cls._keymaps.clear()

        bpy.types.TEXT_HT_header.remove(cls.draw_button)
        bpy.types.CONSOLE_HT_header.remove(cls.draw_redirect)
        bpy.types.TEXT_MT_context_menu.remove(cls.draw_button)

    @classmethod
    def any_console(cls, context):
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'CONSOLE':
                    return True
        return False

    @classmethod
    def poll(cls, context):
        return getattr(context.space_data, "text", 0)

    def draw_redirect(self, context):
        num, index, redirect = get_console_index(context)

        if index != -1 and num - 1:
            row = self.layout.row()
            enable = context.screen['console_redirect'] == index
            row.operator("console.redirect", depress=enable)
            row.enabled = not enable

    def draw_button(self, context):
        row = self.layout.row()
        text = "" if "context_menu" not in self.bl_idname else "Run In Console"
        row.operator("text.run_in_console", text=text, icon='CONSOLE')

        if not TEXT_OT_run_in_console.any_console(context):
            row.enabled = False

    def execute(self, context):
        spaces = get_console_spaces(context)

        if spaces:
            # keep a context dictionary on module level so we don't
            # have topass it everywhere or generate new each time
            c_dict.update(**context.copy())
            set_spaces(spaces)
            _console.runtextblock(context.space_data.text)
            return {'FINISHED'}
        return {'CANCELLED'}

    def invoke(self, context, event):
        if event.shift:
            return bpy.ops.wm.call_panel(
                name="TEXT_PT_run_in_console_settings")
        return self.execute(context)


class TEXT_PT_run_in_console_settings(bpy.types.Panel):
    bl_label = ""
    bl_space_type = "TEXT_EDITOR"
    bl_region_type = 'WINDOW'

    def draw(self, context):
        layout = self.layout
        layout.ui_units_x = 12
        prefs = _preferences

        col = layout.column()
        col.prop(prefs, "assume_print")

        col.label(text="Run In Console Settings")
        col.prop(prefs, "persistent")

        col.prop(prefs, 'clear_bindings')

        if prefs.clear_bindings:

            split = col.split(factor=0.025)
            split.separator()
            subcol = split.column()
            subcol.prop(prefs, 'keep_math')
            subcol.prop(prefs, 'keep_mathutils')
            subcol.prop(prefs, 'keep_vars')

        col.prop(prefs, 'show_name')
        col.prop(prefs, 'show_time')

        # only display if accessed from the text editor
        if context.area.type == 'TEXT_EDITOR':
            col.operator("text.run_in_console", text="Run In Console")


class CONSOLE_OT_redirect(bpy.types.Operator):
    bl_description = 'Redirect script output to this console'
    bl_idname = 'console.redirect'
    bl_label = 'Redirect'

    @classmethod
    def poll(cls, context):
        return context.area.type == 'CONSOLE'

    def execute(self, context):
        consoles = list_consoles(context)
        context.screen['console_redirect'] = consoles.index(context.area)

        for console in consoles:
            console.tag_redraw()

        return {'FINISHED'}


def list_consoles(context):
    return [a for w in bpy.context.window_manager.windows
            for a in w.screen.areas if a.type == 'CONSOLE']


def verify_index(context, consoles):
    """Ensure console index is valid"""
    if not getattr(context, 'screen', False):  # don't verify during redraw
        context = bpy.context
        c_dict.update(**context.copy())
        if not getattr(context, 'screen', False):
            return -1

    index = context.screen.get('console_redirect', None)
    max_index = len(consoles) - 1

    if index is None or index > max_index:

        index = min([(a.x, consoles.index(a)) for a in consoles])[1]
        context.screen['console_redirect'] = index

    return index


def get_console_index(context):
    consoles = list_consoles(context)
    curr_index = verify_index(context, consoles)

    try:
        ret = len(consoles), consoles.index(context.area), curr_index

    except ValueError:
        ret = 0, -1, curr_index

    return ret


def classes():
    from bpy.types import bpy_struct
    mod = globals().values()

    return [i for i in mod if hasattr(i, 'mro') and
            bpy_struct in i.mro() and
            i.__module__ == __name__]


def _module():
    from sys import modules
    return modules[__name__]


def delkey(path, key):
    del path[key]


def get_builtin_print():
    global _print
    _print = get_builtins().print


def backup_print():
    __builtins__['_print'] = __builtins__['print']


def register():
    for cls in classes():
        bpy.utils.register_class(cls)
        if hasattr(cls, '_setup'):
            cls._setup()

    from bpy import context
    addons = context.preferences.addons
    prefs = addons[__name__].preferences

    module = _module()
    module._preferences = prefs
    module._console = Console()
    c_dict.update(window_manager=context.window_manager)

    update_assume_print(prefs, context)


def unregister():
    # restore print
    import sys
    sys.modules['builtins'].print = _print
    # set_builtin_print(False)

    for cls in reversed(classes()):
        if hasattr(cls, '_remove'):
            cls._remove()

        bpy.utils.unregister_class(cls)

    # clean up module refs
    module = _module()
    module._preferences = None
    module._console = None

    # clean up custom properties
    for w in bpy.context.window_manager.windows:
        w.screen.pop('console_redirect', None)


# Ensure there always is a backup version of __builtins__.print
backup_print()
