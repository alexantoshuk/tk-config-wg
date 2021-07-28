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

HookClass = sgtk.get_hook_baseclass()


def set_env(ctx):
    hou.hscript('setenv -u SHOT_ROOT')
    hou.hscript('setenv -u ASSET_ROOT')
    hou.hscript('setenv -u VER')

    # hou.hscript('setenv VER = %s' % ver)
    hipname = hou.hipFile.basename()
    s = hipname.rsplit('.', 2)

    hou.hscript('setenv VER = %s' % s[-2])
    if len(s) == 3:
        ver = s[-2]
        if ver.startswith('v'):
            try:
                intver = int(ver[1:])
                hou.hscript('setenv VER = %s' % ver)
            except:
                pass

    if ctx.entity.get('type', None) == 'Shot':
        shot_root_path = ctx.sgtk.paths_from_entity(
            'Shot', ctx.entity['id'])
        if shot_root_path:
            shot_root_path = shot_root_path[0].replace("\\", "/")
            hou.hscript('setenv SHOT_ROOT = %s' % shot_root_path)

    elif ctx.entity.get('type', None) == 'Asset':
        asset_root_path = ctx.sgtk.paths_from_entity(
            'Asset', ctx.entity['id'])
        if asset_root_path:
            asset_root_path = asset_root_path[0].replace("\\", "/")
            hou.hscript('setenv ASSET_ROOT = %s' % asset_root_path)


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

        if operation == "current_path":
            set_env(context)
            return str(hou.hipFile.name())
        elif operation == "open":
            # give houdini forward slashes
            file_path = file_path.replace(os.path.sep, "/")
            hou.hipFile.load(six.ensure_str(file_path))
            # set_env(context)
        elif operation == "save":
            hou.hipFile.save()
            # set_env(context)
        elif operation == "save_as":
            # give houdini forward slashes
            file_path = file_path.replace(os.path.sep, "/")
            hou.hipFile.save(six.ensure_str(file_path))

        elif operation == "reset":
            hou.hipFile.clear()
            set_env(context)
            return True

        set_env(context)
