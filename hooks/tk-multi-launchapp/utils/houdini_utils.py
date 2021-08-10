
import hou
import sys
import os


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


def set_ver():
    ver = ver_from_path(hou.hipFile.name())
    if ver:
        hou.hscript('setenv VER = %s' % ver)
        hou.hscript('varchange')


def set_env(ctx, filepath):
    import sgtk
    hou.hscript('setenv -u SHOTPATH')
    hou.hscript('setenv -u ASSETPATH')
    hou.hscript('setenv -u STEPPATH')
    hou.hscript('setenv -u SHOT')
    hou.hscript('setenv -u ASSET')
    hou.hscript('setenv -u STEP')
    hou.hscript('setenv -u TASK')
    hou.hscript('setenv -u VER')

    if not filepath:
        hou.hscript('varchange')
        return

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
    hou.hscript('varchange')


def set_comment(node, comment):
    node.setComment(comment)
    node.setGenericFlag(hou.nodeFlag.DisplayComment, True)


def node_types(node_type_category, pattern):
    '''Return a list of node types in a particular node type category
       whose names match a pattern.'''
    import fnmatch

    return [node_type
            for node_type_name, node_type in node_type_category.nodeTypes().items()
            if fnmatch.fnmatch(node_type_name, pattern)]


def node_type_instances(node_type_category, pattern):
    '''Return a list of nodes in a particular node type category
       whose names match a pattern.'''
    return [n for ty in node_types(node_type_category, pattern) for n in ty.instances()]


def is_publish_matnet(node):
    return node.comment().strip() == "# Publish Material Network"


def is_publish_objnet(node):
    return node.comment().strip() == "# Publish Network"


def is_publish_alembic(node):
    return node.comment().strip() == "# Publish Alembic"


def is_publish_camera(node):
    return node.comment().strip() == "# Publish Camera"


def is_time_dependent(node):
    td = [False]

    def _walk(node):
        if node.isTimeDependent():
            td[0] = True
            return True
        child_cat_name = node.childTypeCategory().name()
        if child_cat_name == 'Object':
            for n in node.children():
                if _walk(n):
                    return True
        else:
            r = node.renderNode()
            if r and r.isTimeDependent():
                td[0] = True
                return True

    _walk(node)
    return td[0]


def search_camera(node):
    if node.type().name() == 'cam':
        return node

    cam = [None]

    def _search_cam(node):
        if node.name().startswith('_'):
            return
        if node.childTypeCategory().name() == 'Object':
            for n in node.children():
                if _search_cam(n):
                    return True

        elif node.type().name() in ('cam', 'lopimportcam', 'wg::fetchcamera::1.0'):
            cam[0] = node
            return True

    _search_cam(node)

    return cam[0]


def create_fetch_camera(parent, name, fetchcam_path):
    fetch_camera_node = parent.createNode("cam", name)
    chopnet = fetch_camera_node.createNode('chopnet')
    object_chop = chopnet.createNode('object')
    object_chop.setParms({
        'targetpath': fetchcam_path,
        'compute': 6,  # position and rotation
        'range': 0,  # use full animation range
        'left': 1,  # slope
        'right': 1,  # slope
    })
    object_chop.parm('samplerate').setExpression('$FPS*16')

    object_chop.setExportFlag(True)
    for pname in ('aspect', 'focal', 'aperture', 'near', 'far', 'winx', 'winy', 'winsizex', 'winsizey', 'shutter', 'focus', 'fstop'):
        fetch_camera_node.parm(pname).setExpression(
            'ch("{0}/{1}")'.format(fetchcam_path, pname))

    fetch_camera_node.parm('xOrd').set(3)
    fetch_camera_node.parm('scale').deleteAllKeyframes()

    return fetch_camera_node


def alembic_camera_export(campath, filename, start=1, end=1, preroll=0, samples=8, scale=1.0):
    tmp_subnet_name = '__tmp__'
    tmp_obj_subnet = None

    node = hou.node(campath)
    campath = node.path()
    name = campath.split('/', 3)[2]
    objnet = hou.node('/obj')

    tmp_obj_subnet = hou.node('/obj/' + tmp_subnet_name)
    if tmp_obj_subnet:
        tmp_obj_subnet.destroy()
    tmp_obj_subnet = objnet.createNode('subnet', tmp_subnet_name)

    # ...and execute it:
    try:
        root = '/obj'
        objects = name
        fetch_camera_node = create_fetch_camera(
            tmp_obj_subnet, name, campath)
        fetch_camera_node.parm('scale').set(scale)
        root = tmp_obj_subnet.path()
        objects = fetch_camera_node.path()

        alembic_export(root, objects, filename,
                       start, end, preroll, samples)
    except Exception as e:
        raise e
    finally:
        tmp_obj_subnet.destroy()


def alembic_subnet_export(subnetpath, filename, start=1, end=1, preroll=0, samples=2, scale=1.0):
    node = hou.node(subnetpath)
    scale_p = node.parm('scale')
    old_scale = scale_p.eval()
    is_locked = scale_p.isLocked()

    scale_p.lock(0)
    scale_p.set(old_scale * scale)

    is_display = node.isDisplayFlagSet()
    node.setDisplayFlag(1)
    try:
        alembic_export('/obj', subnetpath, filename,
                       start, end, preroll, samples, build_from_path=True)
    except Exception as e:
        raise e
    finally:
        node.setDisplayFlag(is_display)
        scale_p.set(old_scale)
        scale_p.lock(is_locked)


def alembic_export(root, objects, filename, start=1, end=1, preroll=0, samples=2, build_from_path=False):
    is_animated = end > start

    # add 2 frames to the ends and preroll
    start_frame = start - 2 - preroll
    end_frame = end + 2

    tmp_alembic_node = hou.node('/out/__tmp__alembic__')
    if tmp_alembic_node:
        tmp_alembic_node.destroy()
    tmp_alembic_node = hou.node(
        '/out').createNode('alembic', '__tmp__alembic__')

    try:
        tmp_alembic_node.setParms({
            'trange': int(is_animated),
            'filename': filename,
            'root': root,
            'objects': objects,
            'packed_transform': 1,
            'motionBlur': is_animated,
            'samples': samples,
            'build_from_path': build_from_path,
        })

        if is_animated:
            frange_p = tmp_alembic_node.parmTuple("f")
            frange_p.deleteAllKeyframes()
            frange_p.set((start_frame, end_frame, 1))

        tmp_alembic_node.render()

    except Exception as e:
        raise e

    finally:
        tmp_alembic_node.destroy()
