import bpy, math, mathutils


bl_info = {
    "name": "Rotate OpenGL Lights",
    "description": "A modal operator for rotating the OpenGL solid "
                   "lights in 3D view.",
    "author": "iceythe",
    "version": (1, 0, 0),
    "wiki_url": "https://github.com/iceythe/blender-scripts",
    "blender": (2, 79, 4),
    "location": "3D View > Shift + RMB (default)",
    "category": "3D View",
}


class RotateOpenGLLights(bpy.types.Operator):
    """Rotates the OpenGL solid lights"""
    bl_idname = "view3d.rotate_opengl_lights"
    bl_label = "Rotate OpenGL Lights"
    bl_options = {'REGISTER', 'GRAB_CURSOR', 'BLOCKING'}
    
    lights = bpy.context.user_preferences.system.solid_lights
    lights_state = bpy.props.BoolVectorProperty(default=(True, False, False),
    name='Lights', description='Lights to rotate', options={'HIDDEN'})
    
    rotate_sens = bpy.props.FloatProperty(options={'HIDDEN'}, name='Sensitivity',
    description='Mouse rotation sensitivity', default=.5, min=0.01, max=1.0)
    
    mx = bpy.props.IntProperty(description='Internal use', options={'HIDDEN'})
    my = bpy.props.IntProperty(description='Internal use', options={'HIDDEN'})
    
    escape_keys = set(('RET', 'ESC', 'SPACE', 'LEFTMOUSE', 'MIDDLEMOUSE', 'RIGHTMOUSE',
                       'BUTTON4MOUSE','BUTTON5MOUSE', 'BUTTON6MOUSE', 'BUTTON7MOUSE',
                       'ACTIONMOUSE', 'SELECTMOUSE', 'WHEELINMOUSE', 'WHEELOUTMOUSE', ))
        
        
    def cursor_state(self, context, event, type):
        if type == 'RESTORE':
            context.window.cursor_warp(self.mx, self.my)
            context.window.cursor_modal_restore()
        elif type == 'HIDE':
            self.mx, self.my = event.mouse_x, event.mouse_y
            context.window.cursor_modal_set("NONE")


    def modal(self, context, event):
        dx = event.mouse_x - event.mouse_prev_x
        rad = math.radians (dx * self.rotate_sens)
        q = mathutils.Quaternion((0, 1, 0), rad)
        
        for light, state in zip(self.lights, self.lights_state):
            light.direction.rotate(q) if state else None
                
        if True in (True for k in self.escape_keys if k in event.type):
            self.cursor_state(context, event, 'RESTORE')
            return {'FINISHED'}
        
        return {'RUNNING_MODAL'}
    
    
    def invoke(self, context, event):
        if context.area.type == 'VIEW_3D':
            self.cursor_state(context, event, 'HIDE')
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        return {'CANCELLED'}


addon_keymaps = []


def register():
    bpy.utils.register_class(RotateOpenGLLights)
    wm = bpy.context.window_manager
    km = wm.keyconfigs.addon.keymaps.new(name='3D View', space_type='VIEW_3D')
    kmi = km.keymap_items.new(RotateOpenGLLights.bl_idname, 'RIGHTMOUSE', 'PRESS', shift=True)
    addon_keymaps.append((km, kmi))


def unregister():
    bpy.utils.unregister_class(RotateOpenGLLights)
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()


if __name__ == "__main__":
    register()
