import maya.cmds as cmds
import maya.mel as mel
import os
import sys
import shutil
import tempfile


def collect_publish_cameras(toggle_attr="publishABC"):
    items = []
    for n in cmds.ls(type='transform'):
        if not is_publish_camera(n):
            continue

        cam_path = search_camera(n)
        if not cam_path:
            continue

        try:
            enable = cmds.getAttr(n + "." + toggle_attr)
            if not enable:
                continue
        except:
            continue

        item = {}
        preroll = 0
        samples = 1

        try:
            preroll = max(preroll, cmds.getAttr(
                n + ".preroll"))
        except:
            pass

        item['preroll'] = preroll

        try:
            samples = max(samples, cmds.getAttr(
                n + ".samples"))
        except:
            pass

        item['samples'] = samples
        item['node'] = n
        item['camera'] = cam_path
        item['name'] = f"{n} ({cam_path})"

        items.append(item)

    return items


def collect_publish_items(toggle_attr="publishABC", combine_with_name=None):
    items = dict()
    for g in cmds.ls(type='transform'):
        if not is_publish_geo(g):
            continue

        try:
            enable = cmds.getAttr(g + "." + toggle_attr)
            if not enable:
                continue
        except:
            continue

        if combine_with_name:
            name = combine_with_name
        else:
            basename = get_basename(g)
            namespace = get_namespace(basename)
            if namespace:
                name = namespace
            else:
                name = basename

        item = items.setdefault(name, {})
        triangulate = item.setdefault('triangulate', 0)
        preroll = item.setdefault('preroll', 0)
        samples = item.setdefault('samples', 1)
        nodes_list = item.setdefault('nodes', [])
        nodes_list.append(g)

        try:
            triangulate = max(triangulate, cmds.getAttr(
                g + ".triangulate"))
        except:
            pass
        item['triangulate'] = triangulate

        try:
            preroll = max(preroll, cmds.getAttr(
                g + ".preroll"))
        except:
            pass

        item['preroll'] = preroll

        try:
            samples = max(samples, cmds.getAttr(
                g + ".samples"))
        except:
            pass
        item['samples'] = samples

    # print(f"ITEMS: {items}")

    return items


def get_basename(maya_node_path):
    return maya_node_path.rsplit('|', 1)[-1]


def get_namespace(maya_node_path):
    basename = get_basename(maya_node_path)
    namespace, ok, basename = basename.partition(':')
    if ok:
        return namespace
    return ''


def get_tempfile_name():
    return os.path.join(tempfile.gettempdir(), next(tempfile._get_candidate_names())).replace("\\", "/")


def is_publish_geo(node):
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


def alembic_export(root, filename, start=1, end=1, preroll=0, samples=2, renderable_only=False):
    is_animated = end > start

    # add 2 frames to the ends and preroll
    start_frame = start - 2 - preroll
    end_frame = end + 2

    # set the alembic args that make the most sense when working with Mari.
    # These flags will ensure the export of an Alembic file that contains
    # all visible geometry from the current scene together with UV's and
    # face sets for use in Mari.
    alembic_args = [
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
    if renderable_only:
        # only renderable objects (visible and not templated)
        alembic_args.append("-renderableOnly")

    if is_animated:
        alembic_args.append("-fr %d %d" % (start_frame, end_frame))
        alembic_args.append("-step {0}".format(1.0 / samples))

    filename = filename.replace("\\", "/")
    tmp_filename = get_tempfile_name() + '.abc'

    # * set object to export
    if isinstance(root, (list, tuple)):
        for r in root:
            alembic_args.append("-root '%s'" % r)
    else:
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


def get_current_fps():
    # get current time unit
    time_unit = mel.eval("currentUnit -q -t")

    # get the index in the list defined for the settings windows
    index = mel.eval(f'getIndexFromCurrentUnitCmdValue("{time_unit}")') - 1

    # get the ui name for the tiem unit (something fps)
    fps_name = mel.eval(f'getTimeUnitDisplayString({index});')

    # if you want the number now you can process the name since it will be consistent
    fps_float = float(fps_name.split(' ')[0])
    fps_int = round(fps_float)
    if fps_float == fps_int:
        return fps_int

    return fps_float


def set_current_fps(fps):
    # get current time unit
    return mel.eval(f"currentUnit -t {fps}fps")


def fbx_export(root, filename, start=1, end=1, preroll=0, samples=2, bake=True, triangulate=False):
    start_frame = start - 2 - preroll
    end_frame = end + 2
    filename = filename.replace("\\", "/")
    tmp_filename = get_tempfile_name() + '.fbx'

    fps = None
    if bake and (samples > 1):
        fps = get_current_fps()
        new_fps = fps*samples

        fps_str = set_current_fps(new_fps)
        sys.stderr.write(
            f"SG DEBUG: Change scene FPS to '{new_fps}' ({fps_str})\n")

        start_frame = start_frame*samples
        end_frame = end_frame*samples

    cmds.select(root, replace=True)
    # This ensures the user's settings are ignored so that you can just set values which differ from the default
    mel.eval('FBXResetExport;')
    mel.eval('FBXExportInputConnections -v false;')
    if bake:
        mel.eval('FBXExportBakeComplexAnimation -v 1;')
        mel.eval('FBXExportBakeResampleAnimation -v 1;')

    mel.eval('FBXExportBakeComplexStart -v %i;' % start_frame)
    mel.eval('FBXExportBakeComplexEnd -v %i;' % end_frame)
    mel.eval('FBXExportBakeComplexStep -v 1;')

    if triangulate:
        mel.eval('FBXExportTriangulate -v 1;')

    mel.eval('FBXExport -f "%s" -s;' % tmp_filename)
    # cmds.file(tmp_filename, force=True, options="v=0;", typ="FBX export", es=True)
    if fps is not None:
        fps_str = set_current_fps(fps)
        sys.stderr.write(
            f"SG DEBUG: Restore scene FPS to '{fps}' ({fps_str})\n")

    try:
        shutil.move(tmp_filename, filename)
    finally:
        try:
            os.remove(tmp_filename)
        except:
            pass


def fbx_camera_export(camera, filename, start=1, end=1, preroll=0, samples=2):
    # sys.stderr.write("{0} {1} {2} {3} {4} {5}".format(
    #     camera, filename, start, end, preroll, samples))
    camera = cmds.ls(camera, long=True)[0]
    camera_name = camera.rsplit("|", 1)[-1]
    camera_shape = cmds.listRelatives(camera, shapes=True, f=True)[0]

    # create temp fetch camera
    # try:
    #     cmds.delete('__tmp__camera__group__')
    # except:
    #     pass
    # tmp_group = cmds.group(em=True, name='__tmp__camera__group__')

    fetched_cam = cmds.camera()[0]
    # fetched_cam = cmds.parent(fetched_cam, tmp_group, relative=True)
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

        fbx_export(fetched_cam, filename, start,
                   end, preroll, samples)
    finally:
        cmds.delete(decompose_matrix)
        cmds.delete(fetched_cam)
        # cmds.delete(tmp_group)




# maya_path_remap.py
# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PRIMARY_STORAGE_NAME = "primary"


# ---------------------------------------------------------------------------
# OS helpers
# ---------------------------------------------------------------------------

def get_current_storage_key():
    """
    Return the ShotGrid LocalStorage field corresponding to the current OS.
    """

    if sys.platform.startswith("win"):
        return "windows_path"

    if sys.platform == "darwin":
        return "mac_path"

    if sys.platform.startswith("linux"):
        return "linux_path"

    raise RuntimeError(
        "Unsupported operating system: {}".format(sys.platform)
    )


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def normalize_path(path):
    """
    Normalize a ShotGrid storage path for Maya dirmap.

    Maya dirmap expects absolute paths with forward slashes.
    """

    if not path:
        return None

    path = path.strip()
    path = path.replace("\\", "/")

    # Do not remove the slash from "/" itself.
    if path != "/":
        path = path.rstrip("/")

    return path


def is_valid_absolute_path(path):
    """
    Basic validation for a LocalStorage root.
    """

    if not path:
        return False

    path = normalize_path(path)

    # Windows drive path: C:/foo
    if len(path) >= 3 and path[1] == ":" and path[2] == "/":
        return True

    # UNC path: //server/share
    if path.startswith("//"):
        return True

    # Unix / macOS
    if path.startswith("/"):
        return True

    return False


# ---------------------------------------------------------------------------
# ShotGrid
# ---------------------------------------------------------------------------

def get_primary_storage(sg):
    """
    Query the ShotGrid LocalStorage named 'primary'.
    """

    result = sg.find_one(
        "LocalStorage",
        [
            ["code", "is", PRIMARY_STORAGE_NAME],
        ],
        [
            "id",
            "code",
            "windows_path",
            "linux_path",
            "mac_path",
        ],
    )

    if not result:
        raise RuntimeError(
            "ShotGrid LocalStorage '{}' was not found.".format(
                PRIMARY_STORAGE_NAME
            )
        )

    if len(result) > 1:
        raise RuntimeError(
            "More than one LocalStorage named '{}' was found.".format(
                PRIMARY_STORAGE_NAME
            )
        )

    return result


# ---------------------------------------------------------------------------
# Maya dirmap
# ---------------------------------------------------------------------------

def clear_existing_mappings():
    """
    Remove existing Maya dirmap mappings.

    This is optional but makes the operation deterministic if the function
    is called more than once during the same Maya session.
    """

    try:
        mappings = cmds.dirmap(q=True, gam=True)
    except Exception:
        mappings = []

    if not mappings:
        return

    # Maya returns:
    #
    # [source1, destination1, source2, destination2, ...]
    #
    for i in range(0, len(mappings), 2):
        source = mappings[i]

        try:
            cmds.dirmap(um=source)
        except Exception as exc:
            print(
                "WARNING: Failed to remove dirmap '{}': {}".format(
                    source,
                    exc,
                )
            )


def setup_primary_storage_dirmap(
    sg,
    clear_existing=False,
    verbose=True,
):
    """
    Configure Maya dirmap for ShotGrid primary LocalStorage.

    Every defined OS-specific path except the current OS is mapped to the
    current OS path.

    Example:

        Linux:
            /mnt/projects  <- P:/projects
            /mnt/projects  <- /Volumes/projects

        Windows:
            P:/projects <- /mnt/projects
            P:/projects <- /Volumes/projects

        macOS:
            /Volumes/projects <- /mnt/projects
            /Volumes/projects <- P:/projects
    """

    current_key = get_current_storage_key()

    storage = get_primary_storage(sg)

    destination = normalize_path(
        storage.get(current_key)
    )

    if not destination:
        raise RuntimeError(
            "Primary LocalStorage has no path for current OS: {}".format(
                current_key
            )
        )

    if not is_valid_absolute_path(destination):
        raise RuntimeError(
            "Invalid destination path for {}: {!r}".format(
                current_key,
                destination,
            )
        )

    if clear_existing:
        clear_existing_mappings()

    cmds.dirmap(en=True)

    mappings = []

    for source_key in (
        "windows_path",
        "linux_path",
        "mac_path",
    ):
        if source_key == current_key:
            continue

        source = normalize_path(
            storage.get(source_key)
        )

        if not source:
            continue

        if not is_valid_absolute_path(source):
            print(
                "WARNING: Ignoring invalid {} path: {!r}".format(
                    source_key,
                    source,
                )
            )
            continue

        if source == destination:
            continue

        # Do not install duplicate mappings.
        if (source, destination) in mappings:
            continue

        cmds.dirmap(
            m=(source, destination)
        )

        mappings.append(
            (source, destination)
        )

        if verbose:
            print(
                "Maya dirmap: {} -> {}".format(
                    source,
                    destination,
                )
            )

    if verbose:
        print(
            "Maya dirmap configured for ShotGrid LocalStorage '{}'. "
            "Current OS: {}".format(
                storage["code"],
                current_key,
            )
        )

    return mappings
