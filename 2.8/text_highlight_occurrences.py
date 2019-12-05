import bpy
from gpu.shader import from_builtin
from mathutils import Vector
from gpu_extras.batch import batch_for_shader
from itertools import chain
from collections import deque
# from time import perf_counter
from bgl import glLineWidth, glEnable, glDisable, GL_BLEND
import blf

bl_info = {
    "name": "Highlight Occurrences",
    "description": "Enables highlighting for words matching selected text",
    "author": "kaio",
    "version": (1, 0, 0),
    "blender": (2, 82, 0),
    "location": "Text Editor",
    "category": "Text Editor"
}

shader = from_builtin('2D_UNIFORM_COLOR')
shader_uniform_float = shader.uniform_float
shader_bind = shader.bind
iterchain = chain.from_iterable
wrap_chars = {' ', '-'}
p = None


def get_matches_curl(substr, strlen, find, selr):
    match_indices = []
    idx = find(substr, 0)
    exclude = range(*selr)
    append = match_indices.append

    while idx is not -1:
        span = idx + strlen

        if idx in exclude or span in exclude:
            idx = find(substr, idx + 1)
            continue

        append(idx)
        idx = find(substr, span)

    return match_indices


def get_matches(substr, strlen, find):
    match_indices = []
    append = match_indices.append
    chr_idx = find(substr, 0)

    while chr_idx is not -1:
        append(chr_idx)
        chr_idx = find(substr, chr_idx + strlen)

    return match_indices


def get_colors(draw_type):
    colors = {
        'SCROLL': (p.col_scroll,),
        'SOLID': (p.col_bg,),
        'LINE': (p.col_line,),
        'FRAME': (p.col_line,),
        'SOLID_FRAME': (p.col_bg,
                        p.col_line)}
    return colors[draw_type]


def draw_batches(context, batches, colors):
    glLineWidth(p.line_thickness)
    shader_bind()
    glEnable(GL_BLEND)

    for draw, col in zip(batches, colors):
        shader_uniform_float("color", [*col])
        draw(shader)

    glDisable(GL_BLEND)


def update_colors(self, context):
    col_attrs = ("col_bg", "fg_col", "col_line", 'col_scroll')
    if self.col_preset != 'CUSTOM':
        for source, target in zip(self.colors[self.col_preset], col_attrs):
            setattr(self, target, source)


def to_tris(lineh, pts, y_ofs):
    y1, y2 = Vector((-1, y_ofs)), Vector((0, lineh))
    return (*iterchain(
        [(a, b, by, a, by, ay) for a, b, by, ay in
            [(a + y1, b + y1, b + y1 + y2, a + y1 + y2) for a, b, _ in pts]]),)


def to_scroll(lineh, pts, y_ofs):
    y1, y2 = Vector((-1, y_ofs)), Vector((0, y_ofs))
    return (*iterchain(
        [(a, b, by, a, by, ay) for a, b, by, ay in
            [(a + y1, b + y1, b + y1 + y2, a + y1 + y2) for a, b in pts]]),)


def to_lines(lineh, pts, y_ofs):
    y = Vector((-1, y_ofs + 2))
    return (*iterchain([(i + y, j + y) for i, j, _ in pts]),)


def to_frames(lineh, pts, y_ofs):
    y1, y2 = Vector((-1, y_ofs)), Vector((-1, lineh + y_ofs))
    return (*iterchain(
        [(a, b, ay, by + Vector((1, 0)), ay, a, by, b) for a, b, ay, by in
            [(a + y1, b + y1, a + y2, b + y2) for a, b, _ in pts]]),)


batch_types = {
    'SOLID': (('TRIS', to_tris),),
    'LINE': (('LINES', to_lines),),
    'FRAME': (('LINES', to_frames),),
    'SOLID_FRAME': (('TRIS', to_tris),
                    ('LINES', to_frames))}


# Find character width
def get_cw(loc, firstx, lines):
    for idx, line in enumerate(lines):
        if len(line.body) > 1:
            return loc(idx, 1)[0] - firstx


# Find all occurrences and generate points to draw rects
def get_non_wrapped_pts(context, substr, selr, lineh, wunits):
    pts = []
    scrollpts = []
    append = pts.append

    st = context.space_data
    txt = st.text
    top = st.top
    lines = txt.lines
    curl = txt.current_line
    strlen = len(substr)
    loc = st.region_location_from_cursor

    firstxy = loc(0, 0)
    x_offset = cw = get_cw(loc, firstxy[0], lines)
    str_span_px = cw * strlen

    if st.show_line_numbers:
        x_offset += cw * (len(repr(len(lines))) + 2)

    # Vertical span in pixels
    lenl = len(st.text.lines)
    vspan_px = lineh
    if lenl > 1:
        vspan_px = abs(firstxy[1] - loc(lenl - 1, len(lines[-1].body))[1])

    region = context.region
    rw, rh = region.width, region.height
    hor_max_px = rw - (wunits // 2)
    if p.show_in_scroll:
        args = st, substr, wunits, vspan_px, rw, rh, lineh
        scrollpts = scrollpts_get(*args)

    for idx, line in enumerate(lines[top:top + st.visible_lines + 2], top):
        body = line.body
        find = body.lower().find if not p.case_sensitive else body.find
        if line == curl:
            match_indices = get_matches_curl(substr, strlen, find, selr)
        else:
            match_indices = get_matches(substr, strlen, find)

        if len(match_indices) > 1000:
            return pts, scrollpts

        for match_idx in match_indices:
            x1, y1 = loc(idx, match_idx)
            x2 = x1 + str_span_px
            if x1 > hor_max_px or x2 <= x_offset:
                continue

            char_offset = (x_offset - x1) // cw if x1 < x_offset else 0
            end_idx = match_idx + strlen
            end_idx -= 1 + (x2 - hor_max_px) // cw if x2 > hor_max_px else 0

            append((Vector((x1 + cw * char_offset, y1)),
                    Vector((x2, y1)),
                    body[match_idx + char_offset:end_idx]))

    return pts, scrollpts


# Calculate true top and pixel span when word wrap is turned on
def calc_top(lines, maxy, lineh, rh, yoffs, char_max):
    top = 0
    found = False
    wrap_offset = maxy + yoffs
    wrap_span_px = -lineh
    if char_max < 8:
        char_max = 8
    for idx, line in enumerate(lines):
        wrap_span_px += lineh
        if wrap_offset < rh:
            if not found:
                found = True
                top = idx
        wrap_offset -= lineh
        pos = start = 0
        end = char_max

        body = line.body
        if len(body) < char_max:
            continue

        for c in body:
            if pos - start >= char_max:
                wrap_span_px += lineh
                if wrap_offset < rh:
                    if not found:
                        found = True
                        top = idx
                wrap_offset -= lineh
                start = end
                end += char_max
            elif c is " " or c is "-":
                end = pos + 1
            pos += 1
    return top, wrap_span_px


# Find all occurrences and display as lines on scrollbar
def scrollpts_get(st, substr, wu, vspan_px, rw, rh, lineh):
    scrollpts = []
    append = scrollpts.append
    top_margin = int(0.4 * wu)

    # x offset for scrollbar widget start
    sx_2 = int(rw - 0.2 * wu)
    sx_1 = sx_2 - top_margin + 2
    pxavail = rh - top_margin * 2
    wrh = wrhorg = (vspan_px // lineh) + 1  # wrap lines
    scrolltop = rh - (top_margin + 2)

    vispan = st.top + st.visible_lines
    blank_lines = st.visible_lines // 2
    if wrh + blank_lines < vispan:
        blank_lines = vispan - wrh

    wrh += blank_lines
    j = 2 + wrhorg / len(st.text.lines) * pxavail
    for i, line in enumerate(st.text.lines, 1):
        body = line.body.lower() if not p.case_sensitive else line.body
        if substr in body:
            y = scrolltop - i * j // wrh
            append((Vector((sx_1, y)), Vector((sx_2, y))))
    return scrollpts


def get_wrapped_pts(context, substr, selr, lineh, wunits):
    # t = perf_counter()

    pts = []
    scrollpts = []
    append = pts.append

    st = context.space_data
    txt = st.text
    lines = txt.lines
    curl = txt.current_line
    lenl = len(lines)

    loc = st.region_location_from_cursor
    firstxy = loc(0, 0)
    x_offset = cw = get_cw(loc, firstxy[0], lines)

    if st.show_line_numbers:
        x_offset += cw * (len(repr(lenl)) + 2)

    region = context.region
    rh, rw = region.height, region.width
    # Maximum displayable characters in editor
    char_max = (rw - wunits - x_offset) // cw
    if char_max < 8:
        char_max = 8

    line_height_dpi = int((wunits * st.font_size) / 20)
    y_offset = int(line_height_dpi * 0.3)
    top, vspan_px = calc_top(lines, firstxy[1], lineh, rh, y_offset, char_max)
    strlen = len(substr)

    # Screen coord tables for fast lookup of match positions
    x_table = range(0, cw * char_max, cw)
    y_top = loc(top, 0)[1]
    y_table = range(y_top, y_top - vspan_px, -lineh)
    y_table_size = len(y_table)

    wrap_total = w_count = wrap_offset = 0

    # Generate points for scrollbar highlights
    # if p.show_in_scroll:
    if p.show_in_scroll:
        args = st, substr, wunits, vspan_px, rw, rh, lineh
        scrollpts = scrollpts_get(*args)

    # Generate points for text highlights
    for l_idx, line in enumerate(lines[top:top + st.visible_lines + 4], top):
        body = line.body
        find = body.lower().find if not p.case_sensitive else body.find

        if line == curl:
            # Selected line is processed separately
            match_indices = get_matches_curl(substr, strlen, find, selr)
        else:
            match_indices = get_matches(substr, strlen, find)

        # Hard max for match finding
        if len(match_indices) > 1000:
            return pts, scrollpts

        # Wraps
        w_list = []
        w_start = 0
        w_end = char_max
        w_count = -1
        coords = deque()

        # Simulate word wrapping for displayed text and store
        # local text coordinates and wrap indices for each line.
        for idx, char in enumerate(body):
            if idx - w_start >= char_max:
                w_list.append(body[w_start:w_end])
                w_count += 1
                coords.extend([(i, w_count) for i in range(w_end - w_start)])
                w_start = w_end
                w_end += char_max
            elif char in wrap_chars:
                w_end = idx + 1

        w_list.append(body[w_start:])
        w_end = w_start + (len(body) - w_start)
        w_count += 1
        coords.extend([(i, w_count) for i in range(w_end - w_start)])
        w_indices = [i for i, _ in enumerate(w_list) for _ in _]

        # screen coords for wrapped char/line by match index
        for match_idx in match_indices:
            mspan = match_idx + strlen

            w_char, w_line = coords[match_idx]
            w_char_end, w_line_end = coords[mspan - 1]

            # in edge cases where a single wrapped line has
            # several thousands of matches, skip and continue
            if w_line > y_table_size or w_line_end > y_table_size:
                continue

            matchy = y_table[w_line] - wrap_offset
            if matchy > rh or matchy < -lineh:
                continue

            co_1 = Vector((x_offset + x_table[w_char], matchy))

            if w_line != w_line_end:
                start = match_idx
                end = wrap_idx = 0

                for midx in range(strlen):
                    widx = match_idx + midx
                    w_char, w_line = coords[widx]
                    matchy = y_table[w_line] - wrap_offset

                    if matchy != co_1.y:
                        co_2 = Vector((x_table[w_char - 1] + cw + x_offset,
                                       y_table[w_line - 1] - wrap_offset))

                        if wrap_idx:
                            text = w_list[w_indices[widx - 1]]
                        else:
                            text = body[start:widx]
                        append((co_1, co_2, text))
                        co_1 = Vector((x_offset + x_table[w_char], matchy))
                        end = midx
                        start += end
                        wrap_idx += 1
                        continue
                text = body[match_idx:mspan][end:]
                co_2 = Vector((x_offset + x_table[w_char] + cw, matchy))
                append((co_1, co_2, text))

            else:
                text = body[match_idx:mspan]
                co_2 = co_1.copy()
                co_2.x += cw * strlen
                append((co_1, co_2, text))

        wrap_total += w_count + 1
        wrap_offset = lineh * wrap_total
    # t2 = perf_counter()
    # print("draw:", round((t2 - t) * 1000, 2), "ms")
    return pts, scrollpts


# for calculating offsets and max displayable characters
# source/blender/windowmanager/intern/wm_window.c$515
def get_widget_unit(context):
    system = context.preferences.system
    p = system.pixel_size
    pd = p * system.dpi
    return int((pd * 20 + 36) / 72 + (2 * (p - pd // 72)))


def draw_highlights(context):
    # t = perf_counter()
    st = context.space_data
    txt = st.text

    if not txt:
        return

    selr = sorted((txt.current_character, txt.select_end_character))
    curl = txt.current_line
    substr = curl.body[slice(*selr)]

    if not substr.strip():
        # Nothing to find
        return

    if not p.case_sensitive:
        substr = substr.lower()

    if len(substr) >= p.min_str_len and curl == txt.select_end_line:
        wunits = get_widget_unit(context)
        line_height_dpi = (wunits * st.font_size) / 20
        line_height = int(line_height_dpi + 0.3 * line_height_dpi)
        draw_type = p.draw_type
        args = context, substr, selr, line_height, wunits

        if st.show_word_wrap:
            pts, scrollpts = get_wrapped_pts(*args)
        else:
            pts, scrollpts = get_non_wrapped_pts(*args)

        y_offset = round(line_height_dpi * 0.3)

        scroll_tris = to_scroll(line_height, scrollpts, 2)
        scroll_batch = [batch_for_shader(
                        shader, 'TRIS', {'pos': scroll_tris}).draw]
        draw_batches(context, scroll_batch, get_colors('SCROLL'))

        batches = [batch_for_shader(
                   shader, btyp, {'pos': fn(line_height, pts, y_offset)}).draw
                   for b in batch_types[draw_type] for (btyp, fn) in [b]]

        draw_batches(context, batches, get_colors(draw_type))

        y_offset += int(line_height_dpi * 0.3)
        # highlight font overlay starts here
        fontid = 1
        blf.color(fontid, *p.fg_col)
        for co, _, substring in pts:
            co.y += y_offset
            blf.position(fontid, *co, 1)
            blf.draw(fontid, substring)
    # t2 = perf_counter()
    # print("draw:", round((t2 - t) * 1000, 2), "ms")


def _disable(context, st, prefs):
    handle = getattr(prefs, "_handle", None)
    if handle:
        st.draw_handler_remove(handle, 'WINDOW')
        redraw(context)
        del prefs._handle


def update_highlight(self, context):
    prefs = HighlightOccurrencesPrefs
    st = bpy.types.SpaceTextEditor
    _disable(context, st, prefs)
    if not self.enable:
        return

    args = draw_highlights, (context,), 'WINDOW', 'POST_PIXEL'
    bpy.app.timers.register(lambda: setattr(prefs, "_handle",
                            st.draw_handler_add(*args)), first_interval=0)


class HighlightOccurrencesPrefs(bpy.types.AddonPreferences):
    bl_idname = __name__

    colors = {
        "BLUE": ((.25, .33, .45, 1),
                 (1, 1, 1, 1),
                 (.18, .44, .61, 1),
                 (0.14, .6, 1, .55)),

        "YELLOW": ((.39, .38, .07, 1),
                   (1, 1, 1, 1),
                   (.46, .46, 0, 1),
                   (1, .79, .09, .4)),

        "GREEN": ((.24, .39, .26, 1),
                  (1, 1, 1, 1),
                  (.2, .5, .19, 1),
                  (.04, 1., .008, .4)),

        "RED": ((.58, .21, .21, 1),
                (1, 1, 1, 1),
                (.64, .27, .27, 1),
                (1, 0.21, .21, 0.5))
    }

    from bpy.props import (BoolProperty, FloatVectorProperty, EnumProperty,
                           IntProperty, FloatProperty)

    enable: BoolProperty(description="Enable highlighting",
                         name="Highlight Occurrences",
                         default=True,
                         update=update_highlight)

    line_thickness: IntProperty(description="Line Thickness",
                                default=1,
                                name="Line Thickness",
                                min=1,
                                max=4)

    show_in_scroll: BoolProperty(description="Show in scrollbar",
                                 name="Show in Scrollbar",
                                 default=True)

    min_str_len: IntProperty(description="Don't search below this",
                             name='Minimum Search Length',
                             default=2,
                             min=1,
                             max=4)

    case_sensitive: BoolProperty(description='Case Sensitive Matching',
                                 name='Case Sensitive',
                                 default=False)

    col_bg: FloatVectorProperty(description='Background color',
                                name='Background',
                                default=colors['BLUE'][0],
                                subtype='COLOR',
                                size=4,
                                min=0,
                                max=1)

    col_line: FloatVectorProperty(description='Line and frame color',
                                  name='Line / Frame',
                                  default=colors['BLUE'][2],
                                  subtype='COLOR',
                                  size=4,
                                  min=0,
                                  max=1)

    fg_col: FloatVectorProperty(description='Foreground color',
                                name='Foreground',
                                default=colors['BLUE'][1],
                                size=4,
                                min=0,
                                subtype='COLOR',
                                max=1)

    col_scroll: FloatVectorProperty(description="Scroll highlight opacity",
                                    name="Scrollbar",
                                    default=colors['BLUE'][3],
                                    size=4,
                                    min=0,
                                    max=1,
                                    subtype='COLOR')

    draw_type: EnumProperty(description="Draw type for highlights",
                            name="Draw Type",
                            default="SOLID_FRAME",
                            items=(("SOLID", "Solid", "", 1),
                                   ("LINE", "Line", "", 2),
                                   ("FRAME", "Frame", "", 3),
                                   ("SOLID_FRAME", "Solid + Frame", "", 4)))

    col_preset: EnumProperty(description="Highlight color presets",
                             default="BLUE", name="Presets",
                             update=update_colors,
                             items=(("BLUE", "Blue", "", 1),
                                    ("YELLOW", "Yellow", "", 2),
                                    ("GREEN", "Green", "", 3),
                                    ("RED", "Red", "", 4),
                                    ("CUSTOM", "Custom", "", 5)))

    del (BoolProperty, FloatVectorProperty,
         EnumProperty, IntProperty, FloatProperty)

    def draw(self, context):
        layout = self.layout

        split = layout.split()
        prop = split.column().prop
        for item in ["show_in_scroll", "case_sensitive", "min_str_len"]:
            prop(self, item)

        split.column()

        split = layout.split()
        col = split.column()

        split.column()
        col.prop(self, "line_thickness")
        col.enabled = self.draw_type in {'LINE', 'FRAME', 'SOLID_FRAME'}
        layout.row().prop(self, "draw_type", expand=True)
        layout.grid_flow(align=True).prop(self, "col_preset", expand=True)

        if self.col_preset == 'CUSTOM':
            split = layout.column().split()
            for item in ["col_bg", "fg_col", "col_line", "col_scroll"]:
                split.column().prop(self, item)

    def draw_menu(self, context):
        prefs = bpy.context.preferences.addons[__name__].preferences
        self.layout.prop(prefs, "enable")


def redraw(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'TEXT_EDITOR':
                area.tag_redraw()


def register():
    bpy.utils.register_class(HighlightOccurrencesPrefs)

    import sys
    prefs = bpy.context.preferences.addons[__name__].preferences
    sys.modules[__name__].p = prefs
    bpy.types.TEXT_MT_view.append(HighlightOccurrencesPrefs.draw_menu)
    prefs.enable = True
    # update_highlight(prefs, bpy.context)


def unregister():
    prefs = bpy.context.preferences.addons[__name__].preferences
    prefs.enable = False
    # update_highlight(prefs, bpy.context)
    # if prefs.enable:
    #     print("was enable")
    #     prefs.enable = False
    #     update_highlight(prefs, bpy.context)
    # else:
    #     print("not enable")

    bpy.types.TEXT_MT_view.remove(HighlightOccurrencesPrefs.draw_menu)
    bpy.utils.unregister_class(HighlightOccurrencesPrefs)
    redraw(getattr(bpy, "context"))
