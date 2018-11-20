# Local Scene is a (simple) substitute for missing Local Mode in Blender 2.80
#
#
# Current limitations:
# -   Cannot have multiple Local Scenes. Local Scene gets applied in all viewports
# -   Viewport label (eg. User Perspective) doesn't reflect being in "Local Scene" mode
# -   Restore View setting doesn't cannot use smooth view (yet)
# -   Deleting an object in Local Scene does not delete it from the original scene unless it was created in Local Scene
# -   Creating new objects in Local Scene automatically links them to the original 
# -   Local Scene "state" is saved along the file.
#   scene when Local Scene is removed
#
#TODO
# Create a "Local Scene" collection for objects for organizational and visual feedback in Outliner

import bpy, blf
from bpy.props          import *
from mathutils          import Matrix
from bpy.app.handlers   import persistent

bl_info = {
    "name":         "Local Scene",
    "description":  "Add a Local Scene mode that isolates selection to a new scene "
                    "called 'Local Scene'. A substitute for missing Local Mode",
    "author":       "iceythe",
    "version":      (1, 0, 0),
    "blender":      (2, 80, 0),
    "location":     "In 3D View, Alt-Q hotkey",
    "category":     "3D View",
}

C   = bpy.context
D   = bpy.data
local_coll  = [] # Store local scene collection

def delete_scene(scn):
    local_scn   = bpy.data.scenes[scn]
    objs        = local_scn.collection.objects
    if objs:
        local_coll.clear()
        for obj in objs:
            local_coll.append(obj)
    bpy.data.scenes.remove(bpy.data.scenes[scn])

def def_colls():
    return [coll for coll in bpy.data.collections]

@persistent
def local_scene_handler(dummy):                 # POST LOAD
    print("post_load handler was triggered")
    dns     = bpy.app.driver_namespace
    dns['vpt_size'] = 16
    if 'Local Scene' in bpy.context.scene.name:
        bpy.ops.view3d.local_scene_text(state=True)
    print("Handle 'load_handler_isolate' is working")

def get_handler(arg):                       # Return a list of handlers
    assert arg == 'POST' or 'PRE'
    handler_list = []
    if arg == 'POST':
        for h in bpy.app.handlers.load_post:
            if h.__name__ == 'local_scene_handler':
                handler_list.append(h)
        return handler_list
    elif arg == 'PRE':
        for h in bpy.app.handlers.load_pre:
            if h.__name__ == 'local_scene_load_pre':
                handler_list.append(h)
        return handler_list
    return []


@persistent
def local_scene_load_pre(dummy):                # PRE LOAD
    print("pre_load handler was triggered")
    bpy.ops.view3d.local_scene_text(state=False)
    # local_scene_remove_handlers()


def add_handlers():                             # Get current list of Local Scene handlers
    if not get_handler('POST'):
        bpy.app.handlers.load_post.append(local_scene_handler)
    if not get_handler('PRE'):
        bpy.app.handlers.load_pre.append(local_scene_load_pre)


def local_scene_remove_handlers():         # Clear any handlers added by the addon
    if get_handler('POST'):
        for h in get_handler('POST'):
            bpy.app.handlers.load_post.remove(h)
    if get_handler('PRE'):
        for h in get_handler('PRE'):
            bpy.app.handlers.load_pre.remove(h)


class LocalScene(bpy.types.Operator):
    """Isolates selection to a new scene"""
    bl_idname   = "view3d.local_scene_mode"
    bl_label    = "Local Scene"
    bl_options  = {'REGISTER'}
    
    # Booleans
    # copy_scene:     BoolProperty(name='Copy scene settings', default=True)
    # view_selected:  BoolProperty(name='View Selected', default=True)
    # restore_view:   BoolProperty(name='Restore View', default=True)
    view_selected   = True
    copy_scene      = True
    restore_view    = True

    # Internal
    default_scene:  StringProperty(name='Scene', default='Scene')
    local_scene:    StringProperty(name='Local Scene Name', default='Local Scene')
    view_matrix:    FloatVectorProperty(name='View Matrix', subtype='MATRIX', default=(0,0,0))
    view_location:  FloatVectorProperty(name='View Location')
    view_distance:  FloatProperty(name='View Distance', default=10)


    def restore_scene(self, context):
        D = bpy.data
        bpy.ops.view3d.local_scene_text(state=False)
        if not self.default_scene in D.scenes:
            context.window.scene = D.scenes[0]
            bpy.ops.view3d.local_scene_text(state=False)
        else:
            context.window.scene = D.scenes[self.default_scene]
            if local_coll:
                for obj in local_coll:
                    if not obj.name in bpy.data.scenes[self.default_scene].objects:
                        if not obj.name in bpy.data.scenes[self.default_scene].collection.objects:
                            context.scene.collection.objects.link(obj)
                local_coll.clear()
        
    def view_selected_fn(self, context):
        if self.view_selected:
            mode    = context.mode
            O       = bpy.ops
            O.object.editmode_toggle() if 'EDIT_MESH' in mode else None
            O.view3d.view_selected('INVOKE_DEFAULT', False)
            O.object.editmode_toggle() if 'EDIT_MESH' in mode else None

    def store_view_fn(self, context):
        r3d = context.region_data
        context.scene['view_matrix']    = r3d.view_matrix # Store view matrix 
        self.view_distance              = r3d.view_distance # Store view_distance -- camera <--> look-at point
        self.view_location              = r3d.view_location # Store view_location -- (camera?,look-at?) location here

    def restore_view_fn(self, context):
        r3d                 = context.region_data
        r3d.view_matrix     = Matrix(context.scene['view_matrix']) #return mat
        r3d.view_distance   = self.view_distance # Restore view_distance
        r3d.view_location   = self.view_location # Restore view_location
    
    def link_objs(self, context, objs, scn):
        for obj in objs:
            scn.collection.objects.link(obj)

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def execute(self, context):
        C   = bpy.context
        D   = bpy.data
        O   = bpy.ops

        # Delete Local Scene code starts here
        scn = self.local_scene

        if scn in bpy.data.scenes:
            delete_scene(scn)
            self.restore_scene(context)

            if self.restore_view:
                self.restore_view_fn(context) # Restore view


        # Create Local Scene code starts here
        else:
            bpy.ops.view3d.local_scene_text(state=True)
            selection = C.selected_objects, C.object
            if any(selection): # Check if anything is selected
                if self.restore_view:
                    self.store_view_fn(context) # Store View
                self.default_scene = C.scene.name
                
                local_coll = []
                for obj in C.selected_objects:
                    local_coll.append(obj)
                ao = C.active_object
                if ao:
                    if not ao in local_coll:
                        local_coll.append(ao)

                if not C.selected_objects and C.object:
                    C.object.select_set(True)
                    self.view_selected_fn(context)
                    C.object.select_set(False)
                else:
                    self.view_selected_fn(context)

                if self.copy_scene: # Check if 'Copy Settings' is True
                    bpy.ops.scene.new(type='EMPTY')
                    local_scn, local_scn.name = C.scene, 'Local Scene'
                else:
                    local_scn       = D.scenes.new('Local Scene')
                    C.window.scene  = local_scn
                
                self.link_objs(context, local_coll, local_scn)

                for obj in C.view_layer.objects:
                    obj.select_set(True)
                C.view_layer.objects.active = ao
        return {'FINISHED'}



class LocalSceneViewportText(bpy.types.Operator):
    bl_idname   = "view3d.local_scene_text"
    bl_label    = "Local Scene Viewport Text"
    bl_options  = {'REGISTER'}
    
    state:      bpy.props.BoolProperty(name='State', default=False)
    font_size:  bpy.props.IntProperty(name='Font Size', description='Viewport fpmt size', default=16)
    vpt         = "local_scene_handler"
    handle      = None
    
    def execute(self, context):
        sv3d        = bpy.types.SpaceView3D
        state       = self.state
        dns         = bpy.app.driver_namespace
        vpt         = self.vpt
        vpt_size	= self.font_size

        if state:
            self.remove_handler(self)                   # Clear handlers as precaution
            dns['vpt_size'] = self.font_size	        # Set font size before adding handler

            self.handle = sv3d.draw_handler_add(
                self.draw_callback, (None, None), 
                'WINDOW', 'POST_PIXEL')

            dns[self.vpt] = self.handle	                # Store handle RNA in driver namespace
            self.refresh(context)                       # Update viewports
        else:
            self.remove_handler(self)
        return {'FINISHED'}
    
    def remove_handler(self, context):
        vpt     = self.vpt
        dns     = bpy.app.driver_namespace
        if vpt in dns:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(dns[vpt], 'WINDOW')
            except:
                print("Local Scene Addon: No handler found")
            del dns[vpt]
        self.refresh(context)
    
    def refresh(self, context):
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        bpy.context.scene.update()

    @staticmethod
    def draw_callback(self, context):
        """
        Draw Local Scene state in viewport
        """
        dns         = bpy.app.driver_namespace
        area        = bpy.context.area
        font_size   = 16 #dns['vpt_size']
        font_id     = 0
        string      = "Local Scene"
        bottom      = False
        center      = True
        pos_y       = 20 if bottom else area.height - 50

        if center:
            c = area.width / 2
            f = blf.dimensions(font_id, string)[0] / 2
            pos_x = int(c - f)

        blf.position(font_id, pos_x, pos_y, 0)
        blf.size(font_id, font_size, 72)
        blf.draw(font_id, string)
        blf.disable(font_id, 2)


class LocalSceneAddonPreferences(bpy.types.PropertyGroup):

    vpt_text: StringProperty(
        name='Viewport Text', default='Local Scene',
        description='Text to show when Local Scene is active')

    vpt_size: IntProperty(
        name='Font Size', default=16,
        description='Font size for viewport text')

    # vpt_location: CollectionProperty(

    # )

    copy_scene: BoolProperty(
        name='Copy Scene Settings', default=True,
        description='Use same scene settings for Local Scene as the original')

    view_selected: BoolProperty(
        name='Use View Selected', default=True,
        description='Use View Selected when entering Local Scene')

    restore_view: BoolProperty(
        name='Restore Views', default=True,
        description='Restore views when exiting Local Scene')

addon_keymaps = []
classes = [LocalScene, LocalSceneViewportText]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    wm      = bpy.context.window_manager
    km      = wm.keyconfigs.addon.keymaps.new(name='3D View', space_type='VIEW_3D')
    kmi     = km.keymap_items.new(LocalScene.bl_idname, 'Q', 'PRESS', alt=True)
    addon_keymaps.append((km, kmi))
    print("Running add_handlers()")
    add_handlers()
    print("Local Scene Addon: Successfully registered")

def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)

    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()
    local_scene_remove_handlers()
    print("Local Scene Addon: Successfully unregistered")

if __name__ == "__main__":
    register()