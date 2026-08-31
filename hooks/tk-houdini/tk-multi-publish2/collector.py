# Copyright (c) 2017 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.


import sgtk
import hou
import os
import sys
import houdini_utils
import common_utils
import glob

HookBaseClass = sgtk.get_hook_baseclass()

# A dict of dicts organized by category, type and output file parm
_HOUDINI_OUTPUTS = {
    # rops
    hou.ropNodeTypeCategory(): {
        "alembic": "filename",  # alembic cache
        "comp": "copoutput",  # composite
        "ifd": "vm_picture",  # mantra render node
        "opengl": "picture",  # opengl render
        "wren": "wr_picture",  # wren wireframe
    },
}


class HoudiniSessionCollector(HookBaseClass):
    """
    Collector that operates on the current houdini session. Should inherit from
    the basic collector hook.
    """

    @property
    def settings(self):
        """
        Dictionary defining the settings that this collector expects to receive
        through the settings parameter in the process_current_session and
        process_file methods.

        A dictionary on the following form::

            {
                "Settings Name": {
                    "type": "settings_type",
                    "default": "default_value",
                    "description": "One line description of the setting"
            }

        The type string should be one of the data types that toolkit accepts as
        part of its environment configuration.
        """

        # grab any base class settings
        collector_settings = super(
            HoudiniSessionCollector, self).settings or {}

        # settings specific to this collector
        houdini_session_settings = {
            "Work Template": {
                "type": "template",
                "default": None,
                "description": "Template path for artist work files. Should "
                "correspond to a template defined in "
                "templates.yml. If configured, is made available"
                "to publish plugins via the collected item's "
                "properties. ",
            },
        }

        # update the base settings with these settings
        collector_settings.update(houdini_session_settings)

        return collector_settings

    def process_current_session(self, settings, parent_item):
        """
        Analyzes the current Houdini session and parents a subtree of items
        under the parent_item passed in.

        :param dict settings: Configured settings for this collector
        :param parent_item: Root item instance
        """
        houdini_utils.sync_frame_range_and_fps()

        # create an item representing the current houdini session
        item = self.collect_current_houdini_session(settings, parent_item)

        # remember if we collect any alembic/mantra nodes
        self._alembic_nodes_collected = False
        self._mantra_nodes_collected = False

        # methods to collect tk alembic/mantra nodes if the app is installed
        self.collect_tk_alembicnodes(item)
        self.collect_tk_mantranodes(item)

        # collect other, non-toolkit outputs to present for publishing
        self.collect_node_outputs(item)
        self.collect_flipbooks(item)
        self._collect_textures(item)
        self._collect_matnet(item)
        self._collect_objnet(item)
        self._collect_camera(item)
        self._collect_camera_fbx(item)
        self._collect_geometry(item)
        self._collect_vdb(item)
        self._collect_rop(item)

    def collect_current_houdini_session(self, settings, parent_item):
        """
        Creates an item that represents the current houdini session.

        :param dict settings: Configured settings for this collector
        :param parent_item: Parent Item instance

        :returns: Item of type houdini.session
        """

        publisher = self.parent

        # get the path to the current file
        path = hou.hipFile.path()

        # determine the display name for the item
        if path:
            file_info = publisher.util.get_file_path_components(path)
            display_name = file_info["filename"]
        else:
            display_name = "Current Houdini Session"

        # create the session item for the publish hierarchy
        session_item = parent_item.create_item(
            "houdini.session", "Houdini File", display_name
        )

        # get the icon path to display for this item
        icon_path = os.path.join(
            self.disk_location, os.pardir, "icons", "houdini.png")
        session_item.set_icon_from_path(icon_path)

        # if a work template is defined, add it to the item properties so that
        # it can be used by attached publish plugins
        work_template_setting = settings.get("Work Template")
        if work_template_setting:
            work_template = publisher.engine.get_template_by_name(
                work_template_setting.value
            )

            # store the template on the item for use by publish plugins. we
            # can't evaluate the fields here because there's no guarantee the
            # current session path won't change once the item has been created.
            # the attached publish plugins will need to resolve the fields at
            # execution time.
            session_item.properties["work_template"] = work_template
            self.logger.debug("Work template defined for Houdini collection.")

        self.logger.info("Collected current Houdini session")
        return session_item

    def collect_node_outputs(self, parent_item):
        """
        Creates items for known output nodes

        :param parent_item: Parent Item instance
        """

        for node_category in _HOUDINI_OUTPUTS:
            for node_type in _HOUDINI_OUTPUTS[node_category]:

                if node_type == "alembic" and self._alembic_nodes_collected:
                    self.logger.debug(
                        "Skipping regular alembic node collection since tk "
                        "alembic nodes were collected. "
                    )
                    continue

                if node_type == "ifd" and self._mantra_nodes_collected:
                    self.logger.debug(
                        "Skipping regular mantra node collection since tk "
                        "mantra nodes were collected. "
                    )
                    continue

                path_parm_name = _HOUDINI_OUTPUTS[node_category][node_type]

                # get all the nodes for the category and type
                nodes = hou.nodeType(node_category, node_type).instances()

                # iterate over each node
                for node in nodes:

                    # get the evaluated path parm value
                    path = node.parm(path_parm_name).eval()

                    # ensure the output path exists
                    if not os.path.exists(path):
                        continue

                    self.logger.info(
                        "Processing %s node: %s" % (node_type, node.path())
                    )

                    # allow the base class to collect and create the item. it
                    # should know how to handle the output path
                    item = super(HoudiniSessionCollector, self)._collect_file(
                        parent_item, path, frame_sequence=True
                    )

                    # the item has been created. update the display name to
                    # include the node path to make it clear to the user how it
                    # was collected within the current session.
                    item.name = "%s (%s)" % (item.name, node.path())

    def collect_flipbooks(self, parent_item):
        """
        Creates items for ffmpeg flipbook.

        :param parent_item: Parent Item instance
        """

        en = sgtk.platform.current_engine()
        ctx = en.context

        entity_type = ctx.entity['type'].lower()
        entity_name = ctx.entity['name']
        task_name = ctx.task['name']

        name = "{}: {}    task: {}".format(entity_type, entity_name, task_name)
        out_movie = hou.expandString("$HIP/flipbook/$HIPNAME.mp4")

        if not os.path.isfile(out_movie):
            return

        movies_dir = os.path.dirname(out_movie)
        self.logger.info(
            "Processing movies folder: %s" % (movies_dir,),
            extra={"action_show_folder": {"path": movies_dir}},
        )

        # allow the base class to collect and create the item. it knows how
        # to handle movie files
        item = super(HoudiniSessionCollector, self)._collect_file(
            parent_item, out_movie
        )

        # the item has been created. update the display name to include
        # the an indication of what it is and why it was collected

        item.name = "%s (%s)" % (item.name, "flipbook")

    def _collect_matnet(self, parent_item):
        """
        """

        eng = sgtk.platform.current_engine()
        ctx = eng.context

        if ctx.entity['type'] == 'Shot':
            for matnet in hou.node("/shop").children():

                if matnet.type().name() != 'matnet':
                    continue

                if not houdini_utils.is_publish_matnet(matnet):
                    continue

                matnet_path = matnet.path()
                item = parent_item.create_item(
                    "houdini.matnet", "Materials", matnet_path)
                item.properties["node"] = matnet_path

                # get the icon path to display for this item
                icon_path = self._icons_dir() + "/matnet.svg"

                item.set_icon_from_path(icon_path)
                item.name = matnet_path

            return

        if ctx.entity['type'] != 'Asset':
            return

        if not ctx.step or ctx.step['name'] != 'Surface':
            return

        asset_name = eng.context.entity['name']
        matnet = hou.node('/shop/' + asset_name)
        if not matnet:
            return

        matnet_path = matnet.path()
        item = parent_item.create_item(
            "houdini.matnet", "Materials", matnet_path)
        item.properties["node"] = matnet_path

        # get the icon path to display for this item
        icon_path = self._icons_dir() + "/matnet.svg"

        item.set_icon_from_path(icon_path)
        item.name = matnet_path

    def _collect_textures(self, parent_item):
        """
        """

        en = sgtk.platform.current_engine()
        ctx = en.context
        if ctx.entity['type'] != 'Asset':
            return

        if not ctx.step or ctx.step['name'] != 'Texture':
            return

        asset_name = en.context.entity['name']
        matnet = hou.node('/shop/' + asset_name)
        if not matnet:
            return

        work_template = en.get_template_by_name("work_asset_texture")
        textures = set()

        def _add_tex(node):
            for p in node.parms():
                if not isinstance(p.parmTemplate(), hou.StringParmTemplate):
                    continue

                texpath = p.eval().replace('%(UDIM)d', '<UDIM>')

                if work_template.validate(texpath):
                    textures.add(texpath)

        for node in matnet.children():
            _add_tex(node)
            ntc = node.childTypeCategory()

            if (not node.isLockedHDA()) and ntc and ntc.name() == 'Vop':
                for n in node.children():
                    _add_tex(n)

        for tex in list(textures):
            item = parent_item.create_item(
                "Texture", "Texture", tex)
            item.properties["path"] = tex

            item.properties["work_template"] = work_template

            seq_files = common_utils.seq_files(tex, seq_pattern='<UDIM>')
            if seq_files:
                item.properties["sequence_paths"] = seq_files
                first = seq_files[0]
            else:
                first = tex

            if (not first) or tex.endswith('.exr'):
                icon_path = self._icons_dir() + "/texture.png"
            else:
                icon_path = first

            if first:
                item.set_thumbnail_from_path(first)

                # disable thumbnail creation since we get it for free
                # item.thumbnail_enabled = False

            item.set_icon_from_path(icon_path)

            item.name = os.path.basename(tex).replace('<UDIM>', '####')

    def _collect_objnet(self, parent_item):
        """
        """

        for node in hou.node("/obj").children():
            if not houdini_utils.is_publish_objnet(node):
                continue
            # sys.stderr.write("{0}\n".format(node.path()))
            geo_item = parent_item.create_item(
                "houdini.objnet", "Object Network", node.path()
            )
            geo_item.properties["node"] = node.path()

            # get the icon path to display for this item
            icon_path = self._icons_dir() + "/subnet.svg"

            geo_item.set_icon_from_path(icon_path)
            geo_item.name = node.path()

    def _collect_camera(self, parent_item):
        """
        Creates items for session camera to be exported.

        :param parent_item: Parent Item instance
        """

        # * collect all checked objects in scene for publishing
        for node in hou.node("/obj").children():
            if not houdini_utils.is_publish_alembic_camera(node):
                continue

            node_path = node.path()
            cam_path = node_path
            cam_node = houdini_utils.search_camera(node)
            if not cam_node:
                continue
            cam_path = cam_node.path()

            geo_item = parent_item.create_item(
                "houdini.session.camera", "Alembic Camera", node_path
            )
            geo_item.properties["camera"] = cam_path
            geo_item.properties["node"] = node.path()

            try:
                geo_item.properties["preroll"] = node.evalParm(
                    "preroll")
            except:
                geo_item.properties["preroll"] = 0
            try:
                geo_item.properties["samples"] = node.evalParm(
                    "samples")
            except:
                geo_item.properties["samples"] = 1
            try:
                geo_item.properties["units"] = node.evalParm(
                    "units")
            except:
                geo_item.properties["units"] = 'centimeters'
            # get the icon path to display for this item
            icon_path = self._icons_dir() + "/camera.png"

            geo_item.set_icon_from_path(icon_path)
            geo_item.name = "{0}.abc ({1})".format(node.name(), cam_path)

    def _collect_camera_fbx(self, parent_item):
        """
        Creates items for session camera to be exported.

        :param parent_item: Parent Item instance
        """

        # * collect all checked objects in scene for publishing
        for node in hou.node("/obj").children():
            if not houdini_utils.is_publish_fbx_camera(node):
                continue

            node_path = node.path()
            cam_path = node_path
            cam_node = houdini_utils.search_camera(node)
            if not cam_node:
                continue
            cam_path = cam_node.path()

            geo_item = parent_item.create_item(
                "houdini.session.camera.fbx", "FBX Camera", node_path
            )
            geo_item.properties["camera"] = cam_path
            geo_item.properties["node"] = node.path()

            try:
                geo_item.properties["preroll"] = node.evalParm(
                    "preroll")
            except:
                geo_item.properties["preroll"] = 0
            try:
                geo_item.properties["samples"] = node.evalParm(
                    "samples")
            except:
                geo_item.properties["samples"] = 1
            try:
                geo_item.properties["units"] = node.evalParm(
                    "units")
            except:
                geo_item.properties["units"] = 'centimeters'
            # get the icon path to display for this item
            icon_path = self._icons_dir() + "/camera.png"

            geo_item.set_icon_from_path(icon_path)
            geo_item.name = "{0}.fbx ({1})".format(node.name(), cam_path)

    def _collect_geometry(self, parent_item):
        """
        Creates items for session geometry to be exported.

        :param parent_item: Parent Item instance
        """

        # * collect all checked objects in scene for publishing
        for node in hou.node("/obj").children():
            if not houdini_utils.is_publish_alembic(node):
                continue
            # sys.stderr.write("{0}\n".format(node.path()))
            geo_item = parent_item.create_item(
                "houdini.session.geometry", "Geometry", node.path()
            )
            geo_item.properties["node"] = node.path()

            try:
                geo_item.properties["preroll"] = node.evalParm(
                    "preroll")
            except:
                geo_item.properties["preroll"] = 0
            try:
                geo_item.properties["samples"] = node.evalParm(
                    "samples")
            except:
                geo_item.properties["samples"] = 1
            try:
                geo_item.properties["units"] = node.evalParm(
                    "units")
            except:
                geo_item.properties["units"] = 'centimeters'
            # get the icon path to display for this item
            icon_path = self._icons_dir() + "/alembic.png"

            geo_item.set_icon_from_path(icon_path)
            geo_item.name = "{0}.abc ({1})".format(node.name(), node.path())

    def _collect_vdb(self, parent_item):
        """
        Creates items for session geometry to be exported.

        :param parent_item: Parent Item instance
        """
        filecache_type = hou.nodeType("Sop/filecache::2.0")
        for node in filecache_type.instances():
            filename = node.evalParm("sopoutput")
            basename, ext = os.path.splitext(filename)
            if ext.lower() != ".vdb":
                continue

            geo_item = parent_item.create_item(
                "houdini.session.vdb", "VDB", node.path()
            )
            geo_item.properties["node"] = node.path()

            icon_path = self._icons_dir() + "/openvdb.svg"

            geo_item.set_icon_from_path(icon_path)
            geo_item.name = "{0}.vdb ({1})".format(node.name(), node.path())

    def _collect_rop(self, parent_item):
        """
        Creates items for rops to be exported.

        :param parent_item: Parent Item instance
        """
        rop_node = hou.node("/out/beauty")
        if not rop_node:
            return

        roptype = rop_node.type()
        if roptype == 'ifd':
            filename = rop_node.evalParm("vm_picture")
        elif roptype == 'Redshift_ROP':
            filename = rop_node.evalParm("RS_outputFileNamePrefix")
        try:
            basename, ver, frame, ext = filename.rsplit(filename, ".", 3)
        except:
            return

        if ext.lower() != "exr":
            return

        dirname, basename = os.path.split(basename)
        seq_basename = f"{basename}.{ver}.%04d.{ext}"
        seq_filename = f"{dirname}/{seq_basename}"

        rop_item = parent_item.create_item(
            "houdini.session.render", "Rendered Sequence", seq_filename
        )

        mov_dir = "/".join(seq_filename.split("/")[:-3])

        mov_filename = f"{mov_dir}/{basename}.mp4"

        rop_item.properties["filename"] = seq_filename
        rop_item.properties["movname"] = mov_filename

        icon_path = self._icons_dir() + "/image_sequence.png"

        rop_item.set_icon_from_path(icon_path)
        rop_item.name = seq_basename

    def collect_tk_alembicnodes(self, parent_item):
        """
        Checks for an installed `tk-houdini-alembicnode` app. If installed, will
        search for instances of the node in the current session and create an
        item for each one with an output on disk.

        :param parent_item: The item to parent new items to.
        """

        publisher = self.parent
        engine = publisher.engine

        alembicnode_app = engine.apps.get("tk-houdini-alembicnode")
        if not alembicnode_app:
            self.logger.debug(
                "The tk-houdini-alembicnode app is not installed. "
                "Will not attempt to collect those nodes."
            )
            return

        try:
            tk_alembic_nodes = alembicnode_app.get_nodes()
        except AttributeError:
            self.logger.warning(
                "Unable to query the session for tk-houdini-alembicnode "
                "instances. It looks like perhaps an older version of the "
                "app is in use which does not support querying the nodes. "
                "Consider updating the app to allow publishing their outputs."
            )
            return

        # retrieve the work file template defined by the app. we'll set this
        # on the collected alembicnode items for use during publishing.
        work_template = alembicnode_app.get_work_file_template()

        for node in tk_alembic_nodes:

            out_path = alembicnode_app.get_output_path(node)

            if not os.path.exists(out_path):
                continue

            self.logger.info("Processing sgtk_alembic node: %s" %
                             (node.path(),))

            # allow the base class to collect and create the item. it
            # should know how to handle the output path
            item = super(HoudiniSessionCollector, self)._collect_file(
                parent_item, out_path
            )

            # the item has been created. update the display name to
            # include the node path to make it clear to the user how it
            # was collected within the current session.
            item.name = "%s (%s)" % (item.name, node.path())

            if work_template:
                item.properties["work_template"] = work_template

            self._alembic_nodes_collected = True

    def collect_tk_mantranodes(self, parent_item):
        """
        Checks for an installed `tk-houdini-mantranode` app. If installed, will
        search for instances of the node in the current session and create an
        item for each one with an output on disk.

        :param parent_item: The item to parent new items to.
        """

        publisher = self.parent
        engine = publisher.engine

        mantranode_app = engine.apps.get("tk-houdini-mantranode")
        if not mantranode_app:
            self.logger.debug(
                "The tk-houdini-mantranode app is not installed. "
                "Will not attempt to collect those nodes."
            )
            return

        try:
            tk_mantra_nodes = mantranode_app.get_nodes()
        except AttributeError:
            self.logger.warning(
                "Unable to query the session for tk-houdini-mantranode "
                "instances. It looks like perhaps an older version of the "
                "app is in use which does not support querying the nodes. "
                "Consider updating the app to allow publishing their outputs."
            )
            return

        # retrieve the work file template defined by the app. we'll set this
        # on the collected alembicnode items for use during publishing.
        work_template = mantranode_app.get_work_file_template()

        for node in tk_mantra_nodes:

            out_path = mantranode_app.get_output_path(node)

            if not os.path.exists(out_path):
                continue

            self.logger.info("Processing sgtk_mantra node: %s" %
                             (node.path(),))

            # allow the base class to collect and create the item. it
            # should know how to handle the output path
            item = super(HoudiniSessionCollector, self)._collect_file(
                parent_item, out_path, frame_sequence=True
            )

            # the item has been created. update the display name to
            # include the node path to make it clear to the user how it
            # was collected within the current session.
            item.name = "%s (%s)" % (item.name, node.path())

            if work_template:
                item.properties["work_template"] = work_template

            self._mantra_nodes_collected = True

    def _icons_dir(self):
        return os.path.join(self.disk_location, os.pardir, os.pardir, os.pardir, "icons")
