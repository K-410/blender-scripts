# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

import bpy
import bgl
import blf
# from time import perf_counter
from gpu.shader import from_builtin
from gpu_extras.batch import batch_for_shader
from bpy.types import Operator
from collections import defaultdict, deque
from itertools import repeat

bl_info = {
    "name": "Code Editor",
    "location": "Text Editor > Right Click Menu",
    "version": (0, 1, 0),
    "blender": (2, 82, 0),
    "description": "Better editor for coding",
    "author": "Jerryno, tintwotin, kaio",
    "category": "Text Editor",
}


sh_2d = from_builtin('2D_UNIFORM_COLOR')
sh_2d_uniform_float = sh_2d.uniform_float
sh_2d_bind = sh_2d.bind


# emulate list of integers with slicing
# capability. use with tracking indents
class DefaultInt(defaultdict):
    __slots__ = ('_setitem', '_delitem', '_get')

    def __init__(self):
        sclass = super(__class__, self)
        sclass.__init__()
        self._setitem = sclass.__setitem__
        self._delitem = sclass.__delitem__
        self._get = sclass.__getitem__

    def _parse_slice(self, obj):
        start = obj.start or 0
        stop = obj.stop or len(self) or start + 1
        step = obj.step or 1
        return range(start, stop, step)

    def __delitem__(self, i):
        if isinstance(i, slice):
            for i in self._parse_slice(i):
                del self[i]
        elif i in self:
            self._delitem(i)

    def __missing__(self, i):
        self._setitem(i, -1)
        return self[i]

    def __getitem__(self, i):
        if isinstance(i, slice):
            return [self._get(j) for j in self._parse_slice(i)]
        return self._get(i)


class TextCache(defaultdict):
    __slots__ = ('__dict__',)

    def __init__(self):
        super(__class__, self).__init__()
        self.__dict__ = self

    def __missing__(self, key):  # generate a blank cache
        text = bpy.data.texts.get(key, self.ce.wrap_text)
        self.purge_unused()
        hashes = defaultdict(lambda: None)

        def defaultlist():
            return [[] for _ in repeat(None, len(text.lines))]
        data = defaultdict(defaultlist)
        indents = DefaultInt()
        cache = self[key] = (hashes,   # body hashes
                             data,     # syntax data
                             [],       # ????
                             indents)  # indents data
        return cache

    def purge_unused(self):
        for k in [k for k in self if k != 'ce' and k not in ce_manager]:
            if k not in bpy.data.texts:
                del self[k]


class WrapText:
    __slots__ = ('ce', 'name', 'lines', 'cmax', 'hashes')

    class WrapTextLine:
        __slots__ = ('body', 'is_sub', 'oidx')

        def __init__(self, body, oidx, is_sub=False):
            self.body = body
            self.is_sub = is_sub
            self.oidx = oidx

    def __init__(self, text, ce):
        self.ce = ce
        self.name = text.name
        self.lines = []
        self.cmax = ce.cmax
        self.rebuild_lines()

    def check_hash(self):
        otext = bpy.data.texts.get(self.ce.text_name)
        if not otext:  # original text has been renamed or removed
            return
        hashes = self.hashes
        lenl, lenh = len(otext.lines), len(hashes)
        if lenl > lenh:
            hashes.extend((0,) * (lenl - lenh))
        elif lenh > lenl:
            del hashes[lenl:]
        elif self.ce.cmax != self.cmax:
            self.cmax = self.ce.cmax
            *self.hashes, = (0,) * lenl

        # TODO should use a more elaborate check so
        # TODO we don't have to rebuild every line after
        for idx, (line, hash_val) in enumerate(zip(otext.lines, hashes)):
            if hash(line.body) != hash_val:
                return self.rebuild_lines(from_line=idx)

    def rebuild_lines(self, from_line=0):
        otext = bpy.data.texts.get(self.ce.text_name)
        olines = otext.lines
        self.hashes = [hash(l.body) for l in otext.lines]
        wtl = self.WrapTextLine
        cmax = self.ce.cmax
        if cmax < 8:
            cmax = 8

        if not from_line:  # complete wrap rebuild
            self.lines = []

        else:  # partial wrap rebuild (from line)
            for idx, line in enumerate(self.lines):
                if line.oidx == from_line:
                    del self.lines[idx:]
                    break

        append = self.lines.append
        for idx, line in enumerate(olines[from_line:], from_line):
            pos = start = 0
            end = cmax
            body = line.body
            if len(body) < cmax:
                append(wtl(body, idx))
                continue

            for c in body:
                if pos - start >= cmax:
                    append(wtl(body[start:end], idx, is_sub=start > cmax))
                    start = end
                    end += cmax
                elif c is " " or c is "-":
                    end = pos + 1
                pos += 1
            append(wtl(body[start:], idx, is_sub=True))


# maintain (public) caches and give out handles for editors
class CodeEditorManager(dict):
    __slots__ = ('__dict__',)
    tcache = TextCache()
    editors = []

    def __init__(self):
        super(__class__, self).__init__()
        self.__dict__ = self

    # cached text is a defaultdict of lists,
    # so a new one is created automatically
    def get_cached(self, ce):
        if ce.word_wrap:
            # wrapped texts are unique per space, identify by the editor id
            text = ce.wrap_text
            name = ce.id
        else:
            text = bpy.data.texts.get(ce.text_name)
            name = text.name
        self.tcache.ce = ce
        cache = (hsh, data, spec, ind) = self.tcache[name]
        lenl = len(text.lines)
        lenp = len(data[0])

        if lenl > lenp:  # if the length has changed, resize
            for slot in data.values():
                slot.extend([[] for _ in repeat(None, lenl - lenp)])
        elif lenp > lenl:
            del ind[lenl:]
            for data in data.values():
                del data[lenl + 1:]
            pop = hsh.pop
            for i in range(lenl, lenp):
                pop(i, None)
        return cache

    def gcollect(self, context):
        wm = context.window_manager
        eds = {f"ce_{a.as_pointer()}" for w in wm.windows
               for a in w.screen.areas if a.type == 'TEXT_EDITOR'}

        for ed in (*self.keys(),):
            if ed not in eds:
                self.editors.remove(self[ed])
                del self[ed]

    def nuke(self):
        self.tcache.__init__()
        self.editors.clear()
        self.clear()

    def get_ce(self, context):
        handle_id = f"ce_{context.area.as_pointer()}"
        handle = self.get(handle_id)

        if not handle:
            self.gcollect(context)  # remove closed editors
            self[handle_id] = handle = CodeEditorMain(context)
            self.editors.append(self[handle_id])
        return handle


ce_manager = CodeEditorManager()
get_ce = ce_manager.get_ce


def draw_lines_2d(seq, color):
    batch = batch_for_shader(sh_2d, 'LINES', {'pos': seq})
    sh_2d_bind()
    sh_2d_uniform_float("color", [*color])
    batch.draw(sh_2d)


def draw_quads_2d(seq, color):
    qseq, = [(x1, y1, y2, x1, y2, x2) for (x1, y1, y2, x2) in (seq,)]
    batch = batch_for_shader(sh_2d, 'TRIS', {'pos': qseq})
    sh_2d_bind()
    sh_2d_uniform_float("color", [*color])
    batch.draw(sh_2d)


# source/blender/windowmanager/intern/wm_window.c$515
def get_widget_unit(context):
    system = context.preferences.system
    p = system.pixel_size
    pd = p * system.dpi
    return int((pd * 20 + 36) / 72 + (2 * (p - pd // 72)))


# find all multi-line string states
def get_ml_states(text):
    ml_states = []
    ranges = []
    append = ml_states.append
    pop = ml_states.pop
    append2 = ranges.append
    dbl, sgl = "\"\"\"", "\'\'\'"

    for idx, line in enumerate(text.lines):

        body = line.body
        if "\"" in body or "\'" in body:

            find = body.find
            if dbl in body:
                find = body.find
                i = find(dbl, 0)
                while i != -1:
                    if ml_states and ml_states[-1][2] == dbl:
                        append2(range(ml_states[0][0], idx))
                        pop()
                    else:
                        append((idx, i, dbl))
                    i = find(dbl, i + 1)

            if sgl in body:
                i = find(sgl, 0)
                while i != -1:
                    if ml_states and ml_states[-1][2] == sgl:
                        append2(range(ml_states[0][0], idx))
                        pop()
                    else:
                        append((idx, i, sgl))
                    i = find(sgl, i + 1)

    return ranges


class MinimapEngine:
    __slots__ = ('ce')

    numerics = {*'1234567890'}
    specials = {'def ', 'class '}
    numericsdot = {*'1234567890.'}
    some_set = {'TAB', 'STRING', 'BUILTIN', 'SPECIAL'}
    whitespace = {'\x0b', '\r', '\x0c', '\t', '\n', ' '}
    some_set2 = {'COMMENT', 'PREPRO', 'STRING', 'NUMBER'}
    builtins = {'return', 'break', 'continue', 'yield', 'with', 'is '
                'while', 'for ', 'import ', 'from ', 'not ', 'elif ',
                ' else', 'None', 'True', 'False', 'and ', 'in ', 'if '}

    def __init__(self, ce):
        self.ce = ce

    def close_block(self, idx, indent, blankl, spec, dspecial):
        remove = spec.remove
        val = idx - blankl
        for entry in spec:
            if entry[0] < idx and entry[1] >= indent:
                dspecial[entry[0]].append((entry[1], entry[2], val))
                remove(entry)

    def highlight(self, tidx):
        # t = perf_counter()
        texts = bpy.data.texts
        if not texts:  # abort if requested during undo/redo
            return

        ce = self.ce

        if ce.word_wrap:
            ml_states = []
            text = ce.wrap_text
            is_wrap = True
        else:
            text = texts[tidx]
            ml_states = get_ml_states(text)
            is_wrap = False

        olines = texts[tidx].lines
        start, end = ce.mmvisl  # visible portion of minimap
        # get, or make a proxy version of the text
        c_hash, c_data, special_temp, c_indents = ce_manager.get_cached(ce)

        dspecial = c_data['special']    # special keywords (class, def)
        dplain = c_data['plain']        # plain text
        dnumbers = c_data['numbers']    # ints and floats
        dstrings = c_data['strings']    # strings
        dbuiltin = c_data['builtin']    # builtin
        dcomments = c_data['comments']  # comments
        dprepro = c_data['prepro']      # pre-processor (decorators)
        dtabs = c_data['tabs']          # ?????
        indents = c_indents             # indentation levels

        # syntax element structure
        elem = [0,  # line id
                0,  # element start position
                0,  # element end position
                0]  # special block end line

        # this is used a lot for ending plain text segment
        def close_plain(elem, cidx):
            """Ends non-highlighted text segment"""
            if elem[1] < cidx:
                elem[2] = cidx - 1
                dplain[elem[0]].append(elem[1:3])
            elem[1] = cidx

        # this ends collapsible code block
        close_block = self.close_block
        # recognized tags definitions, only the most used
        numerics = self.numerics
        numericsdot = self.numericsdot
        some_set = self.some_set
        some_set2 = self.some_set2
        ws = self.whitespace
        blankl = idx = 0
        # flags of syntax state machine
        state = ""
        timer = -1      # timer to skip characters and close segment at t=0
        builtin_set = "rbcywfieNTFan"
        builtins = self.builtins
        specials = self.specials
        special_temp.clear()
        tab_width = ce.st.tab_width

        def is_ml_state(idx):
            for r in ml_states:
                if idx in r:
                    return True

        def look_back(idx):
            prev = idx - 1
            lines = text.lines
            while prev > 0:
                bod = lines[prev].body
                blstrip = bod.lstrip()
                lenbprev = len(bod)
                indprev = (lenbprev - len(blstrip)) // tab_width
                if indprev:
                    bstartsw = blstrip.startswith
                    if bstartsw("def"):
                        indprev += 1
                    elif bstartsw("return"):
                        indprev -= 1
                    return indprev
                elif blstrip:
                    return 0
                prev -= 1
            return 0

        for idx, line in enumerate(text.lines[start:end], start):
            bod = line.body
            hsh = hash(bod)

            if hsh == c_hash[idx]:  # use cached data instead
                continue

            c_hash[idx] = hsh

            for i in (dspecial, dplain, dnumbers,  # TODO wrap into a function
                      dstrings, dbuiltin, dcomments, dprepro):
                i[idx].clear()

            # XXX tentative hack
            lenbstrip = len(bod.replace("#", " ").lstrip())
            lenb = len(bod)
            ind = (lenb - lenbstrip) // tab_width

            if not lenbstrip:  # track hanging indents by look-back
                ind = look_back(idx)
            indents[idx] = ind

            elem[0] = idx  # new line new element, carry string flag
            elem[1] = 0

            is_sub = is_wrap and line.is_sub
            is_comment = is_sub and olines[line.oidx].body.startswith("#")
            if state != 'STRING' or is_sub and is_comment:
                if not is_sub:
                    state = ""
            _is_ml_state = is_ml_state(idx)

            if _is_ml_state:
                state = "STRING"
            else:
                state = ""
            indent = 0
            block_close = has_non_ws = any(c not in ws for c in bod)
            enumbod = [*enumerate(bod)]
            # process each line and break into syntax blocks
            for cidx, c in enumbod:
                bodsub = bod[cidx:]
                start_tab = "    " in bodsub[:4]
                if timer > 0:
                    timer -= 1
                elif timer < 0:
                    if not state:
                        # tabs
                        if start_tab:
                            close_plain(elem, cidx)
                            state = 'TAB'
                            timer = 3
                            indent += 4
                        # built-in
                        if not state and c in builtin_set:
                            bodsub = bod[cidx:]
                            for b in builtins:
                                if b in bodsub[:len(b)]:
                                    close_plain(elem, cidx)
                                    state = 'BUILTIN'
                                    timer = len(b) - 1
                                    break
                        # special (def, class)
                        if not state and c in "dc":
                            bodsub = bod[cidx:]
                            for b in specials:
                                if b in bodsub[:len(b)]:
                                    close_plain(elem, cidx)
                                    state = 'SPECIAL'
                                    timer = len(b) - 1
                                    break
                        # numbers
                        elif c in numerics:
                            close_plain(elem, cidx)
                            state = 'NUMBER'
                        # "" string
                        elif c in '\"\'' and not is_sub:
                            if not _is_ml_state:
                                close_plain(elem, cidx)
                                state = 'STRING'
                        # comment
                        elif c == '#':
                            close_plain(elem, cidx)
                            state = 'COMMENT'
                            # close code blocks
                            if block_close:
                                for i, j in enumbod:
                                    if i > 0 and j != " ":
                                        close_block(idx, i // 4 * 4, blankl,
                                                    special_temp, dspecial)
                            break
                        # preprocessor
                        elif c == '@':
                            close_plain(elem, cidx)
                            state = 'PREPRO'
                            # close code blocks
                            if block_close:
                                close_block(idx, indent, blankl,
                                            special_temp, dspecial)
                            break
                    elif state == 'NUMBER' and c not in numericsdot:
                        elem[2] = cidx
                        dnumbers[idx].append(elem[1:3])
                        elem[1] = cidx
                        state = ""
                    elif state == 'STRING':
                        if is_sub and is_comment:
                            state = ""
                        else:
                            if start_tab:
                                elem[1] = cidx + 4
                                indent += 4
                # close special blocks
                if state != 'TAB' and block_close:
                    block_close = False
                    close_block(idx, indent, blankl, special_temp, dspecial)
                # write element when timer 0
                if timer == 0:
                    elem[2] = cidx
                    if state in some_set:
                        if state == 'TAB':
                            dtabs[idx].append(elem[1:3])
                        if state == 'STRING':
                            dstrings[idx].append(elem[1:3])
                        elif state == 'BUILTIN':
                            dbuiltin[idx].append(elem[1:3])
                        elif state == 'SPECIAL':
                            special_temp.append(elem.copy())
                            # special_temp.append(elem[:])
                        elem[1] = cidx + 1
                    state = ""
                    timer = -1
            # count empty lines
            blankl = 0 if has_non_ws else blankl + 1

            # handle line ends - aka when a syntax continues over
            # multiple lines like multi-line strings etc.
            if not state:
                elem[2] = lenb
                dplain[idx].append(elem[1:3])
            elif state in some_set2:
                elem[2] = lenb
                elems = elem[1:3]
                if state == 'COMMENT':
                    dcomments[idx].append(elems)
                elif state == 'PREPRO':
                    dprepro[idx].append(elems)
                elif state == 'STRING':
                    dstrings[idx].append(elems)
                elif state == 'NUMBER':
                    dnumbers[idx].append(elems)

        # close all remaining blocks
        val = idx + 1 - blankl
        for entry in special_temp:
            dspecial[entry[0]].append([entry[1], entry[2], val])

        # done
        output = ce.segments
        output[0]['elements'] = dplain
        output[1]['elements'] = dstrings
        output[2]['elements'] = dcomments
        output[3]['elements'] = dnumbers
        output[4]['elements'] = dbuiltin
        output[5]['elements'] = dprepro
        output[6]['elements'] = dspecial  # XXX needs fixing
        # output[7]['elements'] = dtabs
        ce.indents = indents
        # t2 = perf_counter()
        # print("draw:", round((t2 - t) * 1000, 2), "ms")
        ce.tag_redraw()


def get_cw(st):
    cw = xoffs = 0
    for idx, line in enumerate(st.text.lines):
        if line.body:
            loc = st.region_location_from_cursor
            xoffs = loc(idx, 0)[0]
            cw = loc(idx, 1)[0] - xoffs
            break
    if not cw:
        xoffs = get_widget_unit(bpy.context) // 2
        cw = round(blf.dimensions(1, "T")[0])
    return cw, xoffs

# =====================================================
#                    OPENGL DRAWCALS
# =====================================================


def draw_callback_px(context):
    """Draws Code Editors Minimap and indentation marks"""
    # t = perf_counter()
    text = context.edit_text
    if not text:
        return

    st = context.space_data
    ce = get_ce(context)
    word_wrap = ce.word_wrap = st.show_word_wrap

    if ce.text_name != text.name:  # refer by name to avoid invalid refs
        ce.text_name = text.name

    wu = get_widget_unit(context)  # get the correct ui scale
    wu2 = wu * 0.05
    rw, rh = ce.region.width, ce.region.height
    visl = st.visible_lines
    lines = text.lines
    lenl = len(lines)
    lnrs = st.show_line_numbers and len(repr(lenl)) + 2
    cw, xoffs = get_cw(st)

    # Main text drawing x offset from area edge
    _x = cw
    if st.show_line_numbers:
        _x += cw * lnrs

    mcw = ce.mmcw * round(wu2, 1)  # minimap char width
    maxw = 120 * wu2
    redge = ce.redge = 1 + int(int(rw - (0.2 * wu)) - (0.4 * wu))

    # use different cache for wrapped. less performant, but still cached
    if word_wrap:
        ce.cmax = cmax = (rw - wu - _x) // cw
        mmw = min((mcw * 0.8 * (redge // cw), maxw))
        text, lines = ce.validate()
        lenl = len(lines)

        # do a new pass since max char width changed
        if cmax != ce.cmax_prev:
            ce.cmax_prev = cmax
            return draw_callback_px(context)

    else:
        mmw = min((rw // 7, maxw))
        if st.top > lenl:  # clamp top to avoid going completely off-screen
            st.top = lenl - (visl // 2)

    if not ce.autow:
        mmw = ce.mmw

    ledge = ce.ledge = int(redge - mmw) if ce.show_minimap else redge
    ce.prev_state = word_wrap
    sttop = st.top
    sttopvisl = sttop + visl
    texts = bpy.data.texts
    lent = len(texts)

    lh = int((wu * st.font_size // 20) * 1.3)  # line height
    mlh = ce.mlh = ce.mlh_base * round(wu * 0.1, 1)   # minimap line height
    tabsize = ce.large_tabs and int(wu * 1.1) or int(wu * 0.8)
    tabw = ce.tabw = ce.show_tabs and lent > 1 and tabsize or 0
    lbound = ledge - tabw if ce.show_tabs and texts else ledge
    slide = ce.slide = int(max(0, mlh * (lenl + rh / lh) - rh) * sttop / lenl)
    mmy1 = rh - mlh * sttop + slide - 1

    startrange = round((sttop - (rh - mmy1) // mlh))
    endrange = round(startrange + (rh // mlh))
    ce.opac = opac = min(max(0, (rw - ce.min_width) / 100.0), 1)

    # rebuild minimap visual range
    mmvisrange = range(*ce.mmvisl)
    if startrange not in mmvisrange or endrange not in mmvisrange:
        ce.mmvisl = startrange, endrange

    # params are ready, get minimap symbols
    ce.update_text()

    # draw minimap background rectangle
    x = ledge - tabw
    color = (*ce.background, (1 - ce.bg_opacity) * opac)
    bgl.glEnable(bgl.GL_BLEND)
    draw_quads_2d(((x, rh), (redge, rh), (redge, 0), (x, 0)), color)

    mmap_enabled = all((opac, ce.show_minimap))
    # draw minimap shadow
    bgl.glLineWidth(wu2)
    if mmap_enabled or tabw:
        for idx, intensity in enumerate([.2, .1, .07, .05, .03, .02, .01]):
            color = 0.0, 0.0, 0.0, intensity * opac
            draw_lines_2d(((x - idx, 0), (x - idx, rh)), color)

    # draw minimap/tab divider
    if tabw:
        color = 0.0, 0.0, 0.0, 0.2 * opac
        draw_lines_2d(((ledge, 0), (ledge, rh)), color)

    mmtop = int(slide / mlh)
    mmbot = int((rh + slide) / mlh)

    if mmap_enabled:
        # draw minimap slider
        alpha = 0.05 if ce.in_minimap else 0.03
        color = 1.0, 1.0, 1.0, alpha * opac
        color_frame = 1.0, 1.0, 1.0, alpha + 0.1
        mmy2 = rh - mlh * sttopvisl + slide
        x1, x2 = ledge + 1, redge - 1
        y1, y2 = mmy1, mmy2
        p1, p2, p3, p4 = (x1, y1), (x2, y1), (x2, y2), (x1, y2)
        draw_quads_2d((p1, p2, p3, p4), color)

        # draw slider frame
        bgl.glLineWidth(wu2)
        draw_lines_2d((p1, p2), color_frame)
        draw_lines_2d((p2, p3), color_frame)
        draw_lines_2d((p3, p4), color_frame)
        draw_lines_2d((p4, p1), color_frame)

        # draw minimap symbols
        segments = ce.segments
        mmxoffs = ledge + 4  # minimap x offset
        bgl.glLineWidth((mlh ** 1.02) - 2)  # scale blocks with line height
        for seg in segments:
            seq = deque()
            seq_extend = seq.extend
            color = seg['col'][:3] + (0.4 * opac,)
            for idx, elem in enumerate(seg['elements'][mmtop:mmbot]):
                if elem:
                    y = rh - (mlh * (idx + mmtop + 1) - slide)
                    for start, end, *_ in elem:
                        x1 = mmxoffs + (mcw * start)
                        if x1 > redge:
                            continue

                        x2 = x1 + (mcw * (end - start))
                        if x2 > redge:
                            x2 = redge

                        seq_extend(((x1, y), (x2, y)))
            draw_lines_2d(seq, color)

    # draw minimap indent guides
    seq1, seq2 = deque(), deque()
    seq1_ext, seq2_ext = seq1.extend, seq2.extend
    plain_col = ce.segments[0]['col'][:3]
    color1 = (*plain_col, 0.1)
    color2 = (*plain_col, 0.3 * ce.indent_trans * opac)
    tab_width = st.tab_width
    indent = cw * tab_width
    show_indents = ce.show_indents
    for idx, levels in enumerate(ce.indents[mmtop:mmbot], mmtop):
        if levels:
            for level in range(levels):
                if mmap_enabled:
                    x = ledge + 4 + (mcw * 4 * level)
                    if x < redge:
                        ymax = rh + slide - mlh * idx
                        seq1_ext(((x, ymax - mlh), (x, ymax)))

                # draw editor indent guides
                if show_indents:
                    ymax = rh - lh * (1 + idx - sttop) + lh
                    ymin = ymax - lh
                    bgl.glLineWidth(wu2)
                    if -lh < ymin < rh:
                        x = xoffs + indent * level
                        if x >= _x:
                            seq2_ext(((x, ymin), (x, ymax)))
                            continue
    draw_lines_2d(seq1, color1)
    draw_lines_2d(seq2, color2)
    # draw tabs
    if tabw:
        tabh = rh / lent
        fsize = int(tabw * 0.75)
        blf.size(0, fsize, 72)
        blf.enable(0, blf.ROTATION)
        blf.rotation(0, 1.5707963267948966)
        x = int(ledge - tabw / 4)
        yoffs = rh - (tabh / 2)
        maxlenn = int(((tabh * 1.2) / (fsize * 0.7)) - 2)
        # text names
        tnames = [t.name for t in texts]
        for idx, name in enumerate(tnames):
            lenn = len(name)
            tlabel = lenn <= maxlenn and name or name[:maxlenn] + '..'

            y = round(yoffs - (tabh * idx) - blf.dimensions(0, tlabel)[0] // 2)
            blf.color(0, *plain_col, (name != text.name and .4 or .7) * opac)
            blf.position(0, x, y, 0)
            blf.draw(0, tlabel)

        bgl.glEnable(bgl.GL_BLEND)
        bgl.glLineWidth(wu2)
        # draw tab hover rects
        if opac:
            x, y = ledge - tabw, rh
            hover_text = ce.hover_text
            for name in tnames:
                y2 = y - tabh
                color2 = 0, 0, 0, .2 * opac
                # tab selection
                seq = (x, y), (ledge, y), (ledge, y2), (x, y - tabh)
                if hover_text == name:
                    draw_quads_2d(seq, (1, 1, 1, 0.1))
                # tab active
                elif name == text.name:
                    ce.active_tab_ymax = y
                    draw_quads_2d(seq, color1)
                y -= tabh
                draw_lines_2d(((x, y), (ledge, y)), color2)

    # draw whitespace and/or tab characters
    if ce.show_whitespace:
        st_left = (_x // cw) - (xoffs // cw)
        cend = (lbound - _x) // cw

        wslines = []
        append = wslines.append
        join = "".join
        for l in lines[sttop:sttopvisl]:
            ti = 0
            wsbod = []
            append2 = wsbod.append
            for ci, c in enumerate(l.body):
                if ci < st_left:
                    append2(" ")
                    continue
                if c is "\t":
                    tb = tab_width - ((ci + ti) % tab_width) - 1
                    append2(" " * tb + "→")
                    ti += tb
                elif c is " ":
                    append2("·")
                else:
                    append2(" ")
            append(join(wsbod))

        y = rh - (lh * 0.8)
        blf.color(1, *plain_col, 1 * ce.ws_alpha)
        for idx, line in enumerate(wslines):
            if line:
                blf.position(1, _x, y, 0)
                blf.draw(1, line[st_left:cend])
            y -= lh

    # restore opengl defaults
    bgl.glLineWidth(1.0)
    bgl.glDisable(bgl.GL_BLEND)
    blf.rotation(0, 0)
    blf.disable(0, blf.ROTATION)
    # t2 = perf_counter()
    # print("draw:", round((t2 - t) * 1000, 2), "ms")


class CodeEditorBase:
    bl_options = {'INTERNAL'}
    @classmethod
    def poll(cls, context):
        return getattr(context, "edit_text", False)


class CE_OT_scroll(CodeEditorBase, Operator):
    bl_idname = 'ce.scroll'
    bl_label = "Scroll"
    bl_options = {'INTERNAL', 'BLOCKING'}

    def modal(self, context, event):
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            context.window_manager.event_timer_remove(self.timer)
            return {'FINISHED'}
        elif event.type == 'TIMER':
            return self.scroll_timer(context, event)
        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        st = context.space_data
        self.ce = ce = get_ce(context)
        self.lenl = len(ce.word_wrap and ce.wrap_text.lines or st.text.lines)

        context.window.cursor_set('HAND')
        wm = context.window_manager
        wm.modal_handler_add(self)
        self.timer = wm.event_timer_add(.0075, window=context.window)
        return self.scroll_timer(context, event)

    def scroll_timer(self, context, event):
        st = context.space_data
        top = st.top
        vishalf = st.visible_lines // 2
        mry = event.mouse_region_y
        mlh = self.ce.mlh
        lenl = self.lenl
        center = context.region.height - mlh * (top + vishalf)  # box center
        nlines = round(0.3 * (center + self.ce.slide - mry) / mlh)
        if nlines > 0 and top + nlines > lenl - vishalf:
            val = lenl - vishalf
        else:
            val = top + round(((30 + (lenl / mlh)) / 60) * nlines)

        if val != st.top and not (val < 0 and not st.top):
            st.top = val
        return {'RUNNING_MODAL'}


# hijack clicks inside tab zones and minimap, otherwise pass through
class CE_OT_cursor_set(CodeEditorBase, Operator):
    bl_idname = "ce.cursor_set"
    bl_label = "Set Cursor"
    options = {'INTERNAL', 'BLOCKING'}

    def modal(self, context, event):
        if event.value == 'RELEASE':
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        ce = get_ce(context)
        if ce:
            if ce.in_minimap:
                return bpy.ops.ce.scroll('INVOKE_DEFAULT')
            elif ce.hover_text and ce.hover_text in bpy.data.texts:
                context.space_data.text = bpy.data.texts.get(ce.hover_text)
                context.window_manager.modal_handler_add(self)
                return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}


# handle mouse events in text editor to support hover and scroll
class CE_OT_mouse_move(CodeEditorBase, Operator):
    bl_idname = "ce.mouse_move"
    bl_label = "Mouse Move"

    @classmethod
    def poll(cls, context):
        if getattr(context, 'edit_text', False):
            ce = get_ce(context)
            event = WM_OT_event_catcher(ce.window)
            if event:
                ce.update(context, event)


# catch the event so it can be accessed outside of operators
class WM_OT_event_catcher(bpy.types.Operator):
    bl_idname = "wm.event_catcher"
    bl_label = "Event Catcher"
    bl_options = {'INTERNAL'}

    import _bpy  # use call instead of bpy.ops to reduce overhead
    call = _bpy.ops.call
    del _bpy

    def __new__(cls, window):
        timer(cls.call, cls.__name__, {'window': window}, {}, 'INVOKE_DEFAULT')
        return getattr(cls, 'event', None)

    def invoke(self, context, event):
        __class__.event = event
        return {'CANCELLED'}


# main class for storing runtime draw props
class CodeEditorMain:
    __slots__ = ('__dict__',)

    def __init__(self, context):
        self.id = f"ce_{context.area.as_pointer()}"
        index = f"{context.screen.areas[:].index(context.area)}"
        if index not in context.screen.code_editors:
            context.screen.code_editors.add().name = index
        self.props = context.screen.code_editors[index]

        p = context.preferences
        self.ap = ap = p.addons[__name__].preferences
        self.text = text = context.edit_text
        self.bg_opacity = ap.opacity
        self.mmw = ap.minimap_width
        self.min_width = ap.window_min_width
        self.mmcw = ap.character_width
        self.mlh_base = self.mlh = ap.line_height
        self.indent_trans = ap.indent_trans
        self.ws_alpha = ap.ws_alpha
        self.large_tabs = ap.large_tabs
        self.tabs_right = ap.tabs_right

        self.show_whitespace = self.props.show_whitespace
        self.show_minimap = self.props.show_minimap
        self.show_indents = self.props.show_indents
        self.show_tabs = self.props.show_tabs
        self.region = context.area.regions[-1]
        self.window = context.window
        self.st = st = context.space_data
        self.word_wrap = st.show_word_wrap
        self.prev_state = self.word_wrap
        self.in_minimap = False
        self.autow = True
        wu = get_widget_unit(context)
        lnrs = st.show_line_numbers and len(repr(len(text.lines)))
        cw = get_cw(st)[0]
        rw = self.region.width
        self.opac = min(max(0, (rw - self.min_width) * .01), 1)
        if self.show_minimap:
            self.ledge = rw - round(self.mmw * (wu * 0.025))
        self.redge = rw - wu // 5 * 3
        self.active_tab_ymax = self.ledge = self.tabw = 0
        self.in_tab = self.hover_text = self.hover_prev = self.indents = None
        self.text_name = self.text.name
        self.cmax = (rw - wu - ((wu // 2) + (cw * lnrs))) // cw
        self.cmax_prev = self.cmax
        self.wrap_text = WrapText(self.text, self) if self.word_wrap else None
        self.mmvisl = 0, 1
        # syntax theme colors
        current_theme = p.themes.items()[0][0]
        tex_ed = p.themes[current_theme].text_editor
        self.background = tex_ed.space.back.owner
        items = (tex_ed.space.text, tex_ed.syntax_string,
                 tex_ed.syntax_comment, tex_ed.syntax_numbers,
                 tex_ed.syntax_builtin, tex_ed.syntax_preprocessor,
                 tex_ed.syntax_special, (1, 0, 0))

        self.segments = [{'elements': [], 'col': i} for i in items]
        self.tag_redraw = context.area.tag_redraw
        self.highlight = MinimapEngine(self).highlight

    def indexof(self, text):
        texts = bpy.data.texts
        return next((i for i, t in enumerate(texts) if t == text), -1)

    # refresh the highlights
    def update_text(self):
        text = self.st.text
        self.text_name = text.name
        self.highlight(self.indexof(text))

    # ensure the reference is always valid. dangerous otherwise
    def validate(self):
        if self.text_name != self.st.text.name:
            self.text_name = self.st.text.name
        text = self.text = bpy.data.texts.get(self.text_name)
        wtext = self.wrap_text
        if not self.prev_state or wtext.name != text.name:
            wtext = self.wrap_text = WrapText(text, self)

        wtext.check_hash()
        return text, wtext.lines

    # (hover highlight, minimap refresh, tab activation, text change)
    def update(self, context, event):
        self.validate()
        texts = bpy.data.texts
        hover_text = ""
        ledge = self.ledge
        tab_xmin = ledge - self.tabw
        redraw = False
        mrx = event.mouse_x - context.region.x
        mry = event.mouse_y - context.region.y
        lbound = tab_xmin if self.show_tabs and texts else ledge
        in_minimap = ledge <= mrx < self.redge and self.opac
        in_ttab = tab_xmin <= mrx < ledge and self.opac

        if context.edit_text.name != self.text_name:
            self.update_text()

        if lbound <= mrx:
            context.window.cursor_set('DEFAULT')

        if in_minimap != self.in_minimap:
            self.in_minimap = in_minimap
            redraw = True

        elif in_ttab:
            rh = self.region.height
            tabh = min(200, int(rh / len(texts)))
            prev = 0
            for i in range(1, len(texts) + 1):
                if mry in range(rh - (tabh * i), rh - prev):
                    hover_text = texts[i - 1].name
                    break
                prev += tabh
        if hover_text != self.hover_text:
            self.hover_text = hover_text
            redraw = True
        if redraw:
            self.tag_redraw()
        return {'CANCELLED'}  # prevent view layer update


def update_prefs(self, context):
    propsdict = {
        'minimap_width': 'mmw',
        'character_width': 'mmcw',
        'line_height': 'mlh_base',
        'indent_trans': 'indent_trans',
        'opacity': 'bg_opacity',
        'window_min_width': 'min_width',
        'ws_alpha': 'ws_alpha',
        'auto_width': 'autow',
        'large_tabs': 'large_tabs',
        'tabs_right': 'tabs_right'}
    for editor in ce_manager.editors:
        for approp, edprop in propsdict.items():
            setattr(editor, edprop, getattr(self, approp))


def timer(func, *args, delay=0, init=False):
    if init:
        func(*args)
        return
    bpy.app.timers.register(lambda: timer(func, *args, init=True),
                            first_interval=delay)


class CE_PT_settings_panel(bpy.types.Panel):  # display settings in header
    bl_idname = 'CE_PT_settings'
    bl_space_type = 'TEXT_EDITOR'
    bl_region_type = 'WINDOW'
    bl_label = "Code Editor"
    bl_ui_units_x = 8

    def draw(self, context):
        if getattr(context, 'edit_text', None):
            ce_props = get_ce(context).props
            layout = self.layout
            layout.prop(ce_props, "show_minimap")
            layout.prop(ce_props, "show_tabs")
            layout.prop(ce_props, "show_indents")
            layout.prop(ce_props, "show_whitespace")
            layout.operator(
                "preferences.addon_show", text="Open Settings"
            ).module = __name__


class CodeEditorPrefs(bpy.types.AddonPreferences):
    """Code Editors Preferences Panel"""
    bl_idname = __name__

    opacity: bpy.props.FloatProperty(
        name="Background", min=0.0, max=1.0, default=0.2, update=update_prefs
    )
    ws_alpha: bpy.props.FloatProperty(
        name="Whitespace Alpha", min=0.0, max=1.0, default=0.2,
        update=update_prefs
    )
    auto_width: bpy.props.BoolProperty(
        name="Auto Width", description="Automatically scale minimap width "
        "based on region width", default=1, update=update_prefs
    )
    minimap_width: bpy.props.IntProperty(
        name="Minimap Width", description="Minimap base width in px",
        min=0, max=400, default=225, update=update_prefs
    )
    window_min_width: bpy.props.IntProperty(
        name="Fade Threshold", description="Region width (px) threshold for "
        "fading out panel", min=0, max=4096, default=250, update=update_prefs
    )
    character_width: bpy.props.FloatProperty(
        name="Character Width", description="Minimap character "
        "width in px", min=0.1, max=4.0, default=1.0, update=update_prefs
    )
    line_height: bpy.props.FloatProperty(
        name="Line Height", description="Minimap line height in "
        "pixels", min=0.5, max=4.0, default=1.0, update=update_prefs
    )
    indent_trans: bpy.props.FloatProperty(
        name="Indent Guides", description="0 - fully opaque, 1 - fully "
        "transparent", min=0.0, max=1.0, default=0.3, update=update_prefs
    )
    large_tabs: bpy.props.BoolProperty(
        name="Bigger Tabs", description="Increase tab size for bigger "
        "monitors", update=update_prefs
    )
    tabs_right: bpy.props.BoolProperty(
        name="Tabs Right Side", description="Place text tabs to the right of"
        "minimap", update=update_prefs
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.scale_y = 1.1
        row = layout.row()
        col = row.column()

        flow = col.grid_flow(columns=2, even_columns=1)
        flow.prop(self, "large_tabs")
        flow = col.grid_flow(columns=2, even_columns=1)
        if not self.auto_width:
            flow.prop(self, "minimap_width", slider=True)
        flow.prop(self, "auto_width")
        flow = col.grid_flow(columns=2, even_columns=1)
        flow.prop(self, "opacity", slider=True)
        flow.prop(self, "character_width")
        flow.prop(self, "line_height")

        flow.prop(self, "ws_alpha", slider=True)
        flow.prop(self, "indent_trans", slider=True)
        flow.prop(self, "window_min_width")
        row.separator()

        layout.separator()

    def add_to_header(self, context):
        layout = self.layout
        layout.popover_group(
            "TEXT_EDITOR",
            region_type="WINDOW",
            context="",
            category="")


def set_draw(state=True):
    from bpy_restrict_state import _RestrictContext
    st = bpy.types.SpaceTextEditor

    if state:
        if isinstance(bpy.context, _RestrictContext):  # delay until freed
            return timer(set_draw, delay=1e-3)
        set_draw._handle = st.draw_handler_add(
            draw_callback_px, (bpy.context,), 'WINDOW', 'POST_PIXEL')
    else:
        st.draw_handler_remove(set_draw._handle, 'WINDOW')
        del set_draw._handle

    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == 'TEXT_EDITOR':
                a.tag_redraw()


class CE_PG_settings(bpy.types.PropertyGroup):
    from bpy.props import BoolProperty

    show_minimap: BoolProperty(
        name="Minimap",
        default=1,
        update=lambda self, context: setattr(
            get_ce(context), 'show_minimap', self.show_minimap)
    )
    show_indents: BoolProperty(
        name="Indent Guides",
        default=1,
        update=lambda self, context: setattr(
            get_ce(context), 'show_indents', self.show_indents)
    )
    show_whitespace: BoolProperty(
        name="Whitespace",
        default=0,
        update=lambda self, context: setattr(
            get_ce(context), 'show_whitespace', self.show_whitespace)
    )
    show_tabs: BoolProperty(
        name="Tabs",
        default=1,
        update=lambda self, context: setattr(
            get_ce(context), 'show_tabs', self.show_tabs)
    )
    del BoolProperty


classes = (
    CodeEditorPrefs,
    CE_OT_mouse_move,
    CE_OT_cursor_set,
    CE_OT_scroll,
    CE_PT_settings_panel,
    WM_OT_event_catcher,
    CE_PG_settings
)


def register():
    from bpy.types import Screen, TEXT_HT_header
    from bpy.utils import register_class

    for cls in classes:
        register_class(cls)

    Screen.code_editors = bpy.props.CollectionProperty(type=CE_PG_settings)
    TEXT_HT_header.append(CodeEditorPrefs.add_to_header)

    kc = bpy.context.window_manager.keyconfigs.addon.keymaps
    km = kc.get('Text', kc.new('Text', space_type='TEXT_EDITOR'))
    new = km.keymap_items.new
    kmi1 = new('ce.mouse_move', 'MOUSEMOVE', 'ANY', head=True)
    kmi2 = new('ce.cursor_set', 'LEFTMOUSE', 'PRESS', head=True)

    register.keymaps = ((km, kmi1), (km, kmi2))
    set_draw(getattr(bpy, "context"))

    import addon_utils
    mod = addon_utils.addons_fake_modules.get(__name__)
    if mod:
        addon_utils.module_bl_info(mod)["show_expanded"] = True


def unregister():
    bpy.types.TEXT_HT_header.remove(CodeEditorPrefs.add_to_header)
    set_draw(state=False)

    for km, kmi in register.keymaps:
        km.keymap_items.remove(kmi)
    del register.keymaps

    ce_manager.nuke()

    for w in bpy.context.window_manager.windows:
        w.screen.code_editors.clear()
    del bpy.types.Screen.code_editors

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
