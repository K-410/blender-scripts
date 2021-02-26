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
import ctypes
import bpy
from time import monotonic

bl_info = {
    "name": "Toggle Hide",
    "location": "3D View / Outliner, (Hotkey J)",
    "version": (0, 2, 0),
    "blender": (2, 83, 0),
    "description": "Toggle object visibility of outliner selection",
    "author": "kaio",
    "category": "Object",
}



def space_outliner():
    """Get the outliner. If context area is outliner, return it."""
    context = bpy.context
    if context.area.type == 'OUTLINER':
        return context.space_data
    for w in context.window_manager.windows:
        for a in w.screen.areas:
            if a.type == 'OUTLINER':
                return a.spaces.active

def redraw(t=None):
    """Redraw an outliner.
    Since this may be called for multiple objects in one operation, defer
    redraw.
    """
    tnext = monotonic()
    if t != tnext:
        wm = bpy.context.window_manager
        redraw.funcs = [a.regions[-1].tag_redraw for w in wm.windows
                        for a in w.screen.areas if a.type == 'OUTLINER']
        redraw.__defaults__ = tnext,
    for tag_redraw in redraw.funcs:
        tag_redraw()


def listbase(ctype=None):
    ptr = ctypes.POINTER(ctype)
    name = getattr(ctype, "__name__", "Generic")
    fields = {"_fields_": (("first", ptr), ("last", ptr))}
    return type(f"ListBase_{name}", (ctypes.Structure,), fields)


def fproperty(funcs, property=property):
    return property(*funcs())


class TreeElement(ctypes.Structure):
    _object = None
    _treeid = None

    @fproperty
    def select():
        """Get/set the selection of a tree element."""
        def getter(self):
            return bool(self._store_elem.contents.flag & 2)
        def setter(self, state):
            tse = self._store_elem.contents
            flag = tse.flag
            if state:
                tse.flag |= 2
            else:
                tse.flag &= ~2
            if flag != tse.flag:
                redraw()
        return getter, setter

    @fproperty
    def expand():
        """Get/set the expansion of a tree element."""
        def getter(self):
            return not bool(self.tseflag & 1)
        def setter(self, state):
            tse = self._store_elem.contents
            if state:
                tse.flag &= ~1
            else:
                tse.flag |= 1
        return getter, setter

    @property
    def treeid(self):
        """Tree element identifier, internal."""
        if self._treeid is None:
            self._treeid = hash(
                tuple((t._name.decode(), t.idcode) for t in self._resolve()))
        return self._treeid

    def _resolve(self):
        """Tree element path, internal."""
        link = [self]
        parent = self._parent
        while parent:
            link.append(parent.contents)
            parent = parent.contents._parent
        return tuple(reversed(link))

    def as_object(self):
        if self._object is None:
            self._object = obj_by_id(self)
        return self._object


class SpaceOutliner(ctypes.Structure):
    _fields_ = (
        ("next", ctypes.c_void_p),
        ("prev", ctypes.c_void_p),
        ("regionbase", ctypes.c_void_p * 2),
        ("spacetype", ctypes.c_char),
        ("link_flag", ctypes.c_char),
        ("pad0", ctypes.c_char * 6),
        ("v2d", ctypes.c_char * 168),
        ("tree", listbase(TreeElement)))


class TreeStoreElem(ctypes.Structure):
    _fields_ = (
        ("type", ctypes.c_short),
        ("nr", ctypes.c_short),
        ("flag", ctypes.c_short))


TreeElement._fields_ = (
    ("next", ctypes.POINTER(TreeElement)),
    ("prev", ctypes.POINTER(TreeElement)),
    ("_parent", ctypes.POINTER(TreeElement)),
    ("subtree", listbase(TreeElement)),
    ("xys", ctypes.c_int * 2),
    ("_store_elem", ctypes.POINTER(TreeStoreElem)),
    ("flag", ctypes.c_short),
    ("index", ctypes.c_short),
    ("idcode", ctypes.c_short),
    ("xend", ctypes.c_short),
    ("_name", ctypes.c_char_p),
    ("directdata", ctypes.c_void_p),
    ("rnaptr", ctypes.c_void_p * 3))


class wmWindowManager(ctypes.Structure):
    _fields_ = (
        ("id", ctypes.c_char * 160),
        ("windrawable", ctypes.c_void_p),
        ("winactive", ctypes.c_void_p),
        ("windows", listbase()),
        ("initialized", ctypes.c_short),
        ("file_saved", ctypes.c_short),
        ("op_undo_depth", ctypes.c_short),
        ("outliner_sync_select_dirty", ctypes.c_short))


# TODO: Make non-recursive.
def subtrees_get(tree):
    """Given a tree, retrieve all its sub tree elements."""
    subtrees = []
    stree = tree.contents.subtree.first
    while stree:
        subtrees.append(stree.contents)
        subtrees.extend(subtrees_get(stree))
        stree = stree.contents.next
    return subtrees


def obj_by_id(self):
    """Given a tree id, return an object instance or a layer collection.

    A tree id is a hash based on object name and outliner path, and makes
    it possible to identify view layer object instances (object bases).
    """
    objs = bpy.context.view_layer.objects
    assert OUTLINER_OT_toggle_hide.root is not None
    for t in subtrees_get(OUTLINER_OT_toggle_hide.root):
        if t.treeid == self.treeid:
            name = t._name.decode()

            # Item is a layer collection.
            if t.idcode == 0:
                lc = bpy.context.view_layer.layer_collection
                for p in [t._name.decode() for t in self._resolve()][1:]:
                    lc = lc.children[p]
                return lc

            # Item is an object instance.
            elif name in objs:
                return objs[name]
            raise ValueError("Bad idcode:", t.idcode)


class OUTLINER_OT_toggle_hide(bpy.types.Operator):
    bl_idname = "outliner.toggle_hide"
    bl_label = "Toggle Hide"
    bl_options = {'REGISTER', 'UNDO'}

    root = None

    @classmethod
    def poll(self, context):
        ar = context.screen.areas
        __class__.area = next(
            (a for a in ar if a.type == 'OUTLINER'), None)
        return __class__.area

    def execute(self, context):
        so = space_outliner()
        assert so
        ret = SpaceOutliner.from_address(so.as_pointer())

        # Represents "Scene Collection", ie the topmost tree element.
        OUTLINER_OT_toggle_hide.root = ret.tree.first

        wmstruct = wmWindowManager.from_address(context.window_manager.as_pointer())

        walked = set()
        for t in subtrees_get(OUTLINER_OT_toggle_hide.root):
            if t.select:
                obj = t.as_object()
                if obj in walked:
                    continue
                # Is a layer collection, toggle its visibility.
                elif isinstance(obj, bpy.types.LayerCollection):
                    obj.hide_viewport ^= True

                # Is a hidden object instance, show it.
                elif obj.hide_get():
                    obj.hide_set(False)
                    obj.select_set(True)

                    # Clear sync flag so the object's visibility can be toggled
                    # without affecting the outliner selection.
                    wmstruct.outliner_sync_select_dirty &= ~1

                # Is a visible object instance. Hide it.
                else:
                    obj.hide_set(True)

                # Traversed objects are tracked to prevent multiple instances from
                # toggling eachother.
                walked.add(obj)
        OUTLINER_OT_toggle_hide.root = None
        return {'FINISHED'}


addon_keymaps = []


def register():
    bpy.utils.register_class(OUTLINER_OT_toggle_hide)
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon.keymaps
    km = kc.get("Object Mode")
    if not km:
        km = kc.new("Object Mode")
    kmi = km.keymap_items.new("outliner.toggle_hide", "J", "PRESS")
    addon_keymaps.append((km, kmi))

    km = kc.get("Outliner")
    if not km:
        km = kc.new("Outliner", space_type="OUTLINER")
    kmi = km.keymap_items.new("outliner.toggle_hide", "J", "PRESS")
    addon_keymaps.append((km, kmi))


def unregister():
    bpy.utils.unregister_class(OUTLINER_OT_toggle_hide)

    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()
