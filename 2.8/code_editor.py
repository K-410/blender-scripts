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
from time import perf_counter
from gpu.shader import from_builtin
from gpu_extras.batch import batch_for_shader
from bpy.types import Operator
from collections import defaultdict, deque
from itertools import repeat
bl_info = {
    "name": "Code Editor",
    "location": "Text Editor > Righ Click Menu",
    "version": (0, 1, 0),
    "blender": (2, 80, 0),
    "description": "Better editor for coding",
    "author": "",
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


# emulate a list of integers with slicing capability
# use with tracking indents
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

    # generate a blank cache
    def __missing__(self, key):
        assert key in bpy.data.texts
        self.purge_unused()
        text = bpy.data.texts[key]
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
        texts = bpy.data.texts
        found = key = None
        while texts:
            if found:
                del self[key]
                found = False
            for key in self:
                if key not in texts:
                    found = True
                    break
            if not found:
                break


# maintain caches and give out handles for editors
class CodeEditorManager(dict):
    editors = []
    tcache = TextCache()

    def __init__(self):
        super(__class__, self).__init__()
        self.__dict__ = self

    def get_cached(self, text):
        cache = self.tcache[text.name]
        lenl = len(text.lines)
        lenp = len(cache[1][0])
        # if the original text is longer, increase cache size
        if lenl > lenp:
            for slot in cache[1].values():
                slot.extend([[] for _ in repeat(None, (lenl - lenp))])
        # or nuke the slots
        elif lenp > lenl:
            del cache[3][lenl:]
            for data in cache[1].values():
                del data[lenl + 1:]
            pop = cache[0].pop
            for i in range(lenl, lenp):
                pop(i, None)
        # cached text is a defaultdict, meaning a cache is
        # automatically created instead of raising KeyError
        return cache

    # remove unused instances (closed editors)
    def gc(self, context):
        pset = set()
        add = pset.add
        for w in context.window_manager.windows:
            for a in w.screen.areas:
                if a.type == 'TEXT_EDITOR':
                    add(f"ce_{a.as_pointer()}")
        found = i = None
        while found is not False:
            if found:
                found = False
                del self[i]
            for i in self:
                if i not in pset:
                    found = True
                    break
            if not found:
                break

    def _new(self, hid, context):
        # clean up when a new space is added
        self.gc(context)
        self[hid] = CodeEditorMain(context)
        self.editors.append(self[hid])
        return self[hid]

    def get_handle(self, context):
        hid = f"ce_{context.area.as_pointer()}"
        handle = self.get(hid)
        if not handle:
            return self._new(hid, context)
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


def get_xoffs(text, st):
    loc = st.region_location_from_cursor
    for idx, line in enumerate(text.lines):
        if len(line.body) > 1:
            xstart = loc(idx, 0)[0]
            return loc(idx, 1)[0] - xstart, xstart
    return 0, 0


# source/blender/windowmanager/intern/wm_window.c$515
def get_widget_unit(context):
    system = context.preferences.system
    p = system.pixel_size
    pd = p * system.dpi
    return int((pd * 20 + 36) / 72 + (2 * (p - pd // 72)))


class MinimapEngine:

    def _texts(self):
        return self._data.texts

    def __init__(self, ce, output_list):
        self.output = output_list
        self.ce = ce
        self.data = bpy.data
        self.special = ('def ', 'class ')
        self.numerics = {'0', '1', '2', '3', '4', '5', '6', '7', '8', '9'}
        self.numericsdot = {*self.numerics, '.'}
        self.builtin = {'return', 'break', 'continue', 'yield', 'with', 'is '
                        'while', 'for ', 'import ', 'from ', 'not ', 'elif ',
                        ' else', 'None', 'True', 'False', 'and ', 'in ', 'if '}
        self.ws = {'\x0b', '\r', '\x0c', '\t', '\n', ' '}
        self.some_set = {'TAB', 'STRING', 'BUILTIN', 'SPECIAL'}
        self.some_set2 = {'COMMENT', 'PREPRO', 'STRING', 'NUMBER'}
        self._data = bpy.data
        self.enumbuilt = [*enumerate(self.builtin)]
        self.enumspec = [*enumerate(self.special)]

    def close_block(self, idx, indent, blankl, spec, dspecial):
        remove = spec.remove
        val = idx - blankl
        for entry in spec:
            if entry[0] < idx and entry[1] >= indent:
                dspecial[entry[0]].append((entry[1], entry[2], val))
                remove(entry)

    def highlight(self, tidx):
        # abort if requested during undo/redo
        texts = self._texts()
        if not texts:
            return

        text = texts[tidx]

        t = perf_counter()
        ce = self.ce
        # draw only a portion of the text at a time
        start, end = ce.maprange[0], ce.maprange[-1]

        # make a proxy version of the text
        c_hash, c_data, special_temp, c_indents = ce_manager.get_cached(text)
        # print(len(c_hash), len(text.lines), len(special_temp), len(c_data[0]))

        dspecial = c_data['special']   # special keywords (class, def)
        dplain = c_data['plain']       # plain text
        dnumbers = c_data['numbers']   # ints and floats
        dstrings = c_data['strings']   # strings
        dbuiltin = c_data['builtin']   # builtin
        dcomments = c_data['comments'] # comments
        dprepro = c_data['prepro']     # pre-processor (decorators)
        dtabs = c_data['tabs']         # ?????
        indents = c_indents            # indentation levels
        # indents = c_data['indents']    # indentation levels

        blankl = 0
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

        # this ends collapsible code block <- not sure what this means
        close_block = self.close_block
        # recognized tags definitions, only the most used
        numerics = self.numerics
        numericsdot = self.numericsdot
        some_set = self.some_set
        some_set2 = self.some_set2
        ws = self.ws
        idx = 0
        # flags of syntax state machine
        state = ""
        timer = -1      # timer to skip characters and close segment at t=0
        builtin_set = "rbcywfieNTFan"
        enumbuilt = self.enumbuilt
        enumspec = self.enumspec
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
            hsh = hash(line.body)
            if hsh == c_hash[idx]:
                # use cached data instead
                continue

            c_hash[idx] = hsh

            # TODO wrap into a function
            for i in (dspecial, dplain, dnumbers, dstrings, dbuiltin, dcomments, dprepro):
                i[idx].clear()

            bod = line.body
            lenbstrip = len(bod.lstrip())
            lenb = len(bod)
            ind = (lenb - lenbstrip) // tab_width

            # track hanging indents by looking at previous
            if not lenbstrip:
                ind = look_back(idx)
            indents[idx] = ind

            # new line new element, carry string flag
            elem[0] = idx
            elem[1] = 0
            if state != 'STRING':
                state = ""

            indent = 0
            block_close = has_non_ws = any(c not in ws for c in bod)
            enumbod = [*enumerate(bod)]
            # process each line and break into syntax elements
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
                            for i, b in enumbuilt:
                                if b in bodsub[:len(b)]:
                                    close_plain(elem, cidx)
                                    state = 'BUILTIN'
                                    timer = len(b) - 1
                                    break
                        # special (def, class)
                        if not state and c in "dc":
                            bodsub = bod[cidx:]
                            for i, b in enumspec:  # TODO remove i
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
                        elif c in '\"\'':
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
                                        close_block(idx, i // 4 * 4, blankl, special_temp, dspecial)
                            break
                        # preprocessor
                        elif c == '@':
                            # print("is @", c)
                            close_plain(elem, cidx)
                            state = 'PREPRO'
                            # close code blocks
                            if block_close:
                                # print("close block", timer)
                                close_block(idx, indent, blankl, special_temp, dspecial)
                            break
                    elif state == 'NUMBER' and c not in numericsdot:
                        elem[2] = cidx
                        dnumbers[idx].append(elem[1:3])
                        elem[1] = cidx
                        state = ""
                    elif state == 'STRING':
                        if c in "\"\'":
                            if '\\' not in bod[cidx - 1]:
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

            # handle line ends
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
                    # dnumbers[idx].append(elems)
                    dnumbers[idx].append(elems)

        # special_temp size keeps growing, fucking fix this
        # close all remaining blocks
        val = idx + 1 - blankl
        for entry in special_temp:
            dspecial[entry[0]].append([entry[1], entry[2], val])

        # done
        output = self.output
        output[0]['elements'] = dplain
        output[1]['elements'] = dstrings
        output[2]['elements'] = dcomments
        output[3]['elements'] = dnumbers
        output[4]['elements'] = dbuiltin
        output[5]['elements'] = dprepro
        output[6]['elements'] = dspecial  # XXX needs fixing
        output[7]['elements'] = dtabs
        ce.indents = indents
        # t2 = perf_counter()
        # print("highlighter:", round((t2 - t) * 1000, 2), "ms")

        self.ce.tag_redraw()


# =====================================================
#                    OPENGL DRAWCALS
# =====================================================

def get_cw(loc, firstx, lines):
    for idx, line in enumerate(lines):
        if len(line.body) > 1:
            return loc(idx, 1)[0] - firstx


def draw_callback_px(context):
    """Draws Code Editors Minimap and indentation marks"""
    t = perf_counter()
    # print("\n"*10)
    text = context.edit_text

    if not text:
        return

    ce = get_handle(context)

    if text != ce.text:
        ce.update_text(text)

    bgl_glEnable(bgl_GL_BLEND)

    # init params
    font_id = 0
    region = context.area.regions[-1]
    rw, rh = region.width, region.height
    mmapw = ce.mmapw
    wunits = get_widget_unit(context)
    scrolledge = rw - wunits // 5 * 3

    ledge = ce.ledge = rw - mmapw
    redge = ce.redge = scrolledge
    # compute character dimensions
    dpi_r = context.preferences.system.dpi / 72.0
    mcw = int(dpi_r * ce.mmsymw)         # minimap char width
    mlh = round(dpi_r * ce.mmlineh)   # minimap line height
    st = context.space_data
    fs = st.font_size
    loc = st.region_location_from_cursor
    xoffs, xstart = get_xoffs(text, st)
    lines = text.lines

    # line height
    lh_dpi = (wunits * st.font_size) // 20
    lh = lh_dpi + int(0.3 * lh_dpi)

    # char width
    cw = get_cw(loc, xstart, lines)
    # cw = round(dpi_r * round(2 + 0.6 * (fs - 4)))                     # char width
    ch = round(dpi_r * round(2 + 1.3 * (fs - 2) + ((fs % 10) == 0)))  # char height
    sttop = st.top
    visl = st.visible_lines
    sttopvisl = sttop + visl
    # panel background box
    texts = bpy.data.texts
    lenl = len(lines)
    lent = len(texts)
    tabw = ce.tabw = round(dpi_r * 25) if (ce.show_tabs and lent > 1) else 0
    tabh = min(200, int(rh / lent))
    ldig = len(str(lenl)) if st.show_line_numbers else 0
    ce.linebarw = int(dpi_r * 5) + cw * ldig

    max_slide = max(0, mlh * (lenl + rh / ch) - rh)
    ce.slide = slide = (max_slide * sttop / lenl).__int__()
    mapymin = rh - mlh * sttop + slide
    mapymax = rh - mlh * sttopvisl + slide
    startrange = (sttop - (rh - mapymin) // mlh)
    endrange = startrange + (rh // mlh)
    # update opacity for now
    ce.opacity = opac = min(max(0, (rw - ce.min_width) / 100.0), 1)

    x = ledge - tabw

    hash_curr = hash((*lines[startrange:endrange],))

    # rebuild visible range
    if startrange not in ce.maprange or endrange not in ce.maprange:
        ce.maprange = range(startrange, endrange + 1)
    # minimap update is now cheap. do it every redraw
    ce.update_text(text)
    color = (*ce.background, (1 - ce.bg_opacity) * opac)
    seq = [(x, rh), (redge, rh), (redge, 0), (x, 0)]
    segments = ce.segments
    draw_quads_2d(seq, color)
    # minimap shadow
    bgl_glLineWidth(1.0)
    for idx, intensity in enumerate([.2, .1, .07, .05, .03, .02, .01]):
        color = 0.0, 0.0, 0.0, intensity * opac
        seq = [(ledge - idx - tabw, 0), (ledge - idx - tabw, rh)]
        draw_lines_2d(seq, color)
    # divider
    if tabw:
        color = 0.0, 0.0, 0.0, 0.2 * opac
        seq = [(ledge, 0), (ledge, rh)]
        draw_lines_2d(seq, color)
    # if there is text in window
    if opac:
        # minimap horizontal sliding based on text block length
        mmtop = slide // mlh
        mmbot = (rh + slide) // mlh
        # minimap hover alpha
        alpha = 0.1 if ce.in_minimap else 0.07
        color = 1.0, 1.0, 1.0, alpha * opac
        ymin = rh - mlh * sttop + slide
        ymax = rh - mlh * sttopvisl + slide
        seq = ((ledge, ymin), (redge, ymin), (redge, ymax), (ledge, ymax))
        draw_quads_2d(seq, color)
        # draw minimap code
        thickness = mlh // 2
        bgl_glLineWidth(thickness)
        for seg in segments[:-1]:
            color = seg['col'][0], seg['col'][1], seg['col'][2], 0.4 * opac
            seq = deque()
            seq_extend = seq.extend
            for id, elem in enumerate(seg['elements'][mmtop:mmbot]):
                y = rh - (mlh * (id + mmtop + 1) - slide)
                for sub_element in elem:
                    selem0 = sub_element[0]
                    x = ledge + mcw * (selem0 + 4)
                    if x > scrolledge:
                        continue
                    x2 = mcw * (sub_element[1] - selem0)
                    if x + (x2 * mcw) > scrolledge:
                        x2 = (scrolledge - x) // mcw
                    seq_extend(((x, y), (x + x2, y)))
            draw_lines_2d(seq, color)

        # minimap code marks - vertical
        seq2 = deque()
        seq2_extend = seq2.extend
        yoffs = rh + slide
        color = (*segments[-2]['col'][:3], 0.3 * ce.block_trans * opac)

        mmapxoffs = ledge + 4

        # first absolute x value
        tab_width = st.tab_width
        indent = cw * tab_width

        # draw indent guides in the minimap
        firstx = (wunits // 2 + (st.show_line_numbers and (ldig * cw) or 0))
        for idx, levels in enumerate(ce.indents[mmtop:mmbot], mmtop):
            if levels:
                for level in range(levels):
                    x = mmapxoffs + (mcw * 4 * level)
                    ymax = yoffs - mlh * idx
                    ymin = ymax - mlh
                    seq2_extend(((x, ymin), (x, ymax)))

                    # draw indent guides in the editor
                    ymax = rh - lh * (idx + 1 - sttop) + lh
                    ymin = ymax - lh

                    bgl_glLineWidth(int(wunits * 0.15 * 0.5))
                    if -lh < ymin < rh:
                        x = xstart + indent * level

                        # don't draw indents beyond line numbers
                        if x >= firstx - 10:
                            seq2_extend(((x, ymin), (x, ymax)))
                            continue

        draw_lines_2d(seq2, color)

    bgl_glLineWidth(1.0 * dpi_r)
    # tab dividers
    if tabw and opac:
        # ce.tab_height = tabh = min(200, int(rh / lent))
        y_loc = rh - 5
        for txt in texts:
        #     # tab selection
            if txt.name == ce.in_tab:
                color = 1.0, 1.0, 1.0, 0.05 * opac
                seq = [(ledge - tabw, y_loc),
                       (ledge, y_loc),
                       (ledge, y_loc - tabh),
                       (ledge - tabw, y_loc - tabh)]
                draw_quads_2d(seq, color)
            # tab active
            if txt.name == text.name:
                color = 1.0, 1.0, 1.0, 0.05 * opac
                seq = [(ledge - tabw, y_loc),
                       (ledge, y_loc),
                       (ledge, y_loc - tabh),
                       (ledge - tabw, y_loc - tabh)]
                draw_quads_2d(seq, color)

            color = 0.0, 0.0, 0.0, 0.2 * opac
            y_loc -= tabh
            seq = [(ledge - tabw, y_loc), (ledge, y_loc)]
            draw_lines_2d(seq, color)
    # if tabw and opac:
    #     ce.tabh = tabh = min(200, int(rh / len(bpy.data.texts)))
    #     y_loc = rh - 5
    #     for txt in bpy.data.texts:
    #         # tab selection
    #         if txt.name == ce.in_tab:
    #             color = 1.0, 1.0, 1.0, 0.05 * opac
    #             seq = [(ledge-tabw, y_loc),
    #                    (ledge, y_loc),
    #                    (ledge, y_loc-tabh),
    #                    (ledge-tabw, y_loc-tabh)]
    #             # seq = [(x, y_loc),
    #             #        (ledge, y_loc),
    #             #        (ledge, y_loc - tabh),
    #             #        (x, y_loc - tabh)]

    #             draw_quads_2d(seq, color)

    #     #     tab active
    #         if text and txt.name == text.name:
    #             color = 1.0, 1.0, 1.0, 0.05 * opac
    #             seq = [(x, y_loc),
    #                    (ledge, y_loc),
    #                    (ledge, y_loc - tabh),
    #                    (x, y_loc - tabh)]
    #             draw_quads_2d(seq, color)
    #         color = 0.0, 0.0, 0.0, 0.2 * opac
    #         y_loc -= tabh
    #         seq = [(x, y_loc), (ledge, y_loc)]
    #         draw_lines_2d(seq, color)

    # draw file names
    if tabw:
        blf_size(font_id, fs - 1, int(dpi_r * 72))
        blf_enable(font_id, blf_ROTATION)
        blf_rotation(font_id, 1.5707963267948966)
        y_loc = rh
        for txt in texts:
            text_max_length = max(2, int((tabh - 40) / cw))
            name = txt.name[:text_max_length]
            if text_max_length < len(txt.name):
                name += '...'
            blf_color(font_id, *segments[0]['col'][:3],
                      (0.7 if txt.name == ce.in_tab else 0.4) * opac)
            blf_position(font_id, ledge - round((tabw - ch) / 2.0) - 5,
                         round(y_loc - (tabh / 2) - cw * len(name) / 2), 0)
            blf_draw(font_id, name)
            y_loc -= tabh

    # restore opengl defaults
    bgl_glLineWidth(1.0)
    bgl_glDisable(bgl_GL_BLEND)
    blf_rotation(font_id, 0)
    blf_disable(font_id, blf_ROTATION)
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
        ev, et = event.value, event.type
        if et == 'LEFTMOUSE' and ev == 'RELEASE':
            context.window_manager.event_timer_remove(self.t)
            return {'FINISHED'}
        elif et == 'TIMER':
            return self.scroll_timer(context, event)
            # return self.scroll_timer(context, event)
        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        ce = self.ce = get_handle(context)
        st = context.space_data
        rh = context.region.height
        ignore = {'INBETWEEN_MOUSEMOVE', 'MOUSEMOVE',
                  'TIMER', 'NOTHING', 'PRESS'}

        fs = st.font_size
        dpi_r = context.preferences.system.dpi / 72.0
        ch = round(dpi_r * round(2 + 1.3 * (fs - 2) + ((fs % 10) == 0)))
        mlh = round(context.preferences.system.dpi / 72.0 * ce.mmlineh)
        slide_max = max(0, mlh * (len(context.edit_text.lines) + rh / ch) - rh)

        self.args = st, rh, mlh, slide_max, ignore
        context.window.cursor_set('HAND')
        wm = context.window_manager
        wm.modal_handler_add(self)
        self.t = wm.event_timer_add(0.001, window=context.window)
        self.scroll = bpy.ops.text.scroll_bar
        return self.scroll_timer(context, event)

    def scroll_timer(self, context, event):
        dpi_r = context.preferences.system.dpi / 72.0
        mlh = round(dpi_r * self.ce.mmlineh) 
        # box center in px
        mry = event.mouse_region_y
        box_center = context.region.height - mlh * (context.space_data.top + context.space_data.visible_lines/2)
        self.to_box_center = box_center + self.ce.slide - mry
        nlines = 0.333 * self.to_box_center / mlh
        bpy.ops.text.scroll(lines=round(nlines))
        return {'RUNNING_MODAL'}







        # st = context.space_data
        # ev, et = event.value, event.type
        # slide = self.ce.slide
        # if et == 'LEFTMOUSE' and ev == 'RELEASE':
        #     context.window_manager.event_timer_remove(self.t)
        #     return {'FINISHED'}
        # mlh = (round(context.preferences.system.dpi / 72.0 * self.ce.mmlineh))
        # rh = context.region.height
        # sttop = st.top
        # stvisl = st.visible_lines
        # lenl = len(st.text.lines)
        # mry = (event.mouse_region_y)

        # ymin = rh - mlh * sttop + slide
        # ymax = rh - mlh * (sttop + stvisl) + slide

        # negexp = (lenl ** -1 * 3) * 100
        # ymid2 = ((ymin - ymax) // 2 + ymax)
        # r = ((ymid2 - mry) / (lenl ** negexp))
        # n = True
        # if not round(r, 0):
        #     if ymid2 // 10 < mry // 10:
        #         r = (ymid2 - mry) // lenl
        #     elif ymid2 // 10 > mry // 10:
        #         r = ((ymid2 - mry) // lenl) + 1
        #     else:
        #         n = False
        #         r *= 10
        # if n:
        #     r = round(r)
        # if int(r):
        #     self.scroll('INVOKE_DEFAULT', lines=r)
        # return {'RUNNING_MODAL'}


# capture clicks inside minimap
class CE_OT_cursor_set(CodeEditorBase, Operator):
    bl_idname = "ce.cursor_set"
    bl_label = "Set Cursor"
    options = {'INTERNAL', 'BLOCKING'}

    def invoke(self, context, event):
        ce = get_handle(context)
        if ce and ce.in_minimap:
            return bpy.ops.ce.scroll('INVOKE_DEFAULT')
        return {'PASS_THROUGH'}


# handle mouse events in text editor to support hover and scroll
class CE_OT_mouse_move(CodeEditorBase, Operator):
    bl_idname = "ce.mouse_move"
    bl_label = "Mouse Move"

    def invoke(self, context, event):
        ce = get_handle(context)
        if ce:
            ce.update(context, event)
        return {'CANCELLED'}


# main class for storing runtime draw props
class CodeEditorMain:
    def __init__(self, context):

        # user controllable in addon preferneces
        p = context.preferences
        ap = p.addons[__name__].preferences
        self.bg_opacity = ap.opacity
        self.show_tabs = ap.show_tabs
        self.mmapw = ap.minimap_width
        self.min_width = ap.window_min_width
        self.mmsymw = ap.symbol_width
        self.mmlineh = ap.line_height
        self.block_trans = ap.block_trans
        self.indent_trans = ap.indent_trans

        # init params
        self.st = context.space_data
        self.in_minimap = False
        region = self.region = context.area.regions[-1]
        rw = region.width
        self.opacity = min(max(0, (rw - self.min_width) / 100.0), 1)
        self.height = region.height
        dpi_r = self.dpi_r = p.system.dpi / 72.0
        self.ledge = rw - round(dpi_r * (rw + 5 * self.mmapw) / 10.0)
        self.redge = rw - round(dpi_r * 15)
        self.tabw = round(dpi_r * 25) if self.show_tabs else 0
        self.in_tab = None
        self.tab_height = 0
        self.drag = False
        self.slide = 0
        self.text = text = context.edit_text
        if text:
            self.hash_prev = hash((*text.lines[:],))
        # get theme colors
        current_theme = p.themes.items()[0][0]
        tex_ed = p.themes[current_theme].text_editor
        self.background = tex_ed.space.back
        self.maprange = range(0, 1)
        self.prev_update = perf_counter()
        self.defer_update = False

        # syntax theme colors
        items = (
            tex_ed.space.text,
            tex_ed.syntax_string,
            tex_ed.syntax_comment,
            tex_ed.syntax_numbers,
            tex_ed.syntax_builtin,
            tex_ed.syntax_preprocessor,
            tex_ed.syntax_special,
            (1, 0, 0))

        self.segments = [{'elements': [], 'col': i} for i in items]
        self.indents = None
        # self.data['indents'] = defaultdict(list)
        self.tag_redraw = context.area.tag_redraw

        # claim a highlighter
        self.engine = MinimapEngine(self, self.segments)
        self.engine.highlight(bpy.data.texts[:].index(text))

    # refresh the highlights
    def update_text(self, text, delay=None):
        self.text = text
        tidx = bpy.data.texts[:].index(text)
        self.engine.highlight(tidx)

    # determine the need to update drawing
    # (hover highlight, minimap refresh, tab activation)
    def update(self, context, event):
        ledge = self.ledge
        opac = self.opacity
        show_tabs = self.show_tabs
        tab_xmin = ledge - self.tabw
        mrx = event.mouse_region_x
        lbound = tab_xmin if show_tabs and bpy.data.texts else ledge
        # update minimap symbols if text has changed
        text = context.edit_text
        if text != self.text:
            self.update_text(text)
        if lbound <= mrx:
            context.window.cursor_set('DEFAULT')
        # update minimap highlight when mouse in region
        in_minimap = ledge <= mrx < self.redge and opac
        if in_minimap != self.in_minimap:
            self.in_minimap = in_minimap
            self.tag_redraw()
        in_tab = tab_xmin <= mrx < ledge and opac
        # if in_ttab:
        #     context.window.cursor_set('DEFAULT')
        # prevent view layer update
        return {'CANCELLED'}


def update_prefs(self, context):
    propsdict = {
        'minimap_width': 'mmapw',
        'show_tabs': 'show_tabs',
        'symbol_width': 'mmsymw',
        'line_height': 'mmlineh',
        'block_trans': 'block_trans',
        'indent_trans': 'indent_trans',
        'opacity': 'bg_opacity',
        'window_min_width': 'min_width'}
    for editor in ce_manager.editors:
        for approp, edprop in propsdict.items():
            setattr(editor, edprop, getattr(self, approp))


class CodeEditorPrefs(bpy.types.AddonPreferences):
    """Code Editors Preferences Panel"""
    bl_idname = __name__

    opacity: bpy.props.FloatProperty(
        name="Panel Background transparency",
        description="0 - fully opaque, 1 - fully transparent",
        min=0.0,
        max=1.0,
        default=0.2,
        update=update_prefs)

    show_tabs: bpy.props.BoolProperty(
        name="Show Tabs in Panel when multiple text blocks",
        description="Show opened textblock in tabs next to minimap",
        default=True,
        update=update_prefs)

    minimap_width: bpy.props.IntProperty(
        name="Minimap panel width",
        description="Minimap base width in px",
        min=get_widget_unit(bpy.context) // 5 * 3,
        max=400,
        default=110,
        update=update_prefs)

    window_min_width: bpy.props.IntProperty(
        name="Hide Panel when area width less than",
        description="Set 0 to deactivate side panel hiding, set huge to disable panel",
        min=0,
        max=4096,
        default=250,
        update=update_prefs)

    symbol_width: bpy.props.IntProperty(
        name="Minimap character width",
        description="Minimap character width in px",
        min=1,
        max=4,
        default=1,
        update=update_prefs)

    line_height: bpy.props.IntProperty(
        name="Minimap line spacing",
        description="Minimap line spacign in px",
        min=2,
        max=10,
        default=2,
        update=update_prefs)

    block_trans: bpy.props.FloatProperty(
        name="Code block markings transparency",
        description="0 - fully opaque, 1 - fully transparent",
        min=0.0,
        max=1.0,
        default=0.5,
        update=update_prefs)

    indent_trans: bpy.props.FloatProperty(
        name="Indentation markings transparency",
        description="0 - fully opaque, 1 - fully transparent",
        min=0.0,
        max=1.0,
        default=0.9,
        update=update_prefs)

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        col = row.column(align=True)
        col.prop(self, "opacity")
        col.prop(self, "show_tabs", toggle=True)
        col.prop(self, "window_min_width")
        col = row.column(align=True)
        col.prop(self, "minimap_width")
        col.prop(self, "symbol_width")
        col.prop(self, "line_height")
        row = layout.row(align=True)
        row = layout.row(align=True)
        row.prop(self, "block_trans")
        row.prop(self, "indent_trans")


classes = (
    CodeEditorPrefs,
    CE_OT_mouse_move,
    CE_OT_cursor_set,
    CE_OT_scroll)


def redraw_editors(context):
    for w in context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == 'TEXT_EDITOR':
                a.tag_redraw()


def set_draw(state=True):
    from bpy_restrict_state import _RestrictContext
    st = bpy.types.SpaceTextEditor
    context = bpy.context

    if state:
        if isinstance(context, _RestrictContext):
            # delay until context is freed
            return bpy.app.timers.register(
                lambda: set_draw(state=state), first_interval=1e-3)
        elif getattr(set_draw, '_handle', False):
            pass  # remove handle instead
        else:
            setattr(set_draw, '_handle', st.draw_handler_add(
                draw_callback_px, (context,), 'WINDOW', 'POST_PIXEL'))
            return redraw_editors(context)

    handle = getattr(set_draw, '_handle', False)
    if handle:
        st.draw_handler_remove(handle, 'WINDOW')
        delattr(set_draw, '_handle')
        redraw_editors(context)


def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)

    set_draw(getattr(bpy, "context"))


def unregister():
    set_draw(state=False)
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
