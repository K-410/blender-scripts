import code
import bpy

bl_info = {
    "name": "*Run In Console",
    "description": "Execute a text block and catch its output (prints and "
    "errors) in Blender's interactive console.",
    "author": "kaio",
    "version": (1, 0, 5),
    "blender": (2, 80, 0),
    "location": "Text Editor",
    "category": "Development"
}
_call = None
_console = None
_preferences = None
C_dict = dict()


def get_console_spaces(context):
    spaces = [(a, a.spaces.active, a.regions[-1])
              for w in context.window_manager.windows
              for a in w.screen.areas if a.type == 'CONSOLE']

    if not spaces:
        return None

    elif len(spaces) == 1:
        return spaces.pop()

    return get_redirect(context, spaces)


def get_bl_console():
    from console_python import get_console
    region = C_dict.get('region')
    if region:
        return get_console(hash(region))[0]


def get_redirect(context, spaces):
    """Find the right console."""
    consoles = list_consoles(context)
    index = verify_index(context, consoles)
    for area, space, region in spaces:
        if area == consoles[index]:
            return area, space, region
    return None


def gen_C_dict(context, spaces):
    C_dict.update(**context.copy())
    for k, v in zip(('area', 'space_data', 'region'), spaces):
        C_dict[k] = v


def scrollback_append(result, C_dict=C_dict, type='INFO'):
    """Append text to the console."""

    if result:
        error_str = None
        for l in result.split("\n"):

            text = l.replace("\t", "    ")
            prop = {'text': text, 'type': type}
            args = 'CONSOLE_OT_scrollback_append', C_dict, prop

            try:
                _call(*args)
                # return

            except RuntimeError as error:
                error_str, = error.args
                print(error_str)
                # break


def printc(*values: object, sep=' ', end='', use_repr=False):
    if not values:
        scrollback_append("\n", type='OUTPUT')
        return
    fn = repr if use_repr else str
    scrollback_append(sep.join(fn(v) for v in values) + end, type='OUTPUT')


class TEXT_AP_run_in_console_prefs(bpy.types.AddonPreferences):
    bl_idname = __name__

    from bpy.props import BoolProperty

    persistent: BoolProperty(
        default=False, name="Persistent", description="Access script bindings "
        "in console after execution")

    clear_bindings: BoolProperty(
        default=False, name="Clear Bindings", description="Clear console "
        "bindings before running text block")

    keep_math: BoolProperty(
        default=True, name="Keep Math", description="Restore 'math' module"
        "after clearing")

    keep_mathutils: BoolProperty(
        default=True, name="Keep Mathutils", description="Restore 'mathutils' "
        "module after clearing")

    show_name: BoolProperty(
        default=True, name="Show Name", description="Display text name in the "
        "console before execution")

    # replace_print: _bool(
    #     default=True, name="Catch Print", description="Allow prints from "
    #     "operators to be sent to the console", update=update_print)

    show_elapsed: BoolProperty(
        default=True, name="Show Elapsed", description="Display elapsed time "
        "after execution")

    del BoolProperty

    def draw(self, context):
        return TEXT_PT_run_in_console_settings.draw(self, context)


class Console(object):
    slots = ('__dict__',)

    namespace = {'__name__': '__main__'}
    __name__ = '__main__'

    def __init__(self):
        import traceback
        import contextlib
        import time
        self.modules = traceback.sys.modules

        self.template_dict = {
            '__name__': '__main__',
            '__builtins__': self.modules['builtins'],
            'print': printc
        }
        self.module = type('__main__', (), self.template_dict)()
        self.namespace = self.module.__dict__
        self.backup = self.modules['__main__']
        self.traceback = ""

        self.exc_info = traceback.sys.exc_info
        self.print = self.modules['builtins'].print
        self.perf_counter = time.perf_counter
        self.format_exception = traceback.format_exception
        self.redirect_stderr = contextlib.redirect_stderr
        self.template_dict = {
            '__name__': '__main__',
            '__builtins__': self.modules['builtins'],
            'print': printc
        }
        self.reset()

    def get_error_line(self, traceback):
        lines = traceback.splitlines(keepends=True)[2::]
        e = [i for i in [l[l.rfind("\", line ")::]
             [8::].strip() for l in lines if l] if i][-1]
        return int(e)

    def set_namespace(self, clear=True):
        self.namespace.clear()
        self.namespace.update(self.template_dict)

    def reset(self):
        self.__name__ = '__main__'
        self.traceback = ""

    def write_traceback(self):
        trace = self.format_exception(*self.exc_info())
        self.traceback = "".join(trace[:1] + trace[2:])

    def push(self, source):
        self.runsource(source)

    def runsource(self, source, file="<input>"):
        self.set_namespace()
        namespace = self.namespace
        perf_counter = self.perf_counter
        self.modules['__main__'] = self.module
        perf_time = None

        try:
            code = compile(source, file, 'exec')

            perf_start = perf_counter()
            exec(code, namespace)
            perf_time = perf_counter() - perf_start

        except (KeyboardInterrupt, Exception):
            self.write_traceback()

        finally:
            self.perf_time = perf_time
            self.modules['__main__'] = self.backup

        # store namespace in interactive console
        if _preferences.persistent:
            console = get_bl_console()
            console.locals.update(self.module.__dict__)

    def show_output(self):
        traceback = self.traceback
        if traceback:
            scrollback_append(traceback, type='ERROR')

        if _preferences.show_elapsed:
            perf_time = self.perf_time

            if perf_time:

                num_fmt = ((1e3, 0), (1e2, 1), (1e1, 2))
                val = perf_time * 1000
                precision = 3

                for num, prec in num_fmt:
                    if val >= num:
                        precision = prec

                perf_fmt = f"{val:.{precision}f} ms"
                scrollback_append(perf_fmt, type='INFO')
        self.traceback = ""

    def runtextblock(self, text):
        self.perf_start = self.perf_counter()
        source = "\n".join(l.body for l in text.lines)

        if _preferences.show_name:
            scrollback_append(f"\n{text.name}:", type='INFO')

        if _preferences.persistent and _preferences.clear_bindings:
            console = get_bl_console()
            console.locals.clear()

            if _preferences.keep_math:
                for k, v in self.modules['math'].__dict__.items():
                    if not k.startswith("__"):
                        console.locals[k] = v

            if _preferences.keep_mathutils:
                for k, v in self.modules['mathutils'].__dict__.items():
                    if not k.startswith("__"):
                        console.locals[k] = v

        self.runsource(source, text.name)
        self.show_output()


class TEXT_OT_run_in_console(bpy.types.Operator):
    bl_idname = "text.run_in_console"
    bl_label = "Run In Console"
    bl_description = ("Run current text block in the console.\n\n"
                      "Needs at least 1 console area open")

    @classmethod
    def _setup(cls):
        cls._keymaps = []
        kc = bpy.context.window_manager.keyconfigs.addon.keymaps
        get, new = kc.get, kc.new
        km = get("Text", new(name='Text', space_type='TEXT_EDITOR'))
        kmi = km.keymap_items.new(cls.bl_idname, 'R', 'PRESS', ctrl=True)
        cls._keymaps.append((km, kmi))

        bpy.types.TEXT_HT_header.append(cls.draw)
        bpy.types.CONSOLE_HT_header.append(cls.draw_redirect)
        bpy.types.TEXT_MT_toolbox.append(cls.draw)

    @classmethod
    def _remove(cls):
        for km, kmi in cls._keymaps:
            km.keymap_items.remove(kmi)
        cls._keymaps.clear()

        bpy.types.TEXT_HT_header.remove(cls.draw)
        bpy.types.CONSOLE_HT_header.remove(cls.draw_redirect)
        bpy.types.TEXT_MT_toolbox.remove(cls.draw)

    @classmethod
    def any_console(self, context):
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'CONSOLE':
                    return True
        return False

    @classmethod
    def poll(self, context):
        return (context.area.type == 'TEXT_EDITOR' and
                context.space_data.text is not None and
                self.any_console(context))

    def draw_redirect(self, context):
        num, index, redirect = get_console_index(context)
        if index != -1 and num - 1:
            enable = context.screen['console_redirect'] == index
            self.layout.operator("console.redirect", depress=enable)
            self.layout.enabled = not enable

    def draw_rcm(self, context):
        row = self.layout.row()
        row.operator(
            "text.run_in_console", text="Run In Console", icon='CONSOLE')
        if not TEXT_OT_run_in_console.any_console(context):
            row.enabled = False

    def draw(self, context):
        row = self.layout.row()
        text = "" if "toolbox" not in self.bl_idname else "Run In Console"
        row.operator("text.run_in_console", text=text, icon='CONSOLE')
        if not TEXT_OT_run_in_console.any_console(context):
            row.enabled = False

    def execute(self, context):
        spaces = get_console_spaces(context)
        if spaces:
            gen_C_dict(context, spaces)
            _console.runtextblock(context.space_data.text)
            return {'FINISHED'}
        return {'CANCELLED'}

    def invoke(self, context, event):
        if event.shift:
            props = {'name': "TEXT_PT_run_in_console_settings"}
            _call("WM_OT_call_panel", {}, props)
            return {'CANCELLED'}
        return self.execute(context)


class TEXT_PT_run_in_console_settings(bpy.types.Panel):
    bl_label = ""
    bl_space_type = "TEXT_EDITOR"
    bl_region_type = 'WINDOW'

    def draw(self, context):
        prefs = _preferences
        layout = self.layout
        layout.label(text="Run In Console Settings")
        layout.prop(prefs, "persistent")
        row = layout.row(align=True)
        row.alignment = 'CENTER'
        col = row.column()
        col.prop(prefs, 'clear_bindings')
        subcol = col.column()
        subcol.prop(prefs, 'keep_math')
        subcol.prop(prefs, 'keep_mathutils')
        if not prefs.clear_bindings:
            subcol.enabled = False
        col.prop(prefs, 'show_name')
        col.prop(prefs, 'show_elapsed')
        # col.prop(prefs, 'replace_print')
        # col.prop(self, 'real_time_hack')


class CONSOLE_OT_redirect(bpy.types.Operator):
    bl_description = 'Redirect script output to this console'
    bl_idname = 'console.redirect'
    bl_label = 'Redirect'

    @classmethod
    def poll(self, context):
        return context.area.type == 'CONSOLE'

    def execute(self, context):
        consoles = list_consoles(context)
        context.screen['console_redirect'] = consoles.index(context.area)
        for console in consoles:
            console.tag_redraw()
        return {'FINISHED'}


def list_consoles(context):
    wins = context.window_manager.windows
    return [a for w in wins for a in
            w.screen.areas if a.type == 'CONSOLE']


def verify_index(context, consoles):
    """Ensure console index is valid"""
    if not getattr(context, 'screen'):  # don't verify during redraw
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
    mod = globals().values()
    return [i for i in mod if hasattr(i, 'mro')
            and bpy.types.bpy_struct in i.mro()
            and i.__module__ == __name__]


def _setglobals(**kwargs):
    for k, v in kwargs.items():
        globals()[k] = v


def register():
    import _bpy

    for cls in classes():
        bpy.utils.register_class(cls)
        if hasattr(cls, '_setup'):
            cls._setup()

    addons = bpy.context.preferences.addons
    _setglobals(_preferences=addons[__name__].preferences)
    _setglobals(_console=Console())
    _setglobals(_call=_bpy.ops.call)


def unregister():
    for cls in reversed(classes()):
        if hasattr(cls, '_remove'):
            cls._remove()
        bpy.utils.unregister_class(cls)

    del globals()['_preferences']
    del globals()['_console']
    del globals()['_call']


del code
