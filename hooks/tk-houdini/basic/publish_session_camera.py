# Copyright (c) 2017 Shotgun Software Inc.
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
import glob
import sgtk
import hou

from tank_vendor import six

HookBaseClass = sgtk.get_hook_baseclass()

VER_LIMIT = 0


def create_fetch_camera(parent, name, fetchcam_path):
    fetch_camera_node = parent.createNode("cam", name)
    chopnet = fetch_camera_node.createNode('chopnet')
    object_chop = chopnet.createNode('object')
    object_chop.setParms({
        'targetpath': fetchcam_path,
        'compute': 7,  # full transform
        'range': 1,  # use current frame
    })

    object_chop.setExportFlag(True)
    for pname in ('aspect', 'focal', 'aperture', 'near', 'far', 'winx', 'winy', 'winsizex', 'winsizey', 'shutter', 'focus', 'fstop'):
        fetch_camera_node.parm(pname).setExpression(
            'ch("{0}/{1}")'.format(fetchcam_path, pname))
    return fetch_camera_node


class HoudiniSessionCamerPublishPlugin(HookBaseClass):
    """
    Plugin for publishing an open houdini session.

    This hook relies on functionality found in the base file publisher hook in
    the publish2 app and should inherit from it in the configuration. The hook
    setting for this plugin should look something like this::

        hook: "{self}/publish_file.py:{engine}/tk-multi-publish2/basic/publish_session.py"

    """

    @property
    def description(self):
        """
        Verbose, multi-line description of what the plugin does. This can
        contain simple html for formatting.
        """

        return """
        <p>This plugin publishes session camera for the current session. Any
        session camera will be exported to the path defined by this plugin's
        configured "Publish Template" setting.</p>
        """

    @property
    def settings(self):
        """
        Dictionary defining the settings that this plugin expects to receive
        through the settings parameter in the accept, validate, publish and
        finalize methods.

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
        # inherit the settings from the base publish plugin
        base_settings = super(
            HoudiniSessionCamerPublishPlugin, self).settings or {}

        # settings specific to this class
        houdini_publish_settings = {
            "Publish Template": {
                "type": "template",
                "default": None,
                "description": "Template path for published work files. Should"
                "correspond to a template defined in "
                "templates.yml.",
            }
        }

        # update the base settings
        base_settings.update(houdini_publish_settings)

        return base_settings

    @property
    def item_filters(self):
        """
        List of item types that this plugin is interested in.

        Only items matching entries in this list will be presented to the
        accept() method. Strings can contain glob patters such as *, for example
        ["houdini.*", "file.houdini"]
        """
        return ["houdini.session.camera"]

    def accept(self, settings, item):
        """
        Method called by the publisher to determine if an item is of any
        interest to this plugin. Only items matching the filters defined via the
        item_filters property will be presented to this method.

        A publish task will be generated for each item accepted here. Returns a
        dictionary with the following booleans:

            - accepted: Indicates if the plugin is interested in this value at
                all. Required.
            - enabled: If True, the plugin will be enabled in the UI, otherwise
                it will be disabled. Optional, True by default.
            - visible: If True, the plugin will be visible in the UI, otherwise
                it will be hidden. Optional, True by default.
            - checked: If True, the plugin will be checked in the UI, otherwise
                it will be unchecked. Optional, True by default.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process

        :returns: dictionary with boolean keys accepted, required and enabled
        """

        accepted = True
        publisher = self.parent
        template_name = settings["Publish Template"].value

        # ensure a work file template is available on the parent item
        work_template = item.parent.properties.get("work_template")
        if not work_template:
            self.logger.debug(
                "A work template is required for the session item in order to "
                "publish session geometry. Not accepting session geom item."
            )
            accepted = False

        # ensure the publish template is defined and valid and that we also have
        publish_template = publisher.get_template_by_name(template_name)
        if not publish_template:
            self.logger.debug(
                "The valid publish template could not be determined for the "
                "session geometry item. Not accepting the item."
            )
            accepted = False

        # we've validated the publish template. add it to the item properties
        # for use in subsequent methods
        item.properties["publish_template"] = publish_template

        # because a publish template is configured, disable context change. This
        # is a temporary measure until the publisher handles context switching
        # natively.
        item.context_change_allowed = False

        return {"accepted": accepted, "checked": True}

    def validate(self, settings, item):
        """
        Validates the given item to check that it is ok to publish. Returns a
        boolean to indicate validity.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        :returns: True if item is valid, False otherwise.
        """

        path = hou.hipFile.path()

        # ---- ensure the session has been saved

        if not path:
            # the session still requires saving. provide a save button.
            # validation fails.
            error_msg = "The Houdini session has not been saved."
            self.logger.error(error_msg, extra=_get_save_as_action())
            raise Exception(error_msg)

        cam_path = item.properties["camera"]
        cam_node = hou.node(cam_path)
        if not cam_node:
            error_msg = "Node '%s' is not exists." % cam_path
            self.logger.error(error_msg)
            raise Exception(error_msg)

        node_path = item.properties["node"]
        node_name = node_name = node_path.rsplit("/", 1)[-1]

        if not node_name.startswith('camera'):
            error_msg = "The name of the camera subnet '%s' must be started with 'camera' word." % node_path
            self.logger.error(error_msg)
            raise Exception(error_msg)

        # get the normalized path
        path = sgtk.util.ShotgunPath.normalize(path)

        # get the configured work file template
        work_template = item.parent.properties.get("work_template")
        publish_template = item.properties.get("publish_template")

        # get the current scene path and extract fields from it using the work
        # template:
        work_fields = work_template.get_fields(path)

        if "abc_preroll" not in item.properties:
            self.logger.warning(
                "'abc_preroll' parameter is not founded. Use 0 by default.")
            item.properties["abc_preroll"] = 0
        if "abc_samples" not in item.properties:
            self.logger.warning(
                "'abc_samples' parameter is not founded. Use 8 by default.")
            item.properties["abc_samples"] = 8

        work_fields['node'] = node_name

        # ensure the fields work for the publish template
        missing_keys = publish_template.missing_keys(work_fields)
        if missing_keys:
            error_msg = (
                "Work file '%s' missing keys required for the "
                "publish template: %s" % (path, missing_keys)
            )

            self.logger.error(error_msg)
            raise Exception(error_msg)

        # create the publish path by applying the fields. store it in the item's
        # properties. This is the path we'll create and then publish in the base
        # publish plugin. Also set the publish_path to be explicit.
        item.properties["path"] = publish_template.apply_fields(work_fields)
        item.properties["publish_path"] = item.properties["path"]
        item.properties["publish_type"] = "Alembic Camera"
        # use the work file's version number when publishing
        if "version" in work_fields:
            item.properties["publish_version"] = work_fields["version"]

        # * return grand parent validate method

        return super(HoudiniSessionCamerPublishPlugin, self).validate(settings, item)

    def publish(self, settings, item):
        """
        Executes the publish logic for the given item and settings.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        """

        publisher = self.parent

        item.properties["publish_type"] = "Alembic Camera"
        # * get abc cache data
        node_path = item.properties["node"]
        cam_path = item.properties["camera"]
        node_name = node_path.rsplit("/", 1)[-1]

        abc_preroll = item.properties["abc_preroll"]
        abc_samples = item.properties["abc_samples"]
        # get the path to create and publish
        publish_path = item.properties["path"]

        # ensure the publish folder exists:
        publish_folder = os.path.dirname(publish_path)
        self.parent.ensure_folder_exists(publish_folder)

        # set the alembic args that make the most sense when working with Mari.
        # These flags will ensure the export of an Alembic file that contains
        # all visible geometry from the current scene together with UV's and
        # face sets for use in Mari.

        # find the animated frame range to use:
        start_frame, end_frame = _find_scene_animation_range()

        if start_frame and end_frame:
            # * add 2 frames to the ends and preroll
            start_frame = start_frame - 2 - abc_preroll
            end_frame = end_frame + 2

        tmp_subnet_name = '__tmp__'
        self.parent.log_debug("Create temp subnet: /out/%s" % tmp_subnet_name)
        tmp_subnet = hou.node('/out/' + tmp_subnet_name)
        if tmp_subnet:
            tmp_subnet.destroy()
        tmp_subnet = hou.node('/out').createNode('subnet', tmp_subnet_name)

        tmp_obj_subnet = None
        if node_path != cam_path:
            tmp_obj_subnet = hou.node('/obj/' + tmp_subnet_name)
            if tmp_obj_subnet:
                tmp_obj_subnet.destroy()
            tmp_obj_subnet = hou.node(
                '/obj').createNode('subnet', tmp_subnet_name)

        # ...and execute it:
        try:
            root = '/obj'
            objects = node_name
            if tmp_obj_subnet:
                self.parent.log_debug(
                    "Create temp 'fetch_camera' node: /obj/{0}/{1}".format(tmp_subnet_name, node_name))

                fetch_camera_node = create_fetch_camera(
                    tmp_obj_subnet, node_name, cam_path)

                root = tmp_obj_subnet.path()
                objects = fetch_camera_node.path()

            self.parent.log_debug(
                "Create alembic node: /out/{0}/{1}".format(tmp_subnet, node_name))
            alembic_node = tmp_subnet.createNode(
                'alembic', node_name)

            alembic_node.setParms({
                'trange': 1,
                'filename': publish_path,
                'root': root,
                'objects': objects,
                'packed_transform': 1,
                'motionBlur': True,
                'samples': abc_samples,
            })
            frange_p = alembic_node.parmTuple("f")
            frange_p.deleteAllKeyframes()
            frange_p.set((start_frame, end_frame, 1))

            self.parent.log_debug("Executing node: %s" %
                                  alembic_node.path())
            alembic_node.render()

        except Exception as e:
            error_msg = "Failed to export Camera: %s" % e
            self.logger.error(error_msg)
            raise Exception(error_msg)
            return
        finally:
            self.parent.log_debug("Destroy: /out/%s" % tmp_subnet_name)
            tmp_subnet.destroy()
            if tmp_obj_subnet:
                self.parent.log_debug("Destroy: /obj/%s" % tmp_subnet_name)
                tmp_obj_subnet.destroy()
            pass

        # Now that the path has been generated, hand it off to the
        super(HoudiniSessionCamerPublishPlugin,
              self).publish(settings, item)

    def finalize(self, settings, item):
        """
        Execute the finalization pass. This pass executes once all the publish
        tasks have completed, and can for example be used to version up files.
        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        """

        # * limit number of versions to VER_LIMIT
        if VER_LIMIT and ("publish_version" in item.properties):
            path = item.properties["publish_path"]
            pattern = path[:-len("000.abc")] + "???.abc"
            for f in sorted(glob.iglob(pattern))[:-VER_LIMIT]:
                try:
                    os.remove(f)
                    self.logger.info(
                        "Remove '{0}' because of version limit = {1}".format(path, VER_LIMIT))
                except:
                    self.logger.info("Can't remove '{0}'".format(path))

        return


def _find_scene_animation_range():
    """
    Find the animation range from the current scene.
    """

    start, end = hou.playbar.frameRange()

    return start, end


def _session_path():
    """
    Return the path to the current session
    :return:
    """
    path = hou.hipFile.path()

    if path is not None:
        path = six.ensure_str(path)

    return path


def _get_save_as_action():
    """
    Simple helper for returning a log action dict for saving the session
    """

    engine = sgtk.platform.current_engine()

    # default save callback
    callback = hou.hipFile.save

    # if workfiles2 is configured, use that for file save
    if "tk-multi-workfiles2" in engine.apps:
        app = engine.apps["tk-multi-workfiles2"]
        if hasattr(app, "show_file_save_dlg"):
            callback = app.show_file_save_dlg

    return {
        "action_button": {
            "label": "Save As...",
            "tooltip": "Save the current session",
            "callback": callback,
        }
    }
