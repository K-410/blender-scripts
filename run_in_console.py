import code
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from time import perf_counter
from types import ModuleType

import bpy

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

context_dict = dict()
_dummy_out = StringIO()
redraw_timer = bpy.ops.wm.redraw_timer
prefs = []


def get_console_spaces(context):
    wm, spaces = context.window_manager, []
    areas = [a for w in wm.windows for a in w.screen.areas]
    for area in areas:
        if area.type == 'CONSOLE':
            for region in area.regions:
                if region.type == 'WINDOW':
                    spaces.append((area, area.spaces.active, region))
                    break

    if not spaces:
        return None
    elif len(spaces) == 1:
        return spaces.pop()
    return get_redirect(context, spaces)


def get_redirect(context, spaces):
    """Find the right console."""
    consoles = list_consoles(context)
    index = verify_index(context, consoles)
    for area, space, region in spaces:
        if area == consoles[index]:
            return area, space, region
    return None


def gen_C_dict(context, area, space, region):
    """
    Update the execution context dict (stored on
    module level) with spaces based on a given console.

    args: context, conspace (tuple of area, space_data, region)
    ret: context dict
    """
    context_dict.update(context.copy())
    context_dict.update(area=area, space_data=space, region=region)
    return context_dict


def scrollback_append(result, type='INFO'):
    """Append text to the console."""

    if result:
        scrollback = bpy.ops.console.scrollback_append
        for l in result.split("\n"):
            text = l.replace("\t", "    ")
            try:
                scrollback(context_dict, text=text, type=type)

            except RuntimeError:
                # handle exceptions when blender is redrawing
                args, kwargs = context_dict, {'text': text, 'type': type}
                bpy.app.timers.register(
                    lambda: scrollback(args, **kwargs), first_interval=0.1)


def runsource(source):
    """
    Execute python source in a separate interpreter, kinda like what
    'Run Script' in the text editor does. This function only redirects
    errors.
    """

    modules = code.sys.modules
    main_org = modules.get("__main__")
    main = ModuleType("__main__")
    namespace = main.__dict__
    # namespace["__builtins__"] = modules["builtins"]
    namespace.update(__builtins__=modules.get("builtins"))
    console = code.InteractiveInterpreter(locals=namespace)
    stderr = StringIO()

    with redirect_stderr(stderr):
        try:
            modules["__main__"] = main
            console.runsource(source)
        except Exception:
            stderr.write(code.traceback.format_exc())
        finally:
            modules["__main__"] = main_org

    return stderr.getvalue().strip()


def printc(*value: object, sep=' ', end=''):
    """
    Monkey patching so we can hijack operator prints and output to an
    interactive console. Supports most args.

    Since Blender locks UI updates during script execution, a workaround to
    force updates is provided (bpy.ops.wm.redraw_timer).

    External usage: 'from run_in_console import printc as print'
    """
    st = ''.join([str(v) + sep for v in value] + [end])
    scrollback_append(st, type='OUTPUT')

    if prefs.real_time_hack:
        context_dict.get('area').tag_redraw()
        with redirect_stdout(_dummy_out):
            redraw_timer(type='DRAW_SWAP', iterations=0, time_limit=0)


class TEXT_AP_run_in_console_prefs(bpy.types.AddonPreferences):
    bl_idname = 'run_in_console'

    source_text: bpy.props.BoolProperty(
        default=True, name="Display Source", description="Enable to display "
        "source text block in console")

    replace_print: bpy.props.BoolProperty(
        default=True, name="Replace Print Function", description="Enable to "
        "hijack print function from operators registered from the text editor")

    real_time_hack: bpy.props.BoolProperty(
        default=True, name="Real Time Workaround", description="Force Blender "
        "to print messages in the middle of script execution. Note this is "
        "considered a hack")

    perf_counter: bpy.props.BoolProperty(
        default=False, name="Enable Perf Counter", description="Enable to "
        "display script execution speed at the end")

    def draw(self, context):
        layout = self.layout

        row = layout.row(align=True)
        row.alignment = 'CENTER'
        col = row.column()
        col.prop(self, 'source_text')
        col.prop(self, 'replace_print')
        col.prop(self, 'real_time_hack')
        col.prop(self, 'perf_counter')


class CONSOLE_MT_redirect(bpy.types.Menu):
    bl_idname = 'CONSOLE_MT_redirect'
    bl_label = ""

    def draw(self, context):
        layout = self.layout
        num, index, redirect = get_console_index(context)
        if index != -1 and num - 1:
            row = layout.row()
            if context.screen['console_redirect'] == index:
                row.operator("console.redirect", depress=True)
                row.enabled = False
            else:
                row.operator("console.redirect")


class TEXT_OT_run_in_console(bpy.types.Operator):
    bl_idname = "text.run_in_console"
    bl_label = "Run In Console"

    _keymaps = []

    @staticmethod
    def _setup():
        cls = __class__
        keymaps = cls._keymaps
        kc = bpy.context.window_manager.keyconfigs
        km = kc.addon.keymaps.new(name='Text', space_type='TEXT_EDITOR')
        kmi = km.keymap_items.new(cls.bl_idname, 'R', 'PRESS', ctrl=True)
        keymaps.append((km, kmi))

        bpy.types.TEXT_HT_header.append(TEXT_OT_run_in_console.draw)
        bpy.types.CONSOLE_HT_header.append(CONSOLE_MT_redirect.draw)

        preferences = bpy.context.preferences.addons[__name__].preferences
        setattr(code.sys.modules[__name__], 'prefs', preferences)

    @staticmethod
    def _remove():
        keymaps = __class__._keymaps
        for km, kmi in keymaps:
            km.keymap_items.remove(kmi)
        keymaps.clear()

        bpy.types.TEXT_HT_header.remove(TEXT_OT_run_in_console.draw)
        bpy.types.CONSOLE_HT_header.remove(CONSOLE_MT_redirect.draw)

    def any_console(self, context):
        for area in context.screen.areas:
            if area.type == 'CONSOLE':
                return True
        return False

    @classmethod
    def poll(self, context):
        return (context.area.type == 'TEXT_EDITOR' and
                context.space_data.text is not None and
                self.any_console(self, context))

    def draw(self, context):
        if getattr(context.space_data, 'text', None) is not None:
            row = self.layout.row(align=True)
            row.operator("text.run_in_console")

    def execute(self, context):
        t_start = perf_counter()
        spaces = get_console_spaces(context)

        if spaces:
            gen_C_dict(context, *spaces)
            text = context.space_data.text
            file = repr(text.name)
            source = text.as_string()

            if prefs.replace_print:
                rep = 'from run_in_console import printc as print\n'
                source = rep + source

            source = f"exec(compile({repr(source)}, {file}, 'exec'))"

            if prefs.source_text:
                scrollback_append("\n")
                scrollback_append(f"{repr(text)}:")

            traceback = runsource(source)

            if traceback:
                scrollback_append(traceback, type='ERROR')

            _dummy_out.truncate(0)

            if prefs.perf_counter:
                t = round(perf_counter() - t_start, 3)
                st = f"Finished in {repr(t)} seconds"
                scrollback_append(st, type='INFO')

        return {'FINISHED'}


class CONSOLE_OT_redirect(bpy.types.Operator):
    bl_description = 'Redirect script output to this console'
    bl_idname = 'console.redirect'
    bl_label = 'Redirect'

    @classmethod
    def poll(self, context):
        return context.area.type == 'CONSOLE'

    def execute(self, context):
        consoles = list_consoles(context)
        index = consoles.index(context.area)
        context.screen['console_redirect'] = index
        for console in consoles:
            console.tag_redraw()
        return {'FINISHED'}


def list_consoles(context):
    consoles = []
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'CONSOLE':
                consoles.append(area)
    return consoles


def verify_index(context, consoles):
    """Ensure console index is valid"""
    index = context.screen.get('console_redirect')
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
    from inspect import isclass
    return [i for i in globals().values() if isclass(i) and
            i.__module__ == __name__]


def register():
    for cls in classes():
        bpy.utils.register_class(cls)
        if hasattr(cls, '_setup'):
            cls._setup()


def unregister():
    for cls in reversed(classes()):
        if hasattr(cls, '_remove'):
            cls._remove()
        bpy.utils.unregister_class(cls)
