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
    "location": "Text Editor > Righ Click Menu",
    "version": (0, 1, 0),
    "blender": (2, 81, 0),
    "description": "Better editor for coding",
    "author": "Jerryno, tintwotin, kaio",
    "category": "Text Editor",
}

# =====================================================
#                      CODE EDITTING
# =====================================================
sh_2d = from_builtin('2D_UNIFORM_COLOR')
sh_2d_uniform_float = sh_2d.uniform_float
sh_2d_bind = sh_2d.bind

bgl_glLineWidth = bgl.glLineWidth
bgl_glDisable = bgl.glDisable
bgl_glEnable = bgl.glEnable
bgl_GL_BLEND = bgl.GL_BLEND

blf_position = blf.position
blf_color = blf.color
blf_rotation = blf.rotation
blf_ROTATION = blf.ROTATION
blf_disable = blf.disable
blf_enable = blf.enable
blf_draw = blf.draw
blf_size = blf.size


# emulate list of integers with slicing
# capability. use with tracking indents
class DefaultInt(defaultdict):
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
    class WrapTextLine:
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

    @property
    def otext(self):
        return bpy.data.texts.get(self.ce.text_name)

    def check_hash(self):
        otext = self.otext
        if not otext:  # original text has been renamed or removed
            return
        lines = otext.lines
        hashes = self.hashes
        lenl = len(lines)
        lenh = len(hashes)
        if lenl > lenh:
            hashes.extend((0,) * (lenl - lenh))
        elif lenh > lenl:
            del hashes[lenl:]
        elif self.ce.cmax != self.cmax:
            self.cmax = self.ce.cmax
            *self.hashes, = (0,) * lenl
        idx = 0
        for line, hash_val in zip(lines, hashes):
            if hash(line.body) != hash_val:
                return self.rebuild_lines(from_line=idx)
            idx += 1

    def rebuild_lines(self, from_line=0):
        otext = self.otext
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
    editors = []
    tcache = TextCache()

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

    def get_handle(self, context):
        handle_id = f"ce_{context.area.as_pointer()}"
        handle = self.get(handle_id)

        if not handle:
            self.gcollect(context)  # remove closed editors
            self[handle_id] = CodeEditorMain(context)
            self.editors.append(self[handle_id])
            return self[handle_id]
        return handle


ce_manager = CodeEditorManager()
get_handle = ce_manager.get_handle


def draw_lines_2d(seq, color):
    batch = batch_for_shader(sh_2d, 'LINES', {'pos': seq})
    sh_2d_bind()
    sh_2d_uniform_float("color", [*color])
    batch.draw(sh_2d)


def draw_quads_2d(seq, color):
    qseq, = [[x1, y1, y2, x1, y2, x2] for (x1, y1, y2, x2) in (seq,)]
    batch = batch_for_shader(sh_2d, 'TRIS', {'pos': qseq})
    sh_2d_bind()
    sh_2d_uniform_float("color", [*color])
    batch.draw(sh_2d)


def get_editor_xoffset(st):
    loc = st.region_location_from_cursor
    for idx, line in enumerate(st.text.lines):
        if len(line.body) > 1:
            xstart = loc(idx, 0)[0]
            return loc(idx, 1)[0] - xstart, xstart
    return 0, 0


def get_maxy(st):
    loc = st.region_location_from_cursor
    return loc(0, 0)[1]


# source/blender/windowmanager/intern/wm_window.c$515
def get_widget_unit(context):
    system = context.preferences.system
    p = system.pixel_size
    pd = p * system.dpi
    return int((pd * 20 + 36) / 72 + (2 * (p - pd // 72)))


class MinimapEngine:
    def __init__(self, ce):
        self.ce = ce
        self.numerics = {*'1234567890'}
        self.numericsdot = {*'1234567890.'}
        self.builtins = {
            'return', 'break', 'continue', 'yield', 'with', 'is '
            'while', 'for ', 'import ', 'from ', 'not ', 'elif ',
            ' else', 'None', 'True', 'False', 'and ', 'in ', 'if '}
        self.ws = {'\x0b', '\r', '\x0c', '\t', '\n', ' '}
        self.some_set = {'TAB', 'STRING', 'BUILTIN', 'SPECIAL'}
        self.some_set2 = {'COMMENT', 'PREPRO', 'STRING', 'NUMBER'}
        self._data = bpy.data
        self.specials = {'def ', 'class '}

    def close_block(self, idx, indent, blankl, spec, dspecial):
        remove = spec.remove
        val = idx - blankl
        for entry in spec:
            if entry[0] < idx and entry[1] >= indent:
                dspecial[entry[0]].append((entry[1], entry[2], val))
                remove(entry)

    def highlight(self, tidx):
        texts = bpy.data.texts
        if not texts:  # abort if requested during undo/redo
            return

        text = texts[tidx]
        olines = text.lines
        ce = self.ce
        start, end = ce.mmvisl  # visible portion of minimap
        is_wrap_text = False
        if ce.word_wrap:
            text = ce.wrap_text
            is_wrap_text = True

        # get, or make a proxy version of the text
        c_hash, c_data, special_temp, c_indents = ce_manager.get_cached(ce)
        # print(len(c_hash), len(text.lines), len(special_temp)))

        dspecial = c_data['special']    # special keywords (class, def)
        dplain = c_data['plain']        # plain text
        dnumbers = c_data['numbers']    # ints and floats
        dstrings = c_data['strings']    # strings
        dbuiltin = c_data['builtin']    # builtin
        dcomments = c_data['comments']  # comments
        dprepro = c_data['prepro']      # pre-processor (decorators)
        dtabs = c_data['tabs']          # ?????
        indents = c_indents             # indentation levels
        # indents = c_data['indents']    # indentation levels

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
        ws = self.ws
        blankl = idx = 0
        # flags of syntax state machine
        state = ""
        timer = -1      # timer to skip characters and close segment at t=0
        builtin_set = "rbcywfieNTFan"
        builtins = self.builtins
        specials = self.specials
        special_temp.clear()
        tab_width = ce.st.tab_width

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

            is_sub = is_wrap_text and line.is_sub
            is_comment = is_sub and olines[line.oidx].body.startswith("#")
            if state != 'STRING' or is_sub and is_comment:
                if not is_sub:
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
                            if c in "\"\'":
                                if '\\\\' not in bod[cidx - 1]:
                                    timer = 0
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


# =====================================================
#                    OPENGL DRAWCALS
# =====================================================

def get_cw(st, firstx, lines):
    loc = st.region_location_from_cursor
    for idx, line in enumerate(lines):
        if len(line.body) > 1:
            return loc(idx, 1)[0] - firstx
    return loc(idx, 1)[0]


def draw_callback_px(context):
    """Draws Code Editors Minimap and indentation marks"""
    # t = perf_counter()
    text = context.edit_text
    if not text:
        return

    st = context.space_data
    ce = get_handle(context)
    word_wrap = ce.word_wrap = st.show_word_wrap

    if ce.text_name != text.name:  # refer by name to avoid invalid refs
        ce.text_name = text.name

    wunits = get_widget_unit(context)  # get the correct ui scale
    wu1 = wunits * 0.05
    wu2 = wunits // 2

    mmw = round(ce.mmw * (wunits * 0.025))  # minimap width
    rw, rh = ce.region.width, ce.region.height
    show_minimap = ce.show_minimap
    redge = ce.redge = rw - wunits // 5 * 3  # x before scrollbar starts
    ledge = ce.ledge = rw - mmw if show_minimap else redge
    mcw = ce.mmcw * round(wu1, 1)  # minimap char width

    mlh = ce.mlh = ce.mlh_base * round(wunits * 0.1, 1)   # minimap line height
    xoffs, xstart = get_editor_xoffset(st)
    lines = text.lines
    show_lnr = st.show_line_numbers
    cw = get_cw(st, xstart, lines)  # char width
    lh = int((wunits * st.font_size // 20) * 1.3)  # line height
    lenl = len(lines)
    text_xoffset = wu2 + (show_lnr and cw * len(repr(lenl)) or 0)
    visl = st.visible_lines

    # use different cache for wrapped. less performant, but still cached
    if word_wrap:
        ce.cmax = (rw - wunits - text_xoffset) // cw
        text = ce.validate_text()
        wtext = ce.wrap_text
        if not ce.prev_state or wtext.name != text.name:
            wtext = ce.wrap_text = WrapText(text, ce)

        wtext.check_hash()
        lines = wtext.lines
        lenl = len(lines)
    else:
        if st.top > lenl:  # clamp top to avoid going completely off-screen
            st.top = lenl - (visl // 2)
    sttop = st.top
    ce.prev_state = word_wrap

    sttopvisl = sttop + visl
    texts = bpy.data.texts
    lent = len(texts)

    show_tabs = ce.show_tabs
    tabw = ce.tabw = show_tabs and lent > 1 and int(wunits * 1.2) or 0
    lbound = ledge - tabw if show_tabs and texts else ledge
    show_indents = ce.show_indents

    max_slide = max(0, mlh * (lenl + rh / lh) - rh)
    ce.slide = slide = int(max_slide * st.top / lenl)
    mapymin = rh - mlh * st.top + slide

    startrange = round((sttop - (rh - mapymin) // mlh))
    endrange = round(startrange + (rh // mlh))
    # update opacity for now
    ce.opac = opac = min(max(0, (rw - ce.min_width) / 100.0), 1)
    segments = ce.segments
    mmvisrange = range(*ce.mmvisl)

    # rebuild minimap visual range
    if startrange not in mmvisrange or endrange not in mmvisrange:
        ce.mmvisl = startrange, endrange

    ce.update_text()  # minimap update is cheap. do it every redraw
    bgl_glEnable(bgl_GL_BLEND)

    # minimap rectangle
    x = ledge - tabw
    color = (*ce.background, (1 - ce.bg_opacity) * opac)
    draw_quads_2d(((x, rh), (redge, rh), (redge, 0), (x, 0)), color)

    # minimap shadow
    bgl_glLineWidth(wu1)
    x = ledge - tabw
    for idx, intensity in enumerate([.2, .1, .07, .05, .03, .02, .01]):
        color = 0.0, 0.0, 0.0, intensity * opac
        draw_lines_2d(((x - idx, 0), (x - idx, rh)), color)
    # divider
    if tabw:
        color = 0.0, 0.0, 0.0, 0.2 * opac
        draw_lines_2d(((ledge, 0), (ledge, rh)), color)

    mmap_enabled = all((opac, show_minimap))
    mmtop = int(slide / mlh)
    mmxoffs = ledge + 4  # minimap x offset
    mmbot = int((rh + slide) / mlh)

    if mmap_enabled:
        # minimap horizontal sliding based on text block length
        # minimap hover alpha
        alpha = 0.1 if ce.in_minimap else 0.07
        color = 1.0, 1.0, 1.0, alpha * opac
        y2 = rh - mlh * sttopvisl + slide
        seq = (ledge, mapymin), (redge, mapymin), (redge, y2), (ledge, y2)
        draw_quads_2d(seq, color)

        # draw minimap code
        bgl_glLineWidth((mlh ** 1.02) - 2)  # scale blocks with line height
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

    # minimap code marks - vertical
    seq1, seq2 = deque(), deque()
    seq1_extend = seq1.extend
    seq2_extend = seq2.extend
    yoffs = rh + slide
    plain_col = segments[0]['col'][:3]
    color1 = (*plain_col, 0.1)  # minimap, static opacity
    color2 = (*plain_col, 0.3 * ce.indent_trans * opac)

    tab_width = st.tab_width
    indent = cw * tab_width
    mmapxoffs = ledge + 4  # x offset for minimap
    ind_size = int(wunits * 0.15 * 0.5)
    # draw indent guides in the minimap
    for idx, levels in enumerate(ce.indents[mmtop:mmbot], mmtop):
        if levels:
            for level in range(levels):
                if mmap_enabled:
                    x = mmapxoffs + (mcw * 4 * level)
                    ymax = yoffs - mlh * idx
                    ymin = ymax - mlh
                    seq1_extend(((x, ymin), (x, ymax)))

                # draw indent guides in the editor
                if show_indents:
                    ymax = rh - lh * (1 + idx - sttop) + lh
                    ymin = ymax - lh
                    bgl_glLineWidth(ind_size)
                    if -lh < ymin < rh:
                        x = xstart + indent * level
                        if x >= text_xoffset - 10:
                            seq2_extend(((x, ymin), (x, ymax)))
                            continue
    draw_lines_2d(seq1, color1)
    draw_lines_2d(seq2, color2)

    bgl_glLineWidth(wu1)
    # tab dividers
    if tabw:
        tabh = min(200, int(rh / lent))  # text tab height
        size = int((tabw * 0.6) / wu1)  # ratio to tab width
        blf_size(0, int(tabw * 0.6), 72)
        blf_enable(0, blf_ROTATION)
        blf_rotation(0, 1.5707963267948966)
        x = int(ledge - tabw / 3.5)
        yoffs = rh - (tabh / 2)
        maxlenn = round((tabh * 0.8) / (tabw * 0.5))

        # draw vertical tab file names
        tnames = [t.name for t in texts]
        for idx, name in enumerate(tnames):
            lenn = len(name)
            tlabel = lenn < maxlenn and name or name[:maxlenn] + '..'

            y = round(yoffs - tabh * idx - (0.5 * size * len(tlabel) / 2))
            blf_color(0, *plain_col, name != text.name and .4 or .7 * opac)
            blf_position(0, x, y, 0)
            blf_draw(0, tlabel)

        bgl_glEnable(bgl_GL_BLEND)  # not sure why it gets disabled
        # draw vertical tab rects
        if opac:
            x, y = ledge - tabw, rh
            hover_text = ce.hover_text
            for name in tnames:
                color2 = 0, 0, 0, .2 * opac
                # tab selection
                seq = (x, y), (ledge, y), (ledge, y - tabh), (x, y - tabh)
                if hover_text == name:
                    draw_quads_2d(seq, (1, 1, 1, 0.1))
                # tab active
                elif name == text.name:
                    ce.active_tab_ymax = y
                    draw_quads_2d(seq, color1)
                y -= tabh
                draw_lines_2d(((x, y), (ledge, y)), color2)

    # draw whitespace characters
    if ce.show_whitespace:
        cstart = (text_xoffset + wu2 - xstart) // cw - 1
        cend = (lbound - text_xoffset) // cw
        wsbod = ["".join("·" if c in " " else " "
                 for c in l.body[cstart:cend])
                 for l in lines[sttop:sttopvisl]]

        x = xstart + cstart * cw
        y = rh - (lh * 0.8)

        blf_color(1, *plain_col, 1 * ce.ws_alpha)
        for idx, line in enumerate(wsbod):
            if line:
                blf_position(1, x, y, 0)
                blf_draw(1, line)
            y -= lh

    # restore opengl defaults
    bgl_glLineWidth(1.0)
    bgl_glDisable(bgl_GL_BLEND)
    blf_rotation(0, 0)
    blf_disable(0, blf_ROTATION)
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
        self.ce = ce = get_handle(context)
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
        ce = get_handle(context)
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

    # return None so we don't block other keymaps
    @classmethod
    def poll(cls, context):
        if getattr(context, 'edit_text', False):
            ce = get_handle(context)
            event = WM_OT_event_catcher(ce.window)
            if event:
                ce.update(context, event)


# catch the event so it can be accessed outside of operators
class WM_OT_event_catcher(bpy.types.Operator):
    bl_idname = "wm.event_catcher"
    bl_label = "Event Catcher"
    bl_options = {'INTERNAL'}

    from functools import partial

    @staticmethod
    def catch(window):
        bpy.ops.wm.event_catcher({'window': window}, 'INVOKE_DEFAULT')

    def __new__(cls, window):
        bpy.app.timers.register(cls.partial(cls.catch, window))
        return getattr(cls, 'event', None)

    def invoke(self, context, event):
        __class__.event = event
        return {'CANCELLED'}


# main class for storing runtime draw props
class CodeEditorMain:
    def __init__(self, context):

        # user controllable in addon preferneces
        p = context.preferences
        ap = p.addons[__name__].preferences
        self.bg_opacity = ap.opacity
        self.show_tabs = ap.show_tabs
        self.mmw = ap.minimap_width
        self.min_width = ap.window_min_width
        self.mmcw = ap.character_width
        self.mlh_base = self.mlh = ap.line_height
        self.indent_trans = ap.indent_trans
        self.show_whitespace = ap.show_whitespace
        self.show_minimap = ap.show_minimap
        self.ws_alpha = ap.ws_alpha
        self.show_indents = ap.show_indents
        # init params
        self.region = context.area.regions[-1]
        self.window = context.window
        self.st = st = context.space_data
        self.word_wrap = st.show_word_wrap
        self.prev_state = self.word_wrap
        self.in_minimap = False
        wunits = get_widget_unit(context)
        rw = self.region.width
        self.opac = min(max(0, (rw - self.min_width) * .01), 1)
        if self.show_minimap:
            self.ledge = rw - round(self.mmw * (wunits * 0.025))
        self.redge = rw - wunits // 5 * 3
        self.active_tab_ymax = self.ledge = self.tabw = 0
        self.in_tab = self.hover_text = self.hover_prev = self.indents = None
        self.text = context.edit_text
        self.text_name = self.text.name
        self.cmax = 120
        self.id = f"ce_{context.area.as_pointer()}"

        self.wrap_text = None
        if self.word_wrap:
            self.wrap_text = WrapText(self.text, self)

        # get theme colors
        current_theme = p.themes.items()[0][0]
        tex_ed = p.themes[current_theme].text_editor
        self.background = tex_ed.space.back.owner
        self.mmvisl = 0, 1

        # syntax theme colors
        items = (tex_ed.space.text, tex_ed.syntax_string,
                 tex_ed.syntax_comment, tex_ed.syntax_numbers,
                 tex_ed.syntax_builtin, tex_ed.syntax_preprocessor,
                 tex_ed.syntax_special, (1, 0, 0))

        self.segments = [{'elements': [], 'col': i} for i in items]
        self.tag_redraw = context.area.tag_redraw

        # claim a highlighter
        # self.engine = MinimapEngine(self)
        self.highlight = MinimapEngine(self).highlight
        self.highlight(self.indexof(self.text))

    def indexof(self, text):
        texts = bpy.data.texts
        return next((i for i, t in enumerate(texts) if t == text), -1)

    # refresh the highlights
    def update_text(self):
        text = self.validate_text()
        self.text_name = text.name
        self.highlight(self.indexof(text))

    # ensure the reference is always valid. dangerous otherwise
    def validate_text(self):
        self.text_name = self.st.text.name
        text = self.text = bpy.data.texts.get(self.text_name)
        if not text:
            self.text_name = self.st.text.name
            return self.validate_text()
        return text

    # (hover highlight, minimap refresh, tab activation, text change)
    def update(self, context, event):
        self.validate_text()
        texts = bpy.data.texts
        hover_text = ""
        ledge = self.ledge
        opac = self.opac
        tab_xmin = ledge - self.tabw
        redraw = False
        # use window coords since we can't guarantee the
        # event object is assigned to the current region
        mrx = event.mouse_x - context.region.x
        mry = event.mouse_y - context.region.y
        lbound = tab_xmin if self.show_tabs and texts else ledge
        in_minimap = ledge <= mrx < self.redge and opac
        in_ttab = tab_xmin <= mrx < ledge and opac

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
        'show_tabs': 'show_tabs',
        'character_width': 'mmcw',
        'line_height': 'mlh_base',
        'indent_trans': 'indent_trans',
        'opacity': 'bg_opacity',
        'window_min_width': 'min_width',
        'show_whitespace': 'show_whitespace',
        'ws_alpha': 'ws_alpha',
        'show_minimap': 'show_minimap',
        'show_indents': 'show_indents'}
    for editor in ce_manager.editors:
        for approp, edprop in propsdict.items():
            setattr(editor, edprop, getattr(self, approp))


class CE_PT_settings(bpy.types.Panel):
    bl_idname = 'CE_PT_settings'
    bl_space_type = 'TEXT_EDITOR'
    bl_region_type = 'WINDOW'
    bl_label = "Code Editor"
    bl_ui_units_x = 8

    def draw(self, context):
        layout = self.layout
        prefs = context.preferences.addons[__name__].preferences
        layout.prop(prefs, "show_minimap")
        layout.prop(prefs, "show_tabs")
        layout.prop(prefs, "show_whitespace")
        layout.prop(prefs, "show_indents")


class CodeEditorPrefs(bpy.types.AddonPreferences):
    """Code Editors Preferences Panel"""
    bl_idname = __name__

    opacity: bpy.props.FloatProperty(
        name="Panel Background transparency", min=0.0, max=1.0, default=0.2,
        update=update_prefs
    )
    show_indents: bpy.props.BoolProperty(
        name="Indent Guides", default=True, update=update_prefs,
        description="Show indentation guides in the editor"
    )
    show_whitespace: bpy.props.BoolProperty(
        name="Whitespace", default=False, update=update_prefs,
        description="Show whitespace characters in the editor. Requires word-"
        "wrapping to be off currently"
    )
    ws_alpha: bpy.props.FloatProperty(
        name="Whitespace Character Alpha", min=0.0, max=1.0, default=0.2,
        update=update_prefs
    )
    show_tabs: bpy.props.BoolProperty(
        name="Texts Tab",
        description="Show opened textblock in tabs next to minimap",
        default=True, update=update_prefs
    )
    show_minimap: bpy.props.BoolProperty(
        name="Minimap",
        description="Show minimap", default=True, update=update_prefs
    )
    minimap_width: bpy.props.IntProperty(
        name="Minimap panel width", description="Minimap base width in px",
        min=get_widget_unit(bpy.context) // 5 * 3, max=400, default=225,
        update=update_prefs
    )
    window_min_width: bpy.props.IntProperty(
        name="Hide Panel when area width less than",
        description="Set 0 to deactivate side panel hiding, set huge to "
        "disable panel", min=0, max=4096, default=250, update=update_prefs
    )
    character_width: bpy.props.FloatProperty(
        name="Minimap character width", description="Minimap character "
        "width in px", min=0.1, max=4.0, default=1.0, update=update_prefs
    )
    line_height: bpy.props.FloatProperty(
        name="Minimap line height", description="Minimap line height in "
        "pixels", min=0.5, max=4.0, default=1.0, update=update_prefs
    )
    indent_trans: bpy.props.FloatProperty(
        name="Indentation markings transparency", description="0 - fully "
        "opaque, 1 - fully transparent", min=0.0, max=1.0, default=0.3,
        update=update_prefs
    )

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        col = row.column(align=True)
        col.prop(self, "opacity")
        col.prop(self, "show_tabs", toggle=True)
        col.prop(self, "window_min_width")
        col = row.column(align=True)
        col.prop(self, "minimap_width")
        col.prop(self, "character_width")
        col.prop(self, "line_height")
        row = layout.row(align=True)
        row = layout.row(align=True)
        row.prop(self, "indent_trans")
        col = layout.column(align=True)
        col.prop(self, "show_whitespace")
        col.prop(self, "ws_alpha")

    def add_to_header(self, context):
        layout = self.layout
        layout.popover_group(
            "TEXT_EDITOR",
            region_type="WINDOW",
            context="",
            category="")


classes = (
    CodeEditorPrefs,
    CE_OT_mouse_move,
    CE_OT_cursor_set,
    CE_OT_scroll,
    CE_PT_settings,
    WM_OT_event_catcher)


def set_draw(state=True):
    from bpy_restrict_state import _RestrictContext
    st = bpy.types.SpaceTextEditor

    if state:
        if isinstance(bpy.context, _RestrictContext):  # delay until freed
            return bpy.app.timers.register(set_draw, first_interval=1e-3)
        set_draw._handle = st.draw_handler_add(
            draw_callback_px, (bpy.context,), 'WINDOW', 'POST_PIXEL')
    else:
        st.draw_handler_remove(set_draw._handle, 'WINDOW')
        del set_draw._handle

    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == 'TEXT_EDITOR':
                a.tag_redraw()


def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)

    bpy.types.TEXT_HT_header.append(CodeEditorPrefs.add_to_header)

    kc = bpy.context.window_manager.keyconfigs.addon.keymaps
    km = kc.get('Text', kc.new('Text', space_type='TEXT_EDITOR'))
    # needs to be before any other potentially blocking kmis
    new = km.keymap_items.new
    kmi1 = new('ce.mouse_move', 'MOUSEMOVE', 'ANY', head=True)
    kmi2 = new('ce.cursor_set', 'LEFTMOUSE', 'PRESS', head=True)

    register.keymaps = ((km, kmi1), (km, kmi2))
    set_draw(getattr(bpy, "context"))


def unregister():
    set_draw(state=False)
    bpy.types.TEXT_HT_header.remove(CodeEditorPrefs.add_to_header)

    for km, kmi in register.keymaps:
        km.keymap_items.remove(kmi)
    del register.keymaps

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
