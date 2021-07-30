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


def ver_from_path(filepath):
    if not filepath:
        return
    s = filepath.rsplit('.', 2)

    if len(s) != 3:
        return

    ver = s[-2]
    if not ver.startswith('v'):
        return
    try:
        intver = int(ver[1:])
        return ver
    except:
        return


def set_env(ctx, filepath):
    hou.hscript('setenv -u SHOTPATH')
    hou.hscript('setenv -u ASSETPATH')
    hou.hscript('setenv -u STEPPATH')
    hou.hscript('setenv -u SHOT')
    hou.hscript('setenv -u ASSET')
    hou.hscript('setenv -u STEP')
    hou.hscript('setenv -u TASK')
    hou.hscript('setenv -u VER')

    ver = ver_from_path(filepath)
    if ver is not None:
        hou.hscript('setenv VER = %s' % ver)

    en = sgtk.platform.current_engine()
    ctx.sgtk.create_filesystem_structure(ctx.entity['type'], ctx.entity['id'])

    root_template_name = ctx.entity.get('type', '').lower() + '_root'
    root_template = en.get_template_by_name(root_template_name)

    root_path = None
    entity_root_path = None

    fields = ctx.as_template_fields(root_template)
    root_path = ctx.sgtk.paths_from_template(
        root_template, fields)

    root_path = root_path[0].replace("\\", "/")
    entity_root_path = os.path.dirname(root_path)
    hou.hscript('setenv ENTITYPATH = %s' % entity_root_path)
    hou.hscript('setenv ENTITY = %s' % ctx.entity['name'])

    if ctx.step:
        hou.hscript('setenv STEPPATH = %s' % root_path)
        hou.hscript('setenv STEP = %s' % ctx.step['name'])

    if ctx.task:
        task_name = ctx.task.get('name', None)
        if task_name:
            hou.hscript('setenv TASK = %s' % task_name)

    if ctx.entity.get('type', None) == 'Shot':
        hou.hscript('setenv SHOTPATH = %s' % entity_root_path)
        hou.hscript('setenv SHOT = %s' % ctx.entity['name'])

    elif ctx.entity.get('type', None) == 'Asset':
        hou.hscript('setenv ASSETPATH = %s' % entity_root_path)
        hou.hscript('setenv ASSET = %s' % ctx.entity['name'])


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

        if file_path:
            file_path = file_path.replace(os.path.sep, "/")

        set_env(context, file_path)
        if operation == "current_path":
            return str(hou.hipFile.name())

        elif operation == "open":
            hou.hipFile.load(six.ensure_str(file_path))

        elif operation == "save":
            hou.hipFile.save()

        elif operation == "save_as":
            hou.hipFile.save(six.ensure_str(file_path))

        elif operation == "reset":
            hou.hipFile.clear()
            set_env(context, file_path)
            return True

        set_env(context, file_path)
