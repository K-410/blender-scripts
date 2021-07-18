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


# Currently supports versions:
#   2.83.x LTS
#   2.93.1
#   3.0 alpha

import bpy
from ctypes import c_int, c_float, c_void_p, c_short, \
    c_char, c_char_p, c_uint, POINTER, Structure

bl_info = {
    "name": "Toggle Hide",
    "location": "3D View / Outliner, (Hotkey J)",
    "version": (0, 1, 0),
    "blender": (2, 83, 0),
    "description": "Toggle object visibility of outliner selection",
    "author": "kaio",
    "category": "Object",
}

# Blender major/sub version
version = bpy.app.version[:2]

def idcode(id):
    return sum(j << 8 * i for i, j in enumerate(id.encode()))


# source/blender/makesdna/DNA_ID_enums.h
# We only care about types which can have their visibility toggled.
ID_OB = idcode("OB")  # bpy.types.Object
ID_LAYERCOLL = 0


def listbase(ctyp=None):
    ptr = POINTER(ctyp)
    name = getattr(ctyp, "__name__", "Generic")
    fields = {"_fields_": (("first", ptr), ("last", ptr))}
    return type(f"ListBase_{name}", (Structure,), fields)


def fproperty(funcs, property=property):
    return property(*funcs())


def _dyn_entry(name, ctyp, predicate):
    """Insert a Structure._fields_ entry based on predicate. Making it
    easier to add version-specific changes."""
    if predicate:
        return (name, ctyp),
    return ()


# source/blender/makesdna/DNA_view2d_types.h
class View2D(Structure):
    _fields_ = (
        ("tot", c_float * 4),
        ("cur", c_float * 4),
        ("vert", c_int * 4),
        ("hor", c_int * 4),
        ("mask", c_int * 4),
        ("min", c_float * 2),
        ("max", c_float * 2),
        ("minzoom", c_float),
        ("maxzoom", c_float),
        ("scroll", c_short),
        ("scroll_ui", c_short),
        ("keeptot", c_short),
        ("keepzoom", c_short),
        ("keepofs", c_short),
        ("flag", c_short),
        ("align", c_short),
        ("winx", c_short),
        ("winy", c_short),
        ("oldwinx", c_short),
        ("oldwiny", c_short),
        ("around", c_short),
        *_dyn_entry("tab_offset", POINTER(c_float), version == (2, 83)),
        *_dyn_entry("tab_num", c_int, version == (2, 83)),
        *_dyn_entry("tab_cur", c_int, version == (2, 83)),
        ("alpha_vert", c_char),
        ("alpha_hor", c_char),
        *_dyn_entry("_pad", c_char * 6, version == (2, 83)),
        ("sms", c_void_p),
        ("smooth_timer", c_void_p),
    )


# source/blender/makesdna/DNA_outliner_types.h
class TreeStoreElem(Structure):
    _fields_ = (
        ("type", c_short),
        ("nr", c_short),
        ("flag", c_short))


# source/blender/editors/space_outliner/outliner_intern.h
class TreeElement(Structure):
    _object = None
    _treeid = None
    _root = None

    @fproperty
    def select():
        """Get/set the selection of a tree element."""
        def getter(self):
            return bool(self.store_elem.contents.flag & 2)
        def setter(self, state):
            if state:
                self.store_elem.contents.flag |= 2
            else:
                self.store_elem.contents.flag &= ~2
        return getter, setter

    @fproperty
    def expand():
        """Get/set the expansion of a tree element."""
        def getter(self):
            return not bool(self.tseflag & 1)
        def setter(self, state):
            if state:
                self.store_elem.contents.flag &= ~1
            else:
                self.store_elem.contents.flag |= 1
        return getter, setter

    @property
    def treeid(self):
        """Internal use. """
        if self._treeid is None:
            self._treeid = hash(
                tuple((t.name.decode(), t.idcode) for t in self._resolve()))
        return self._treeid

    def _resolve(self):
        """Tree element path, internal."""
        link = [self]
        parent = self.parent
        while parent:
            link.append(parent.contents)
            parent = parent.contents.parent
        return tuple(reversed(link))

    def as_object(self, root):
        """Return the bpy.types.Object or LayerCollection instance"""
        if self._object is None:
            objs = bpy.context.view_layer.objects

            for t in subtrees_get(root):
                if t.treeid == self.treeid:
                    name = t.name.decode()

                    if t.idcode == ID_LAYERCOLL:
                        lc = bpy.context.view_layer.layer_collection
                        for p in [t.name.decode() for t in self._resolve()][1:]:
                            lc = lc.children[p]
                        self._object = lc
                        break

                    elif t.idcode == ID_OB:
                        self._object = objs[name]
                        break

        return self._object

    @classmethod
    def from_outliner(cls, so):
        return SpaceOutliner.from_address(so.as_pointer()).tree.first


TreeElement._fields_ = (
    ("next", POINTER(TreeElement)),
    ("prev", POINTER(TreeElement)),
    ("parent", POINTER(TreeElement)),
    *_dyn_entry("type", c_void_p, version > (2, 91)),
    ("subtree", listbase(TreeElement)),
    ("xs", c_int),
    ("ys", c_int),
    ("store_elem", POINTER(TreeStoreElem)),
    ("flag", c_short),
    ("index", c_short),
    ("idcode", c_short),
    ("xend", c_short),
    ("name", c_char_p),
    ("directdata", c_void_p),
    ("rnaptr", c_void_p * 3))


# source/blender/makesdna/DNA_space_types.h
class SpaceOutliner(Structure):
    _fields_ = (
        ("next", c_void_p),
        ("prev", c_void_p),
        ("regionbase", listbase()),
        ("spacetype", c_char),
        ("link_flag", c_char),
        ("pad0", c_char * 6),
        ("v2d", View2D),
        ("tree", listbase(TreeElement)),
        # ... (cont)
    )
    @classmethod
    def get_tree(cls, so: bpy.types.SpaceOutliner) -> TreeElement:
        return cls.from_address(so.as_pointer()).tree.first


# source/blender/makesdna/DNA_ID.h
class ID(Structure):
    _fields_ = (
        ("next", c_void_p),
        ("prev", c_void_p),
        ("newid", c_void_p),
        ("lib", c_void_p),
        *_dyn_entry("asset_data", c_void_p, version > (2, 83)),
        ("name", c_char * 66),
        ("flag", c_short),
        ("tag", c_int),
        ("us", c_int),
        ("icon_id", c_int),
        ("recalc", c_int),
        ("recalc_up_to_undo_push", c_int),
        ("recalc_after_undo_push", c_int),
        ("session_uuid", c_uint),
        ("properties", c_void_p),
        ("override_library", c_void_p),
        ("orig_id", c_void_p),
        ("py_instance", c_void_p),
        *_dyn_entry("_pad1", c_void_p, version > (2, 83))
    )


# source/blender/makesdna/DNA_windowmanager_types.h
class wmWindowManager(Structure):
    _fields_ = (
        ("id", ID),
        ("windrawable", c_void_p),
        ("winactive", c_void_p),
        ("windows", listbase()),
        ("initialized", c_short),
        ("file_saved", c_short),
        ("op_undo_depth", c_short),
        ("outliner_sync_select_dirty", c_short),
        # ... (cont)
    )


def subtrees_get(tree):
    """Given a tree, retrieve all its sub tree elements."""
    trees = []
    pool = [tree]
    while pool:
        t = pool.pop().contents
        trees.append(t)
        child = t.subtree.first
        while child:
            pool.append(child)
            child = child.contents.next
    return trees[1:]


class OUTLINER_OT_toggle_hide(bpy.types.Operator):
    """Toggle the visibility of current outliner selection"""
    bl_idname = "outliner.toggle_hide"
    bl_label = "Toggle Hide"
    bl_options = {'REGISTER', 'UNDO'}

    _keymaps = []
    _root = None
    _so = None

    # Toggling only works when an outliner area is present. When two or more
    # outliners exist, the active outliner is used for purpose of selection.
    @classmethod
    def poll(cls, context):
        if context.area.type == 'OUTLINER':
            cls._so = context.space_data
            return True

        for win in context.window_manager.windows:
            for ar in win.screen.areas:
                if ar.type == 'OUTLINER':
                    cls._so = ar.spaces.active
                    return True
        return False

    def execute(self, context):
        if self._so is None:
            return {'CANCELLED'}

        # Represents "Scene Collection" ie. the topmost tree element.
        root = TreeElement.from_outliner(self._so)
        wmstruct = wmWindowManager.from_address(context.window_manager.as_pointer())

        # Track processed objects to prevent those that appear in multiple
        # collections from being processed again.
        walked = set()
        types = {ID_OB, ID_LAYERCOLL}

        for tree in subtrees_get(root):
            if tree.select and tree.idcode in types:
                obj = tree.as_object(root)
                if obj in walked:
                    continue

                # Is a layer collection
                elif isinstance(obj, bpy.types.LayerCollection):
                    obj.hide_viewport ^= True

                # Is a bpy.types.Object instance
                elif isinstance(obj, bpy.types.Object):
                    if obj.hide_get():
                        obj.hide_set(False)
                        obj.select_set(True)
                        # Prevent outliner selection sync.
                        wmstruct.outliner_sync_select_dirty &= ~1

                    # Is a visible object instance. Hide it.
                    else:
                        obj.hide_set(True)

                # Traversed objects are tracked to prevent multiple instances from
                # toggling eachother.
                walked.add(obj)

        # Redraw to show any changes.
        for ar in self._so.id_data.areas:
            if ar.spaces.active == self._so:
                ar.tag_redraw()
                break

        OUTLINER_OT_toggle_hide._so = None
        return {'FINISHED'}

    @classmethod
    def register(cls):
        # Register keymaps
        kc = bpy.context.window_manager.keyconfigs.addon.keymaps

        km = kc.get("Object Mode") or kc.new("Object Mode")
        kmi = km.keymap_items.new(cls.bl_idname, 'J', 'PRESS')
        cls._keymaps.append((km, kmi))

        km = kc.get("Outliner") or kc.new("Outliner", space_type='OUTLINER')
        kmi = km.keymap_items.new("outliner.toggle_hide", 'J', 'PRESS')
        cls._keymaps.append((km, kmi))

    @classmethod
    def unregister(cls):
        for km, kmi in cls._keymaps:
            km.keymap_items.remove(kmi)
        cls._keymaps.clear()


def register():
    if version < (2, 83):
        raise AssertionError("Minimum Blender version 2.83 required")
    bpy.utils.register_class(OUTLINER_OT_toggle_hide)

def unregister():
    bpy.utils.unregister_class(OUTLINER_OT_toggle_hide)
