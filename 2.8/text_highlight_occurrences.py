import bpy
from gpu.shader import from_builtin
from mathutils import Vector
from gpu_extras.batch import batch_for_shader
from itertools import chain
from collections import deque
from time import perf_counter
from bgl import glLineWidth, glEnable, glDisable, GL_BLEND
from blf import (
    # dimensions as blf_dimensions,
    position as blf_position,
    color as blf_color,
    draw as blf_draw,)

bl_info = {
    "name": "Highlight Occurrences",
    "description": "Enables highlighting for words matching selected text",
    "author": "kaio",
    "version": (1, 0, 0),
    "blender": (2, 81, 0),
    "location": "Text Editor",
    "category": "Text Editor"
}

shader = from_builtin('2D_UNIFORM_COLOR')
shader_uniform_float = shader.uniform_float
shader_bind = shader.bind
iterchain = chain.from_iterable
wrap_chars = {' ', '-'}
p = None


def clamp(top, lenl):
    if -1 < top < lenl:
        return top
    if top < lenl:
        return 0
    return lenl - 1


def get_matches_curl(substr, size, find, selr):
    match_indices = []
    idx = find(substr, 0)
    exclude = range(*selr)
    append = match_indices.append
    while idx is not -1:
        span = idx + size
        if idx in exclude or span in exclude:
            idx = find(substr, idx + 1)
            continue
        append(idx)
        idx = find(substr, span)
    return match_indices


def get_matches(substr, size, find):
    match_indices = []
    append = match_indices.append
    chr_idx = find(substr, 0)
    while chr_idx is not -1:
        append(chr_idx)
        chr_idx = find(substr, chr_idx + size)
    return match_indices


def get_colors(draw_type):
    colors = {
        'SOLID': (p.bg_col,),
        'LINE': (p.line_col,),
        'FRAME': (p.line_col,),
        'SOLID_FRAME': (p.bg_col,
                        p.line_col)}
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
    col_attrs = ("bg_col", "fg_col", "line_col")
    if self.col_preset != 'CUSTOM':
        for source, target in zip(self.colors[self.col_preset], col_attrs):
            setattr(self, target, source)


def redraw(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'TEXT_EDITOR':
                area.tag_redraw()


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
        [(a, b, ay, by, ay, a, by, b) for a, b, ay, by in
            [(a + y1, b + y1, a + y2, b + y2) for a, b, _ in pts]]),)


batch_types = {
    'SOLID': (('TRIS', to_tris),),
    'LINE': (('LINES', to_lines),),
    'FRAME': (('LINES', to_frames),),
    'SOLID_FRAME': (('TRIS', to_tris),
                    ('LINES', to_frames))}


def get_y_offset(rh, lineh, fs, yco):
    rh_min_1 = rh - lineh
    rh_min_2 = rh - (lineh * 2)
    for y_ref in yco:
        if rh_min_1 >= y_ref >= rh_min_2:
            return rh_min_1 - y_ref
    return lineh / fs


def get_non_wrapped_pts(st, txt, curl, substr, selr, lineh, wunits, xoffset):
    scrollpts = []
    pts = []
    append = pts.append
    top = st.top
    lines = txt.lines
    size = len(substr)
    region = bpy.context.area.regions[-1]
    rw = region.width
    loc = st.region_location_from_cursor
    cw = loc(0, 1)[0] - loc(0, 0)[0]
    # cw = round(blf_dimensions(1, " ")[0])
    cspan = cw * size
    yco = range(loc(top, 0)[1], -lineh, -lineh)
    y_offset = get_y_offset(region.height, lineh, st.font_size, yco)
    xoffset += (st.show_line_numbers and cw * len(repr(len(lines)))) or 0
    viewmax = rw - (wunits // 2)

    for idx, line in enumerate(lines[top:top + st.visible_lines + 2], top):
        bod = line.body
        find = bod.lower().find if not p.case else bod.find
        if line == curl:
            match_indices = get_matches_curl(substr, size, find, selr)
        else:
            match_indices = get_matches(substr, size, find)

        if len(match_indices) > 100:
            return pts, y_offset

        for midx in match_indices:
            x1, y1 = loc(idx, midx)
            x2 = x1 + cspan
            if x1 > viewmax or x2 <= xoffset:
                continue

            cofs = (xoffset - x1) // cw if x1 < xoffset else 0
            c2 = midx + size
            c2 -= 1 + (x2 - viewmax) // cw if x2 > viewmax else 0

            append((Vector((x1 + cw * cofs, y1)),
                    Vector((x2, y1)),
                    bod[midx + cofs:c2]))

    return pts, scrollpts, y_offset


def calc_top(top, maxy, lenl, loc, lines, lineh, rh):

    # this can probably be more efficient
    #
    # we don't need to find the last
    # line if top is above half of lenl

    miny = 0
    if lenl > 1:
        miny = loc(lenl - 1, len(lines[-1].body))[1]
        dif = abs(maxy - miny)
        top = round(lenl - (dif * (rh - miny) / dif) / (dif / lenl)) + 2
    else:
        dif = lineh
    top = clamp(top, lenl)
    rhmin = rh - (lineh * 2)
    y = loc(top, len(lines[top].body))[1]

    while y < rhmin:
        if top < 1:
            break
        top -= 1
        y = loc(top, 0)[1]

    return clamp(top, lenl), dif, miny


def indexof(lines, line, lenl, top=0):
    line_hash = hash(line)
    for idx, l in enumerate(lines):
        if hash(l) == line_hash:
            return idx


def get_wrapped_pts(st, txt, curl, substr, selr, lineh, wunits, xoffset):

    loc = st.region_location_from_cursor
    pts = []
    append = pts.append

    scrollpts = []
    scr_append = scrollpts.append

    lines = txt.lines
    lenl = len(lines)
    region = bpy.context.area.regions[-1]

    firstxy = loc(0, 0)
    maxy = firstxy[1]
    cw = loc(0, 1)[0] - firstxy[0]
    rh, rw = region.height, region.width
    # rlimit = ry + rh
    fs = st.font_size
    top_margin = int(0.4 * wunits)

    # x offset for scrollbar widget start
    sx_2 = int(rw - 0.2 * wunits)
    sx_1 = sx_2 - top_margin + 2

    # add to x offset for text when line numbers are visible
    xoffset += (st.show_line_numbers and cw * len(repr(lenl))) or 0

    # maximum displayable characters in editor
    cmax = (rw - wunits - xoffset) // cw
    if cmax < 8:
        cmax = 8

    # estimate top by comparing coords of first / last line
    stp = st.top
    top, pxspan, miny = calc_top(stp, maxy, lenl, loc, lines, lineh, rh)
    size = len(substr)
    # calc_scroll = perf_counter()
    pxavail = rh - top_margin * 2
    wrh = wrhorg = (pxspan // lineh) + 1  # wrap height in lines
    # wrh = pxspan // lineh + 1  # wrap height in lines
    endl_idx = indexof(lines, txt.select_end_line, lenl, top)
    # current line position with wrap offset
    curlwofs = abs(maxy - loc(txt.current_line_index, 0)[1]) / lineh
    sellwofs = abs(maxy - loc(endl_idx, 0)[1]) / lineh
    # scrollmax = abs(maxy - maxy) / lineh
    # scrollmin = abs(maxy - miny) / lineh
    scrolltop = rh - top_margin

    vis = st.visible_lines
    yco = range(loc(top, 0)[1], -100000, -lineh)
    xco = range(0, cw * cmax, cw)
    tsize = len(yco)
    y_offset = get_y_offset(rh, lineh, fs, yco)
    if p.show_in_scroll:
        vispan = stp + vis
        blank_lines = vis // 2
        if wrh + blank_lines < vispan:
            blank_lines = vispan - wrh

        wrh += blank_lines
        barh = int((vis * pxavail) / wrh) if wrh > 0 else 0
        pxdif = 0

        if barh < 20:
            pxdif, barh = 20 - barh, 20

        pxmrg = pxavail - pxdif
        if wrh > 0:
            bar1 = int((pxmrg * stp) / wrh)
        else:
            bar1 = barh = 0

        j = 2 + wrhorg / lenl * pxavail
        substr_s = substr.lower()
        for i, line in enumerate(lines, 1):
            if substr_s in line.body.lower():
                y = scrolltop - 2 - (i * j) // wrh
                scr_append((
                    Vector((sx_1, y)),
                    Vector((sx_2, y))))

        barspan = bar1 + barh
        lhl1, lhl2 = sorted((curlwofs, sellwofs))
        hl1 = (lhl1 * pxavail) // wrh
        hl2 = (lhl2 * pxavail) // wrh

        if pxdif > 0:
            if lhl1 >= stp and lhl1 <= vispan:
                hl1 = int(((pxmrg * lhl1) / wrh) +
                          (pxdif * (lhl1 - stp) / vis))
            elif lhl1 > vispan and hl1 < barspan and hl1 > bar1:
                hl1 = barspan
            elif lhl2 > stp and lhl1 < stp and hl1 > bar1:
                hl1 = bar1
            if hl2 <= hl1:
                hl2 = hl1 + 2
            if lhl2 >= stp and lhl2 <= vispan:
                hl2 = int(((pxmrg * lhl2) / wrh) +
                          (pxdif * (lhl2 - stp) / vis))
            elif lhl2 < stp and hl2 >= bar1 - 2 and hl2 < barspan:
                hl2 = bar1
            elif lhl2 > vispan and lhl1 < stp + vis and hl2 < barspan:
                hl2 = barspan
            if hl2 <= hl1:
                hl1 = hl2 - 2
        if hl2 - hl1 < 2:
            hl2 = int(hl1 + 2)

        # keep as reference

        # hlstart = (scrollmax * pxavail) // wrh
        # hlend = (scrollmin * pxavail) // wrh
        # sy_2 = scrolltop - 3
        # sy_1 = sy_2 - hlend
        # scr_append((Vector((sx_1, sy_2)), Vector((sx_2, sy_2)), ""))
        # scr_append((Vector((sx_1, sy_1)), Vector((sx_2, sy_1)), ""))

        # hlminy = scrolltop - hl2 - 1
        # scr_append((Vector((sx_1, hlminy)), Vector((sx_2, hlminy))))
        # scr_append((Vector((sx_1, hlminy)), Vector((sx_2, hlminy)), ""))

    totwrap = wrap = woffset = 0
    for l_idx, line in enumerate(lines[top:top + vis + 4], top):
        bod = line.body
        find = bod.lower().find if not p.case else bod.find
        if line == curl:
            match_indices = get_matches_curl(substr, size, find, selr)
        else:
            match_indices = get_matches(substr, size, find)

        if len(match_indices) > 100:
            return pts, y_offset

        wlist = []
        wappend = wlist.append
        wstart = 0
        wend = cmax  # wrap cut-off
        wrap = -1
        coords = deque()
        extend = coords.extend

        # simulate word-wrapping only,
        # but keep track of wrap indices
        for idx, char in enumerate(bod):
            if idx - wstart >= cmax:
                wappend(bod[wstart:wend])
                wrap += 1
                extend([(i, wrap) for i in range(wend - wstart)])
                wstart = wend
                wend += cmax
            elif char in wrap_chars:
                wend = idx + 1

        wappend(bod[wstart:])
        wend = wstart + (len(bod) - wstart)
        wrap += 1
        extend([(i, wrap) for i in range(wend - wstart)])
        wrap_indices = [i for i, _ in enumerate(wlist) for _ in _]

        # if match_indices:
        #     print(top, l_idx + wrap)
        # wrap_offset_idx.append(l_idx + wrap - 1)

        # screen coords for wrapped char/line by match index
        for match_idx in match_indices:
            mspan = match_idx + size

            wrapc, wrapl = coords[match_idx]
            wrapc_end, wrapl_end = coords[mspan - 1]
            # print(wrapc_end, wrapl_end)

            # in edge cases where a single wrapped line has
            # several thousands of matches, skip and continue
            if wrapl > tsize or wrapl_end > tsize:
                continue

            matchy = yco[wrapl] - woffset
            # if matchy > rlimit or matchy < -lineh:
            if matchy > rh or matchy < -lineh:
                continue

            co_1 = Vector((xoffset + xco[wrapc], matchy))

            if wrapl != wrapl_end:
                start = match_idx
                end = wrap_idx = 0

                for midx in range(size):
                    widx = match_idx + midx
                    wrapc, wrapl = coords[widx]
                    matchy = yco[wrapl] - woffset

                    if matchy != co_1.y:
                        co_2 = Vector((xco[wrapc - 1] + cw + xoffset,
                                       yco[wrapl - 1] - woffset))

                        if wrap_idx:
                            text = wlist[wrap_indices[widx - 1]]
                        else:
                            text = bod[start:widx]
                        append((co_1, co_2, text))
                        co_1 = Vector((xoffset + xco[wrapc], matchy))
                        end = midx
                        start += end
                        wrap_idx += 1
                        continue
                text = bod[match_idx:mspan][end:]
                co_2 = Vector((xoffset + xco[wrapc] + cw, matchy))
                append((co_1, co_2, text))

            else:
                text = bod[match_idx:mspan]
                co_2 = co_1.copy()
                co_2.x += cw * size
                append((co_1, co_2, text))

        totwrap += wrap + 1
        woffset = lineh * totwrap
    return pts, scrollpts, y_offset


# for calculating offsets and max displayable characters
# source/blender/windowmanager/intern/wm_window.c$515
def get_widget_unit(context):
    system = context.preferences.system
    p = system.pixel_size
    pd = p * system.dpi
    return int((pd * 20 + 36) / 72 + (2 * (p - pd // 72)))


def draw_highlights(context):
    # print("\n" * 40)
    # t = perf_counter()
    st = context.space_data
    txt = st.text
    if not txt:
        return
    selr = sorted((txt.current_character, txt.select_end_character))
    curl = txt.current_line
    substr = curl.body[slice(*selr)]
    if not substr.strip():
        return
    if not p.case:
        substr = substr.lower()

    if len(substr) >= p.min_str_len and curl == txt.select_end_line:
        wunits = get_widget_unit(context)
        lh_dpi = (wunits * st.font_size) // 20
        lh = lh_dpi + int(0.3 * lh_dpi)
        xoffset = wunits // 2
        draw_type = p.draw_type
        args = st, txt, curl, substr, selr, lh, wunits, xoffset
        if st.show_word_wrap:
            pts, scrollpts, y_ofs = get_wrapped_pts(*args)
        else:
            pts, scrollpts, y_ofs = get_non_wrapped_pts(*args)

        # tpredraw = perf_counter()

        scroll_tris = to_scroll(lh, scrollpts, 2)
        scroll_batch = [batch_for_shader(
            shader, 'TRIS', {'pos': scroll_tris}).draw]
        draw_batches(context, scroll_batch, get_colors(draw_type))

        batches = [batch_for_shader(
                   shader, btyp, {'pos': fn(lh, pts, y_ofs)}).draw
                   for b in batch_types[draw_type] for (btyp, fn) in [b]]
        draw_batches(context, batches + scroll_batch, get_colors(draw_type))
        # highlight font overlay starts here
        fontid = 1
        blf_color(fontid, *p.fg_col)
        for co, _, substring in pts:
            co.y += xoffset
            blf_position(fontid, *co, 1)
            blf_draw(fontid, substring)
        # tend = perf_counter()
    #     print(" Pre-Scan:", round((tprescan - t) * 1000, 2), "ms")
    #     print(" Scan:", round((tpredraw - tprescan) * 1000, 2), "ms")
    #     print(" Draw:", round((tend - tpredraw) * 1000, 2), "ms")
    # print("Total Time:", round((perf_counter() - t) * 1000, 2), "ms")


class HighlightOccurrencesPrefs(bpy.types.AddonPreferences):
    bl_idname = __name__
    from bpy.props import (
        BoolProperty, FloatVectorProperty, EnumProperty, IntProperty)

    line_thickness: IntProperty(default=1, name="Line Thickness", min=1, max=4)
    show_in_scroll: BoolProperty(
        name="Show in Scrollbar", default=True,
        description="Show highlights in scrollbar")

    min_str_len: IntProperty(
        description='Skip finding occurrences below this number', default=2,
        name='Minimum Search Length', min=1, max=4)

    case: BoolProperty(
        description='Highlight identical matches only', default=False,
        name='Case Sensitive',)

    bg_col: FloatVectorProperty(
        description='Background color', default=(.25, .33, .45, 1),
        name='Background', subtype='COLOR_GAMMA', size=4, min=0, max=1)

    line_col: FloatVectorProperty(
        description='Line and frame color', subtype='COLOR_GAMMA', size=4,
        default=(.14, .33, .39, 1), name='Line / Frame', min=0, max=1)

    fg_col: FloatVectorProperty(
        description='Foreground color', name='Foreground', size=4, min=0,
        default=(1, 1, 1, 1), subtype='COLOR_GAMMA', max=1)

    draw_type: EnumProperty(
        description="Draw type for highlights",
        default="SOLID_FRAME", name="Draw Type",
        items=(
            ("SOLID", "Solid", "", 1),
            ("LINE", "Line", "", 2),
            ("FRAME", "Frame", "", 3),
            ("SOLID_FRAME", "Solid + Frame", "", 4)))

    col_preset: EnumProperty(
        description="Highlight color presets",
        default="BLUE", name="Presets",
        update=update_colors,
        items=(
            ("BLUE", "Blue", "", 1),
            ("YELLOW", "Yellow", "", 2),
            ("GREEN", "Green", "", 3),
            ("RED", "Red", "", 4),
            ("CUSTOM", "Custom", "", 5)))

    colors = {
        "BLUE": ((.25, .33, .45, 1), (1, 1, 1, 1), (.14, .33, .39, 1)),
        "YELLOW": ((.39, .38, .07, 1), (1, 1, 1, 1), (.46, .46, 0, 1)),
        "GREEN": ((.24, .39, .26, 1), (1, 1, 1, 1), (.2, .5, .19, 1)),
        "RED": ((.58, .21, .21, 1), (1, 1, 1, 1), (.64, .27, .27, 1))}

    def draw(self, context):
        lines_only = self.draw_type in {'LINE', 'FRAME', 'SOLID_FRAME'}
        layout = self.layout

        split = layout.split()
        col = split.column()
        col.prop(self, "show_in_scroll")
        col.prop(self, "case")
        col.prop(self, "min_str_len")
        split.column()
        split = layout.split()
        col = split.column()
        split.column()
        col.prop(self, "line_thickness")
        col.enabled = lines_only
        row = layout.row()
        row.prop(self, "draw_type", expand=True)
        grid = layout.grid_flow(align=True)
        grid.prop(self, "col_preset", expand=True)
        if self.col_preset == 'CUSTOM':
            col = layout.column()
            split = col.split()
            col = split.column()
            col.prop(self, "bg_col")
            col = split.column()
            col.prop(self, "fg_col")
            col = split.column()
            col.prop(self, "line_col")


def register():
    bpy.utils.register_class(HighlightOccurrencesPrefs)
    import sys
    prefs = bpy.context.preferences.addons[__name__].preferences
    sys.modules[__name__].p = prefs

    bpy.app.timers.register(
        lambda: setattr(
            HighlightOccurrencesPrefs,
            "handler",
            bpy.types.SpaceTextEditor.draw_handler_add(
                draw_highlights,
                (getattr(bpy, "context"),),
                'WINDOW', 'POST_PIXEL')) or redraw(getattr(bpy, "context")))


def unregister():
    try:
        bpy.types.SpaceTextEditor.draw_handler_remove(
            HighlightOccurrencesPrefs.handler, 'WINDOW')
    except ValueError:
        pass

    bpy.utils.unregister_class(HighlightOccurrencesPrefs)
    redraw(getattr(bpy, "context"))
