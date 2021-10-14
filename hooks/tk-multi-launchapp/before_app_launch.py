# Copyright (c) 2013 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

"""
Before App Launch Hook

This hook is executed prior to application launch and is useful if you need
to set environment variables or run scripts as part of the app initialization.
"""

import os
import sys
import tank
import platform


class BeforeAppLaunch(tank.Hook):
    """
    Hook to set up the system prior to app launch.
    """

    def execute(
        self, app_path, app_args, version, engine_name, software_entity=None, **kwargs
    ):
        """
        The execute function of the hook will be called prior to starting the required application

        :param app_path: (str) The path of the application executable
        :param app_args: (str) Any arguments the application may require
        :param version: (str) version of the application being run if set in the
            "versions" settings of the Launcher instance, otherwise None
        :param engine_name (str) The name of the engine associated with the
            software about to be launched.
        :param software_entity: (dict) If set, this is the Software entity that is
            associated with this launch command.
        """

        # accessing the current context (current shot, etc)
        # can be done via the parent object
        #
        # > multi_launchapp = self.parent
        # > current_entity = multi_launchapp.context.entity

        # you can set environment variables like this:
        # os.environ["MY_SETTING"] = "foo bar"
        ctx = self.parent.context
        projects = os.path.dirname(ctx.sgtk.roots.get('primary'))
        root = os.path.dirname(projects)
        tkroot = os.path.join(root, 'tk').replace('\\', '/')

        cur_proj_path = None
        cur_proj_path = ctx.sgtk.paths_from_entity(
            ctx.project['type'], ctx.project['id'])[0]

        cur_proj_path = os.path.normpath(cur_proj_path)
        sys.path.append(cur_proj_path)
        self.logger.debug(
            "Try to load project environment from '%s/proj_env.py'" % cur_proj_path)
        try:
            import proj_env
            reload(proj_env)
            self.logger.debug(
                "Loading project environment from '%s/proj_env.py' done successfully" % cur_proj_path)
        except:
            self.logger.warning(
                "Fail to load project environment from '%s/proj_env.py'" % cur_proj_path)

        if platform.system() == "Windows":
            tk_app_path = tkroot + '/app/' + platform.system()
            os.environ['PATH'] += os.pathsep + tk_app_path + '/ffmpeg/bin'
            os.environ['PATH'] += os.pathsep + tk_app_path + '/ImageMagick'
            home = (os.environ['USERPROFILE'] +
                    "/Documents").replace('\\', '/')
        else:
            home = os.environ['HOME']

        os.environ["redshift_LICENSE"] = "5053@10.150.73.5"
        os.environ['OCIO'] = tkroot + \
            '/OpenColorIO-Configs/aces_1.0.3/config.ocio'

        os.environ['PYTHONPATH'] = os.environ.get(
            'PYTHONPATH', '') + os.pathsep + os.path.join(os.path.dirname(__file__), 'utils').replace('\\', '/')

        if engine_name in ("tk-nuke", "tk-nukestudio"):
            os.environ['NUKE_PATH'] = os.environ.get(
                'NUKE_PATH', '') + os.pathsep + tkroot + '/.nuke'

        elif engine_name == "tk-maya":
            os.environ['MAYA_SCRIPT_PATH'] = os.environ.get(
                'MAYA_SCRIPT_PATH', '') + os.pathsep + os.path.normpath(tkroot + '/maya/scripts')
            os.environ['PYTHONPATH'] = os.environ.get(
                'PYTHONPATH', '') + os.pathsep + os.path.normpath(tkroot + '/maya/scripts')

        elif engine_name == "tk-houdini":
            os.environ['HSITE'] = tkroot
            hver = None
            for i, ch in enumerate(app_path):
                try:
                    int(ch)
                    hver = app_path[i:]
                    hver = '.'.join(hver.split('.')[:2])
                    break
                except:
                    pass

            try:
                os.remove(home + '/houdini%s/flipbook.pref' % hver)
            except:
                pass
