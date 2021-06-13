
import hou


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

        elif node.type().name() == 'cam':
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
        'compute': 7,  # full transform
        'range': 1,  # use current frame
    })

    object_chop.setExportFlag(True)
    for pname in ('aspect', 'focal', 'aperture', 'near', 'far', 'winx', 'winy', 'winsizex', 'winsizey', 'shutter', 'focus', 'fstop'):
        fetch_camera_node.parm(pname).setExpression(
            'ch("{0}/{1}")'.format(fetchcam_path, pname))
    return fetch_camera_node


def alembic_export(root, objects, filename, start=1, end=1, preroll=0, samples=2):
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
