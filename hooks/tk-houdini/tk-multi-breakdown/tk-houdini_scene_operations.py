# Copyright (c) 2013 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import os
import sys

from tank import Hook

import hou
import houdini_utils
from houdini_utils import set_comment
from common_utils import datetime_str, project_field_value


class BreakdownSceneOperations(Hook):
    """
    Breakdown operations for Houdini.

    This implementation handles detection of alembic node paths.
    """

    def scan_scene(self):
        """
        The scan scene method is executed once at startup and its purpose is
        to analyze the current scene and return a list of references that are
        to be potentially operated on.

        The return data structure is a list of dictionaries. Each scene reference
        that is returned should be represented by a dictionary with three keys:

        - "node": The name of the 'node' that is to be operated on. Most DCCs have
          a concept of a node, path or some other way to address a particular
          object in the scene.
        - "type": The object type that this is. This is later passed to the
          update method so that it knows how to handle the object.
        - "path": Path on disk to the referenced object.

        Toolkit will scan the list of items, see if any of the objects matches
        any templates and try to determine if there is a more recent version
        available. Any such versions are then displayed in the UI as out of date.
        """

        items = []

        # get a list of all regular lembic nodes in the file
        alembic_nodes = hou.nodeType(
            hou.sopNodeTypeCategory(), "alembic").instances()

        # return an item for each alembic node found. the breakdown app will check
        # the paths of each looking for a template match and a newer version.
        for alembic_node in alembic_nodes:

            file_parm = alembic_node.parm("fileName")
            file_path = os.path.normpath(file_parm.eval())

            items.append(
                {"node": alembic_node.path(), "node_name": alembic_node.path(
                ), "type": "alembic",  "node_type": "alembic", "path": file_path}
            )

        # Alembic Camera
        alembic_camera_nodes = houdini_utils.node_type_instances(
            hou.objNodeTypeCategory(), "wg::alembic_camera::*")

        for alembic_camera_node in alembic_camera_nodes:

            file_parm = alembic_camera_node.parm("fileName")
            file_path = os.path.normpath(file_parm.eval())

            items.append(
                {"node": alembic_camera_node.path(), "node_name": alembic_camera_node.path(), "type": "alembic_camera", "node_type": "alembic_camera",
                 "path": file_path}
            )

        # FBX Character
        kinefx__fbxcharacterimport_type = hou.nodeType(
            hou.sopNodeTypeCategory(), "kinefx::fbxcharacterimport")
        fbxcharacterimport_type = hou.nodeType(
            hou.sopNodeTypeCategory(), "fbxcharacterimport")
        custom_fbxcharacterimport_type = hou.nodeType(
            hou.sopNodeTypeCategory(), "custom_fbxcharacterimport")

        fbxcharacterimport_nodes = []
        if kinefx__fbxcharacterimport_type:
            fbxcharacterimport_nodes += list(
                kinefx__fbxcharacterimport_type.instances())
        if fbxcharacterimport_type:
            fbxcharacterimport_nodes += list(
                fbxcharacterimport_type.instances())
        if custom_fbxcharacterimport_type:
            fbxcharacterimport_nodes += list(
                custom_fbxcharacterimport_type.instances())

        fbxcharacterimport_nodes = tuple(set(fbxcharacterimport_nodes))
        for fbxcharacterimport_node in fbxcharacterimport_nodes:

            file_parm = fbxcharacterimport_node.parm("fbxfile")
            file_path = os.path.normpath(file_parm.eval())

            items.append(
                {"node": fbxcharacterimport_node.path(), "node_name": fbxcharacterimport_node.path(), "type": "fbx_character", "node_type": "fbx_character",
                 "path": file_path}
            )

        # Material Network
        for matnet_node in hou.node('/shop').children():
            if matnet_node.type().name() != 'matnet':
                continue
            if matnet_node.comment().strip().startswith('#'):
                continue
            try:
                file_parm = matnet_node.parm("network_filename")
                file_path = os.path.normpath(file_parm.eval())
            except:
                continue

            items.append(
                {"node": matnet_node.path(),  "node_name": matnet_node.path(), "type": "matnet", "node_type": "matnet",
                 "path": file_path}
            )

        # Object Network
        for objnet_node in hou.node('/obj').children():
            if objnet_node.type().name() != 'subnet':
                continue
            if objnet_node.comment().strip().startswith('#'):
                continue

            try:
                file_parm = objnet_node.parm("network_filename")
                file_path = os.path.normpath(file_parm.eval())

                items.append(
                    {"node": objnet_node.path(), "node_name": objnet_node.path(), "type": "objnet",  "node_type": "objnet",
                     "path": file_path}
                )
            except:
                pass

            try:
                file_parm = objnet_node.parm("fbx_camera_path")
                file_path = os.path.normpath(file_parm.eval())

                items.append(
                    {"node": objnet_node.path(), "node_name": objnet_node.path(), "type": "fbx_camera",  "node_type": "fbx_camera",
                     "path": file_path}
                )
            except:
                pass

        houdini_utils.sync_frame_range_and_fps()
        return items

    def update(self, item=None, items=None):
        """
        Perform replacements given a number of scene items passed from the app.

        Once a selection has been performed in the main UI and the user clicks
        the update button, this method is called.

        The items parameter is a list of dictionaries on the same form as was
        generated by the scan_scene hook above. The path key now holds
        the that each node should be updated *to* rather than the current path.
        """

        engine = self.parent.engine
        context = engine.context
        # these items are to be updated. swap out the fileName parm value with the
        # new path as supplied by the breakdown app.

        def item_update(item):
            node_path = item.get("node", item.get("node_name"))
            node_type = item.get("type", item.get("node_type"))
            file_path = item["path"]

            file_path = file_path.replace("\\", "/")

            # update the alembic fileName parm to the new path
            if node_type == "alembic":

                node = hou.node(node_path)
                engine.log_debug(
                    "Updating alembic node '%s' to: %s" % (
                        node_path, file_path)
                )
                node.parm("fileName").set(houdini_utils.injectJOB(file_path))
                set_comment(node, datetime_str())

            elif node_type == "alembic_camera":

                node = hou.node(node_path)
                engine.log_debug(
                    "Updating alembic_camera node '%s' to: %s" % (
                        node_path, file_path)
                )
                node.parm("fileName").set(houdini_utils.injectJOB(file_path))

                set_comment(node, datetime_str())

            elif node_type == "fbx_camera":
                node = hou.node(node_path)
                name = node.name()
                engine.log_debug(
                    "Updating fbx_camera node '%s' to: %s" % (
                        node_path, file_path)
                )
                node.destroy()
                width = int(project_field_value(
                    'sg_width', 1920, context=context))
                height = int(project_field_value(
                    'sg_height', 1080, context=context))
                houdini_utils.fbx_camera_import(
                    file_path, name, res=(width, height))

            elif node_type == "fbx_character":

                node = hou.node(node_path)
                engine.log_debug(
                    "Updating fbxcharacterimport node '%s' to: %s" % (
                        node_path, file_path)
                )
                node.parm("fbxfile").set(houdini_utils.injectJOB(file_path))
                set_comment(node, datetime_str())

            elif node_type == "matnet":
                node = hou.node(node_path)

                engine.log_debug(
                    "Updating matnet node '%s' to: %s" % (
                        node_path, file_path)
                )
                node.parm("network_filename").set(
                    houdini_utils.injectJOB(file_path))
                node.parm("network_reload").pressButton()

            elif node_type == "objnet":
                node = hou.node(node_path)
                engine.log_debug(
                    "Updating objnet node '%s' to: %s" % (
                        node_path, file_path)
                )
                node.parm("network_filename").set(
                    houdini_utils.injectJOB(file_path))
                node.parm("network_reload").pressButton()

        if items:
            for item in items:
                item_update(item)
        else:
            item_update(item)
