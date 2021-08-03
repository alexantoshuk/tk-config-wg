# Copyright (c) 2015 Shotgun Software Inc.
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
import hou

import sgtk

from tank_vendor import six
import houdini_utils

HookClass = sgtk.get_hook_baseclass()


class SceneOperation(HookClass):
    """
    Hook called to perform an operation with the current scene
    """

    def execute(
        self,
        operation,
        file_path,
        context,
        parent_action,
        file_version,
        read_only,
        **kwargs
    ):
        """
        Main hook entry point

        :param operation:       String
                                Scene operation to perform

        :param file_path:       String
                                File path to use if the operation
                                requires it (e.g. open)

        :param context:         Context
                                The context the file operation is being
                                performed in.

        :param parent_action:   This is the action that this scene operation is
                                being executed for.  This can be one of:
                                - open_file
                                - new_file
                                - save_file_as
                                - version_up

        :param file_version:    The version/revision of the file to be opened.  If this is 'None'
                                then the latest version should be opened.

        :param read_only:       Specifies if the file should be opened read-only or not

        :returns:               Depends on operation:
                                'current_path' - Return the current scene
                                                 file path as a String
                                'reset'        - True if scene was reset to an empty
                                                 state, otherwise False
                                all others     - None
        """
        # with open('/home/ali/sg.txt', 'a') as f:
        #     f.write('{0} {1} {2} {3} {4}\n'.format(parent_action,
        #             operation, file_path, hou.hipFile.name(), file_version))
        if file_path:
            file_path = file_path.replace(os.path.sep, "/")

        if operation == "current_path":
            return str(hou.hipFile.name())

        elif operation == "open":
            hou.hipFile.load(six.ensure_str(file_path))
            houdini_utils.set_env(context, file_path)

        elif operation == "save":
            houdini_utils.set_env(context, hou.hipFile.name())
            hou.hipFile.save()

        elif operation == "save_as":
            houdini_utils.set_env(context, file_path)
            hou.hipFile.save(six.ensure_str(file_path))

        elif operation == "reset":
            hou.hipFile.clear()
            houdini_utils.set_env(context, None)

            return True
