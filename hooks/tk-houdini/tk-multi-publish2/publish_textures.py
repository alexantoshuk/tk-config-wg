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
import traceback
import sgtk
from sgtk.util.filesystem import copy_file
import hou

from tank_vendor import six

import houdini_utils
import common_utils

HookBaseClass = sgtk.get_hook_baseclass()

VER_LIMIT = 0


class HoudiniTexturesPublishPlugin(HookBaseClass):
    """
    Plugin for publishing matnet.

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
        <p>This plugin publishes material network for the current session. Any
        session material network will be exported to the path defined by this plugin's
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
            HoudiniTexturesPublishPlugin, self).settings or {}

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
        return ["Texture"]

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

        work_template = item.parent.properties.get("work_template")
        work_fields = work_template.get_fields(path)
        version = work_fields['version']

        path = item.properties["path"]
        # get the normalized path
        path = sgtk.util.ShotgunPath.normalize(path)

        # get the configured work file template
        work_template = item.properties.get("work_template")
        publish_template = item.properties.get("publish_template")

        # get the current scene path and extract fields from it using the work
        # template:
        # sys.stderr.write(str(work_template) + '\n')
        # sys.stderr.write(str(publish_template) + '\n')
        # sys.stderr.write(path + '\n')
        # sys.stderr.write(str(version) + '\n')
        work_fields = work_template.get_fields(path)
        work_fields['version'] = version

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
        item.properties["publish_version"] = version
        item.properties["publish_path"] = publish_template.apply_fields(
            work_fields)
        item.properties["publish_type"] = "Texture"

        # * return grand parent validate method

        return super(HoudiniTexturesPublishPlugin, self).validate(settings, item)

    def publish(self, settings, item):
        """
        Executes the publish logic for the given item and settings.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        """

        # Now that the path has been generated, hand it off to the
        super(HoudiniTexturesPublishPlugin,
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
        # common_utils.cleanup_versions(
        #     item.properties["publish_path"], pattern=".v???.matnet", max_versions=VER_LIMIT, logger=self.logger)

        super(HoudiniTexturesPublishPlugin,
              self).finalize(settings, item)

    def _copy_work_to_publish(self, settings, item):
        """
        This method handles copying work file path(s) to a designated publish
        location.

        This method requires a "work_template" and a "publish_template" be set
        on the supplied item.

        The method will handle copying the "path" property to the corresponding
        publish location assuming the path corresponds to the "work_template"
        and the fields extracted from the "work_template" are sufficient to
        satisfy the "publish_template".

        The method will not attempt to copy files if any of the above
        requirements are not met. If the requirements are met, the file will
        ensure the publish path folder exists and then copy the file to that
        location.

        If the item has "sequence_paths" set, it will attempt to copy all paths
        assuming they meet the required criteria with respect to the templates.

        """
        path = hou.hipFile.path()

        # ---- ensure the session has been saved

        if not path:
            # the session still requires saving. provide a save button.
            # validation fails.
            error_msg = "The Houdini session has not been saved."
            self.logger.error(error_msg, extra=_get_save_as_action())
            raise Exception(error_msg)

        work_template = item.parent.properties.get("work_template")
        work_fields = work_template.get_fields(path)
        version = work_fields['version']

        publish_file = None

        # ---- ensure templates are available
        work_template = item.properties.get("work_template")
        if not work_template:
            self.logger.debug(
                "No work template set on the item. "
                "Skipping copy file to publish location."
            )
            return

        publish_template = self.get_publish_template(settings, item)
        if not publish_template:
            self.logger.debug(
                "No publish template set on the item. "
                "Skipping copying file to publish location."
            )
            return

        # ---- get a list of files to be copied

        # by default, the path that was collected for publishing
        work_files = [item.properties.path]

        # if this is a sequence, get the attached files
        if "sequence_paths" in item.properties:
            work_files = item.properties.get("sequence_paths", [])

            if not work_files:
                self.logger.warning(
                    "Sequence publish without a list of files. Publishing "
                    "the sequence path in place: %s" % (item.properties.path,)
                )
                return

        # ---- copy the work files to the publish location

        for work_file in work_files:

            if not work_template.validate(work_file):
                self.logger.warning(
                    "Work file '%s' did not match work template '%s'. "
                    "Publishing in place." % (work_file, work_template)
                )
                return

            work_fields = work_template.get_fields(work_file)
            work_fields['version'] = version
            missing_keys = publish_template.missing_keys(work_fields)

            if missing_keys:
                self.logger.warning(
                    "Work file '%s' missing keys required for the publish "
                    "template: %s" % (work_file, missing_keys)
                )
                return

            publish_file = publish_template.apply_fields(work_fields)

            # copy the file
            try:
                publish_folder = os.path.dirname(publish_file)
                self.parent.ensure_folder_exists(publish_folder)
                copy_file(work_file, publish_file)
            except Exception:
                raise Exception(
                    "Failed to copy work file from '%s' to '%s'.\n%s"
                    % (work_file, publish_file, traceback.format_exc())
                )

            self.logger.debug(
                "Copied work file '%s' to publish file '%s'."
                % (work_file, publish_file)
            )

        return publish_file


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
