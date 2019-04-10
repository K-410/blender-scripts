from collections import Counter, deque

import bmesh
import bpy
import mathutils
from bgl import (GL_ALWAYS, GL_BLEND, glDepthFunc, glDisable, glEnable,
                 glPointSize)
from gpu.types import GPUShader
from gpu_extras.batch import batch_for_shader

Vector = mathutils.Vector
inv = mathutils.Matrix.inverted
norm = Vector.normalized
dot = Vector.dot

line_plane = mathutils.geometry.intersect_line_plane
point_line = mathutils.geometry.intersect_point_line

# feed this to the gpu batch to stop drawing
def nan_vector(size, freeze=True):
    from mathutils import Vector
    from math import nan
    nan_vec = Vector([nan for i in range(size)])

    if not freeze:
        return nan_vec

    frozen = nan_vec.freeze()
    del nan_vec
    return frozen

# radial search pattern to find proximity geometry
# used in conjunction with bvh.ray_cast
def radial_patterns():
    from math import sin, cos, pi
    points = (16, 16, 16, 18, 20, 22, 22, 24)
    bases = [(r, n) for r, n in enumerate(points, 3)]

    patterns = []
    for r, n in bases:
        t = ((round(cos(2 * pi / n * x) * r),
              round(sin(2 * pi / n * x) * r)) for x in range(n))
        patterns.append(tuple(t))
    return tuple(patterns)

# patterns are fixed per pixels, so store
# on module level for fast retrievance
patterns = radial_patterns()
common = Counter.most_common
vec3_nan = nan_vector(3)


# stripped down higher performance versions of view3d utils
# no mat copy, no clamp, re-arrange calc. values passed as args
# upwards to 30-40% faster execution from my own testing
def origin_3d(rv3d, rw, rh, mx, my):
    if rv3d.is_perspective:
        return inv(rv3d.view_matrix).translation
    dx, dy = -1.0 + mx / rw * 2.0, (2.0 * my / rh) - 1.0
    p = inv(rv3d.perspective_matrix)
    org_start = p.col[0].xyz * dx + p.col[1].xyz * dy + p.translation
    if rv3d.view_perspective != 'CAMERA':
        return org_start - p.col[2].xyz


def vector_3d(rv3d, rw, rh, mx, my):
    if rv3d.is_perspective:
        p = inv(rv3d.perspective_matrix)
        out = Vector((-1.0 + mx / rw * 2.0, (2.0 * my / rh) - 1.0, -0.5))
        w = dot(out, p[3].xyz) + p[3][3]
        return norm(p @ out / w - inv(rv3d.view_matrix).translation).normalized()
    return norm(-inv(rv3d.view_matrix).col[2].xyz).normalized()


def location_3d(rv3d, rw, rh, mx, my, depth):
    vec3 = vector_3d(rv3d, rw, rh, mx, my)
    start = origin_3d(rv3d, rw, rh, mx, my)
    if rv3d.is_perspective:
        view = inv(rv3d.view_matrix).col[2].normalized()
        return line_plane(start, start + vec3, depth, view, 1)
    return point_line(depth, start, start + vec3)[0]


def ray_cast(rc, rv3d, rw, rh, mx, my):
    origin = origin_3d(rv3d, rw, rh, mx, my)
    direction = vector_3d(rv3d, rw, rh, mx, my)
    return rc(origin, direction)[0]


vshader = """
    uniform mat4 ModelViewProjectionMatrix;
    in vec3 pos;

    void main()
    {
        gl_Position = ModelViewProjectionMatrix * vec4(pos, 0.999);
    }
"""

fshader = """
    void main()
    {
        float r = 0.0, delta = 0.0, alpha = 0.0;
        vec2 cxy = 2.0 * gl_PointCoord - 1.0;
        r = dot(cxy, cxy);

        if (r > 1.0) {
            discard;
        }

        gl_FragColor = vec4(1.0, 1.0, 0.0, 1);
    }
"""

shader = GPUShader(vshader, fshader)


def avg_edge_distance(bm):
    return sum([e.calc_length() for e in bm.edges]) / len(bm.edges)


def draw(coords):
    glEnable(GL_BLEND)
    glPointSize(12)
    glDepthFunc(GL_ALWAYS)
    shader.bind()
    batch = batch_for_shader(shader, 'POINTS', {"pos": coords})
    batch.draw(shader)
    glDisable(GL_BLEND)


# return the functions themselves and store on the class
# this removes the need to store the bmesh/bvh, since the functions
# are direct references. not sure of the practical value
def trees(bm, tot_vsel, mat):
    rc = mathutils.bvhtree.BVHTree.FromBMesh(bm).ray_cast
    size = len(bm.verts) - tot_vsel
    verts = ((v.co, v.index) for v in bm.verts if not v.select)
    kd = mathutils.kdtree.KDTree(size)
    insert = kd.insert
    for vco, idx in verts:
        insert(mat @ vco, idx)
    kd.balance()
    return kd.find_range, rc


def search(rc, rv3d, rw, rh, mx, my):
    for p in patterns:
        for x, y in p:
            ret = ray_cast(rc, rv3d, rw, rh, mx + x * 2, my + y * 2)
            if ret:
                return ret
    return ret


class MESH_OT_snap_weld(bpy.types.Operator):
    bl_idname = "mesh.snap_weld"
    bl_label = "Snap Weld"

    def exit(self, context):
        bpy.types.SpaceView3D.draw_handler_remove(
            self.draw_handler, 'WINDOW')
        self.redraw()
        return {'CANCELLED'}

    def register_draw(self, point):
        handler = bpy.types.SpaceView3D.draw_handler_add(
            draw, (point,), 'WINDOW', 'POST_VIEW')
        self.redraw()
        return handler

    @classmethod
    def poll(self, context):
        a = context.mode == 'EDIT_MESH'
        b = context.objects_in_mode_unique_data
        c = [1 for o in b if o.data.total_vert_sel]
        return a and sum(c) is 1

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            mx = event.mouse_region_x
            my = event.mouse_region_y
            rw = self.region.width
            rh = self.region.height

            rc = self.rc
            find = self.find
            buf = self.buf
            push = buf.append

            rv3d = context.region_data
            args = rc, rv3d, rw, rh, mx, my
            hit, found = ray_cast(*args), None

            if hit:
                # store last known hit
                self.last = hit
                found = find(hit, self.range)

            if found:
                closest, idx, dist = found[0]
                if closest != self.last:
                    for i in range(5):
                        # buffer the hit location to induce
                        # hysteresis and keep it from jumping
                        push(closest.freeze())
                    self.last = closest
                self.update(closest)

            else:
                closest = common(Counter(buf), 1)[0][0]
                if closest != self.last:
                    for i in range(5):
                        push(closest)
                    self.last = closest
                self.update(closest)

            if not hit:
                # start radial search around cursor
                args = rc, rv3d, rw, rh, mx, my
                proximity = search(*args)

                if proximity:
                    found = find(proximity, self.range)

                    if found:
                        # semi-duplicate code
                        closest, idx, dist = found[0]
                        push(closest.freeze())
                        c = common(Counter(buf), 1)[0]
                        self.update(c[0])
                else:
                    # push nothing to the buffer.
                    # this hides drawn geometry
                    push(vec3_nan)

            self.redraw()

        if event.type == 'ESC':
            return self.exit(context)

        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        ob = context.object
        mat = ob.matrix_world
        bm = bmesh.from_edit_mesh(ob.data)
        tv = ob.data.total_vert_sel
        
        self.find, self.rc = trees(bm, tv, mat)
        self.range = avg_edge_distance(bm) * 0.5

        # buffer used to stabilize the found points
        self.buf = deque([vec3_nan], maxlen=5)
        self.redraw = context.area.tag_redraw
        self.region = context.region

        # a single point representing a vertex location
        # fed into the gpu bach as coordinate
        point = deque([vec3_nan], maxlen=1)
        self.update = point.append
        self.last = None

        self.draw_handler = self.register_draw(point)

        wm = context.window_manager
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}


def register():
    bpy.utils.register_class(MESH_OT_snap_weld)


if __name__ == '__main__':
    register()
