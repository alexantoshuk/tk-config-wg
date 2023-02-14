import maya.cmds as cmds
import maya.mel as mel
import os
import sys
import shutil
import tempfile


def get_tempfile_name():
    return os.path.join(tempfile.gettempdir(), next(tempfile._get_candidate_names())).replace("\\", "/")


def is_publish_geometry(node):
    if not cmds.getAttr(node + ".useOutlinerColor"):
        return False
    color = cmds.getAttr(node + ".outlinerColor")[0]
    r, g, b = color
    return (round(r, 1), round(g, 1), round(b, 1)) == (0.1, 0.7, 0.1)


def is_publish_camera(node):
    if not cmds.getAttr(node + ".useOutlinerColor"):
        return False
    color = cmds.getAttr(node + ".outlinerColor")[0]
    r, g, b = color
    return (round(r, 1), round(g, 1), round(b, 1)) == (0.8, 0.2, 0.2)


def search_camera(node):
    camera_shapes = cmds.listRelatives(
        node, allDescendents=True, noIntermediate=True, fullPath=True, type="camera")
    if not camera_shapes:
        return
    for n in camera_shapes:
        s = n.rsplit("|", 2)
        sname = s[-1]
        sname = sname.rsplit(':')[-1]
        tname = s[-2]
        tname = tname.rsplit(':')[-1]
        if sname.startswith('_') or tname.startswith('_'):
            continue

        return "|".join(s[:-1])  # return camera transform full path


def alembic_camera_export(camera, filename, start=1, end=1, preroll=0, samples=8):
    # sys.stderr.write("{0} {1} {2} {3} {4} {5}".format(
    #     camera, filename, start, end, preroll, samples))
    camera = cmds.ls(camera, long=True)[0]
    camera_name = camera.rsplit("|", 1)[-1]
    camera_shape = cmds.listRelatives(camera, shapes=True, f=True)[0]

    # create temp fetch camera
    try:
        cmds.delete('__tmp__camera__group__')
    except:
        pass
    tmp_group = cmds.group(em=True, name='__tmp__camera__group__')

    fetched_cam = cmds.camera()[0]
    fetched_cam = cmds.parent(fetched_cam, tmp_group, relative=True)
    fetched_cam = cmds.rename(fetched_cam, camera_name)
    fetched_cam_shape = cmds.listRelatives(fetched_cam, shapes=True, f=True)[0]

    decompose_matrix = cmds.createNode(
        'decomposeMatrix', n='__tmp__decomposeMatrix')

    try:
        cmds.connectAttr(
            camera + '.worldMatrix[0]', decompose_matrix + '.inputMatrix')
        cmds.connectAttr(
            decompose_matrix + '.outputTranslate', fetched_cam + '.translate')
        cmds.connectAttr(
            decompose_matrix + '.outputRotate', fetched_cam + '.rotate')
        cmds.connectAttr(
            decompose_matrix + '.outputScale', fetched_cam + '.scale')

        for name in ('.cameraAperture', '.fStop', '.focalLength', '.focusDistance', '.shutterAngle', '.lensSqueezeRatio', '.nearClipPlane', '.farClipPlane'):
            cmds.connectAttr(camera_shape + name, fetched_cam_shape + name)

        # prepare to alembic export
        is_animated = end > start

        alembic_export(fetched_cam, filename, start,
                       end, preroll, samples)
    finally:
        cmds.delete(decompose_matrix)
        cmds.delete(tmp_group)


def alembic_export(root, filename, start=1, end=1, preroll=0, samples=2):
    is_animated = end > start

    # add 2 frames to the ends and preroll
    start_frame = start - 2 - preroll
    end_frame = end + 2

    # set the alembic args that make the most sense when working with Mari.
    # These flags will ensure the export of an Alembic file that contains
    # all visible geometry from the current scene together with UV's and
    # face sets for use in Mari.
    alembic_args = [
        # only renderable objects (visible and not templated)
        "-renderableOnly",
        # write shading group set assignments (Maya 2015+)
        "-writeFaceSets",
        # write uv's (only the current uv set gets written)
        "-uvWrite",
        # do not export vertex normals
        # "-noNormals",
        "-eulerFilter",
        "-attrPrefix 'mix_'",
        "-attrPrefix 'abc_'",
        "-attrPrefix 'attr_'",
    ]

    if is_animated:
        alembic_args.append("-fr %d %d" % (start_frame, end_frame))
        alembic_args.append("-step {0}".format(1.0 / samples))

    filename = filename.replace("\\", "/")
    tmp_filename = get_tempfile_name() + '.abc'

    # * set object to export
    alembic_args.append("-root '%s'" % root)
    # Set the output path:
    # Note: The AbcExport command expects forward slashes!
    alembic_args.append("-file '%s'" % tmp_filename)

    # build the export command.  Note, use AbcExport -help in Maya for
    # more detailed Alembic export help
    abc_export_cmd = 'AbcExport -j "%s"' % " ".join(alembic_args)

    try:
        # ...and execute it:
        mel.eval(abc_export_cmd)
        shutil.move(tmp_filename, filename)

    finally:
        try:
            os.remove(tmp_filename)
        except:
            pass


def fbx_export(root, filename, start=1, end=1, preroll=0, samples=2):
    start_frame = start - 2 - preroll
    end_frame = end + 2
    filename = filename.replace("\\", "/")
    tmp_filename = get_tempfile_name() + '.fbx'

    cmds.select(root, replace=True)
    # This ensures the user's settings are ignored so that you can just set values which differ from the default
    mel.eval('FBXResetExport')
    mel.eval('FBXExportBakeComplexAnimation -v 1')
    # mel.eval('FBXExportBakeResampleAll -v 1')
    mel.eval('FBXExportBakeComplexStart -v %i' % start_frame)
    mel.eval('FBXExportBakeComplexEnd -v %i' % end_frame)
    mel.eval('FBXExportBakeComplexStep -v %i' % samples)
    mel.eval('FBXExport -f "%s" -s' % tmp_filename)
    # cmds.file(tmp_filename, force=True, options="v=0;", typ="FBX export", es=True)
    try:
        shutil.move(tmp_filename, filename)
    finally:
        try:
            os.remove(tmp_filename)
        except:
            pass
