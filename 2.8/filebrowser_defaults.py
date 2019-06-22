import bpy

bl_info = {
    "name": "File Browser Defaults",
    "description": "Set view settings in the file browser once, ever.",
    "author": "kaio",
    "version": (1, 0, 0),
    "blender": (2, 80, 0),
    "location": "File Browser",
    "category": "File Browser"}


class FileBrowserDefaults(bpy.types.AddonPreferences):
    bl_idname = __name__
    EnumProperty = bpy.props.EnumProperty

    _sort_methods = (
        ('FILE_SORT_ALPHA', 'Alphabetically', 'SORTALPHA', 1),
        ('FILE_SORT_EXTENSION', 'File Type', 'SORTBYEXT', 2),
        ('FILE_SORT_TIME', 'Date', 'SORTTIME', 3),
        ('FILE_SORT_SIZE', 'File Size', 'SORTSIZE', 4))

    _display_types = (
        ('LIST_SHORT', 'Short List', 'SHORTDISPLAY', 1),
        ('LIST_LONG', 'Long List', 'LONGDISPLAY', 2),
        ('THUMBNAIL', 'Thumbnails', 'IMGDISPLAY', 3))

    _display_sizes = (
        ('TINY', 'Tiny', '', 1),
        ('SMALL', 'Small', '', 2),
        ('NORMAL', 'Regular', '', 3),
        ('LARGE', 'Large', '', 4))

    sort_method: EnumProperty(
        name="Sort Method", items=_sort_methods, default='FILE_SORT_TIME')
    display_type: EnumProperty(
        name="Display Type", items=_display_types, default='LIST_SHORT')
    display_size: EnumProperty(
        name="Display Size", items=_display_sizes, default='SMALL')

    del EnumProperty

    @staticmethod
    def set_defaults(header, context):
        addons = context.preferences.addons
        prefs = addons[__name__].preferences

        if hasattr(context.space_data, 'params'):
            params = context.space_data.params

            sort_method = prefs.sort_method
            display_type = prefs.display_type
            display_size = prefs.display_size

            if params.sort_method != sort_method:
                setattr(params, 'sort_method', sort_method)

            if params.display_type != display_type:
                setattr(params, 'display_type', display_type)

            if params.display_size != display_size:
                setattr(params, 'display_size', display_size)

    # not useful to display these
    # def draw(self, context):
    #     layout = self.layout

    #     layout.prop(self, "sort_method")
    #     layout.prop(self, "display_type")
    #     layout.prop(self, "display_size")

    @classmethod
    def _setup(cls):
        bpy.types.FILEBROWSER_HT_header.append(cls.set_defaults)

    @classmethod
    def _remove(cls):
        bpy.types.FILEBROWSER_HT_header.remove(cls.set_defaults)


class FILEBROWSER_HT_header(bpy.types.Header):
    bl_space_type = 'FILE_BROWSER'

    def draw(self, context):
        layout = self.layout

        st = context.space_data
        params = st.params

        if st.active_operator is None:
            layout.template_header()

        layout.menu("FILEBROWSER_MT_view")

        row = layout.row(align=True)
        row.operator("file.previous", text="", icon='BACK')
        row.operator("file.next", text="", icon='FORWARD')
        row.operator("file.parent", text="", icon='FILE_PARENT')
        row.operator("file.refresh", text="", icon='FILE_REFRESH')

        layout.operator_context = 'EXEC_DEFAULT'
        layout.operator("file.directory_new", icon='NEWFOLDER', text="")

        layout.operator_context = 'INVOKE_DEFAULT'

        # can be None when save/reload with a file selector open
        if params:
            is_lib_browser = params.use_library_browsing

            # XXX -------- edit start
            p_new = context.preferences.addons[__name__].preferences

            row = layout.row(align=True)
            for val, name, icon, idx in p_new._display_types:
                row.prop_enum(p_new, "display_type", val, text="", icon=icon)

            row = layout.row(align=True)
            for val, name, icon, idx in p_new._sort_methods:
                row.prop_enum(p_new, "sort_method", val, text="", icon=icon)

            # XXX -------- edit end
            layout.prop(params, "show_hidden", text="", icon='FILE_HIDDEN')

        layout.separator_spacer()

        layout.template_running_jobs()

        if params:
            layout.prop(params, "use_filter", text="", icon='FILTER')

            row = layout.row(align=True)
            row.active = params.use_filter
            row.prop(params, "use_filter_folder", text="")

            if params.filter_glob:
                # if st.active_operator and hasattr(st.active_operator, "filter_glob"):
                #     row.prop(params, "filter_glob", text="")
                row.label(text=params.filter_glob)
            else:
                row.prop(params, "use_filter_blender", text="")
                row.prop(params, "use_filter_backup", text="")
                row.prop(params, "use_filter_image", text="")
                row.prop(params, "use_filter_movie", text="")
                row.prop(params, "use_filter_script", text="")
                row.prop(params, "use_filter_font", text="")
                row.prop(params, "use_filter_sound", text="")
                row.prop(params, "use_filter_text", text="")

            if is_lib_browser:
                row.prop(params, "use_filter_blendid", text="")
                if params.use_filter_blendid:
                    row.separator()
                    row.prop(params, "filter_id_category", text="")

            row.separator()
            row.prop(params, "filter_search", text="", icon='VIEWZOOM')


class FILEBROWSER_MT_view(bpy.types.Menu):
    bl_label = "View"

    def draw(self, context):
        layout = self.layout
        st = context.space_data
        params = st.params

        # XXX -------- edit start
        addons = context.preferences.addons
        params_new = addons[__name__].preferences

        layout.prop_menu_enum(params_new, "display_size")
        # XXX -------- edit end
        layout.prop_menu_enum(params, "recursion_level")

        layout.separator()

        layout.menu("INFO_MT_area")


classes = (
    FILEBROWSER_HT_header,
    FILEBROWSER_MT_view,
    FileBrowserDefaults)

orig_cls = (
    bpy.types.FILEBROWSER_HT_header,
    bpy.types.FILEBROWSER_MT_view)


def register():
    for cls in orig_cls:
        bpy.utils.unregister_class(cls)

    for cls in classes:
        bpy.utils.register_class(cls)
        if hasattr(cls, '_setup'):
            cls._setup()


def unregister():
    for cls in reversed(classes):
        if hasattr(cls, '_remove'):
            cls._remove()
        bpy.utils.unregister_class(cls)

    for cls in reversed(orig_cls):
        bpy.utils.register_class(cls)
