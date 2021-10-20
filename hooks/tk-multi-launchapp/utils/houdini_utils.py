
import hou
import sys
import os
import tempfile
from common_utils import project_field_value, entity_field_value


def abstract_paths_from_template(self, template, fields):
    """
    Override to deal with optional template fields
    https://developer.shotgridsoftware.com/tk-core/_modules/tank/api.html#Sgtk.abstract_paths_from_template
    """
    search_template = template

    # the logic is as follows:
    # do a glob and collapse abstract fields down into their abstract patterns
    # unless they are specified with values in the fields dictionary
    #
    # if the leaf level can be avoided, do so.
    # the leaf level can be avoided if it contains
    # a combination of non-abstract templates with values in the fields dict
    # and abstract templates.

    # can we avoid the leaf level?
    leaf_keys = set(template.keys.keys()) - set(template.parent.keys.keys())

    abstract_key_names = [
        k.name for k in template.keys.values() if k.is_abstract]

    skip_leaf_level = True
    for k in leaf_keys:
        if k not in abstract_key_names:
            # a non-abstract key
            if k not in fields:
                # with no value
                skip_leaf_level = False
                break

    if skip_leaf_level:
        search_template = template.parent

    # now carry out a regular search based on the template
    found_files = self.paths_from_template(search_template, fields)

    st_abstract_key_names = [
        k.name for k in search_template.keys.values() if k.is_abstract
    ]

    # now collapse down the search matches for any abstract fields,
    # and add the leaf level if necessary
    abstract_paths = set()
    for found_file in found_files:

        cur_fields = search_template.get_fields(found_file)

        # pass 1 - go through the fields for this file and
        # zero out the abstract fields - this way, apply
        # fields will pick up defaults for those fields
        #
        # if the system found matches for eye=left and eye=right,
        # by deleting all eye values they will be replaced by %V
        # as the template is applied.
        #

        # this is the fix..
        try:
            for abstract_key_name in st_abstract_key_names:
                del cur_fields[abstract_key_name]
        except:
            abstract_paths.add(found_file)
            continue

        # pass 2 - if we ignored the leaf level, add those fields back
        # note that there is no risk that we add abstract fields at this point
        # since the fields dictionary should only ever contain "real" values.
        # also, we may have deleted actual fields in the pass above and now we
        # want to put them back again.
        for f in fields:
            if f not in cur_fields:
                cur_fields[f] = fields[f]

        # now we have all the fields we need to compose the full template
        abstract_path = template.apply_fields(cur_fields)
        abstract_paths.add(abstract_path)

    return list(abstract_paths)


def sync_frame_range_and_fps():
    import sgtk
    en = sgtk.platform.current_engine()
    ctx = en.context
    sg = en.shotgun

    fps = int(project_field_value('sg_fps', 25))
    cut_in = int(entity_field_value('sg_cut_in', 1001))
    cut_out = int(entity_field_value('sg_cut_out', 1100))

    cur_fps = hou.fps()
    cur_cut_in, cur_cut_out = hou.playbar.frameRange()
    out = []
    if cur_fps != fps:
        out.append("FPS:  {0} -> {1}".format(int(cur_fps), fps))

    if cur_cut_in != cut_in:
        out.append(
            "START_FRAME:  {0} -> {1}".format(int(cur_cut_in), cut_in))

    if cur_cut_out != cut_out:
        out.append(
            "END_FRAME:  {0} -> {1}".format(int(cur_cut_out), cut_out))

    if out:
        ok = not hou.ui.displayMessage('\n'.join(out), buttons=('Ok', 'Cancel'), title="Frame range and FPS change detected.",
                                       help="Update with the latest frame ranges and FPS from Shotgrid?")
        if ok:
            hou.setFps(fps)
            hou.playbar.setFrameRange(cut_in, cut_out)
            hou.playbar.setPlaybackRange(cut_in, cut_out)


def get_tempfile_name():
    return os.path.join(tempfile.gettempdir(), next(tempfile._get_candidate_names())).replace("\\", "/")


def update_materials():
    import sgtk
    import glob
    import re
    import os
    import sys
    import platform
    network_io = hou.nodeType("wg::Driver/network::1.0").hdaModule()

    RENDER2MAT = {
        'redshift': 'redshift::principledshader::1.0',
        'mantra': 'wg::principledshader::2.0',
    }

    """
    RENDER2GLASSMAT = {
        'redshift': 'redshift::principledshader::1.0',
        'mantra': 'wg::principledshader::2.0',
    }
    """

    MATPARMS = {
        'principledshader': {
            'color': {'basecolor': [1.0], 'basecolor_useTexture': True, 'basecolor_texture': '{0}'},
            'emitcolor': {'emitcolor': [1.0], 'emitcolor_useTexture': True, 'emitcolor_texture': '{0}'},
            'spec': {'reflect': [1.0], 'reflect_useTexture': True, 'reflect_texture': '{0}'},
            'rough': {'rough': [1.0], 'rough_useTexture': True, 'rough_texture': '{0}'},
            'metal': {'metallic': [1.0], 'metallic_useTexture': True, 'metallic_texture': '{0}'},
            'bump': {'bump': [0.1], 'bump_enable': True, 'bump_texture': '{0}'},
            'normal': {'bump': [1.0], 'bump_enable': True, 'bump_type': 'normal', 'bump_texture': '{0}'},
            'opac': {'opac': [1.0], 'opac_useTexture': True, 'opac_texture': '{0}'},
            'disp': {'disp': [0.1], 'disp_enable': True, 'disp_texture': '{0}'},
        },

    }

    DEFAULT_MATPARMS = MATPARMS['principledshader']

    en = sgtk.platform.current_engine()
    ctx = en.context
    sg = en.shotgun

    RENDERNAME = project_field_value('sg_render', 'mantra').lower()

    def set_comment(node, comment):
        node.setComment(comment)
        node.setGenericFlag(hou.nodeFlag.DisplayComment, True)

    def set_mat_chan(node, chan, tex):
        nodetype = node.type()
        _, _, typename, _ = nodetype.nameComponents()

        parms = MATPARMS.get(typename, DEFAULT_MATPARMS)
        fulltype_parms = MATPARMS.get(nodetype.name(), None)
        if fulltype_parms:
            parms.update(fulltype_parms)

        tex = tex.replace('\\', '/')
        for k, v in parms.get(chan, {}).iteritems():
            if type(v) == str:
                v = v.format(tex)
                p = node.parm(k)
            elif type(v) == bool:
                p = node.parm(k)
            else:
                p = node.parmTuple(k)
                if p and len(p) > 1 and len(v) == 1:
                    v = v * len(p)
            if p:
                p.set(v)

    _prog = re.compile('.v[0-9]{3}.')

    def get_publish_name(path):
        name = os.path.basename(path)
        return _prog.sub('.', name)

    def work_textures():
        work_template = en.get_template_by_name("work_asset_texture")

        fields = ctx.as_template_fields(work_template)

        return abstract_paths_from_template(ctx.sgtk, work_template, fields)

    def published_textures():
        filters = [
            #['project.Project.id', 'is', ctx.project['id']],
            ['entity.Asset.id', 'is', ctx.entity['id']],
            ['task.Task.step.Step.code', 'is', 'Texture'],
            ['published_file_type.PublishedFileType.code', 'is', 'Texture'],
        ]

        summary_fields = [{'field': 'version_number', 'type': 'maximum'}]

        order = [{'field_name': 'version_number', 'direction': 'asc'}]
        grouping = [{'field': 'name', 'type': 'exact', 'direction': 'asc'}]

        data = sg.summarize('PublishedFile', filters,
                            summary_fields, grouping=grouping)
        if not data:
            return []

        data = data['groups']

        asset_root_template = en.get_template_by_name("asset_root")
        fields = ctx.as_template_fields(asset_root_template)
        fields['Step'] = 'TXT'
        root_path = ctx.sgtk.paths_from_template(asset_root_template, fields)
        if not root_path:
            return []
        root_path = root_path[0]
        tex_publish_path = os.path.join(root_path, 'publish', 'caches')
        # print tex_publish_path

        def path_from_name(name, ver):
            basename, ext = os.path.splitext(name)
            if basename.endswith('.####'):
                basename, _ = os.path.splitext(basename)
                return os.path.join(tex_publish_path, '{0}.v{1:03}.<UDIM>{2}'.format(basename, ver, ext))
            return os.path.join(tex_publish_path, '{0}.v{1:03}{2}'.format(basename, ver, ext))

        result = [path_from_name(d['group_name'], d['summaries'].get('version_number', 0)) for d in data ]
       
        return result

    def generate_matnet_from_geo(matnet, mattype, sop):
        matnet_name = matnet.name()
        geo = sop.geometry()
        try:
            mats = set(geo.primStringAttribValues('shop_materialpath'))
        except:
            return

        new_nodes_count = 0
        for mat in mats:
            s = mat.split('/')
            if len(s) < 4:
                continue

            asset = s[2]
            if asset != matnet_name:
                continue
            mat_name = s[3]
            mat_node = matnet.node(mat_name)
            if not mat_node:
                mat_node = matnet.createNode(mattype, mat_name)
                new_nodes_count += 1
                # mat_node.moveToGoodPosition()
            mat_node.setMaterialFlag(True)
        if new_nodes_count:
            matnet.layoutChildren()

    def generate_matnet(matnet, mattype, textures, template):

        new_nodes_count = 0
        for file in textures:
            fields = template.validate_and_get_fields(file)
            if fields is None:
                continue
            mat_name = fields['mat.name']
            mat_channel = fields['mat.channel']
            mat_node = matnet.node(mat_name)
            if not mat_node:
                mat_node = matnet.createNode(mattype, mat_name)
                new_nodes_count += 1
                # mat_node.moveToGoodPosition()
            mat_node.setMaterialFlag(True)
            set_mat_chan(mat_node, mat_channel, file)

        if new_nodes_count:
            matnet.layoutChildren()

        #matnet.setSelected(True, clear_all_selected=True, show_asset_if_selected=True)

    def update_textures(matnet, textures):
        textures = dict(
            (get_publish_name(t), t)
            for t in textures
        )

        def _tex_upver(node):
            for p in node.parms():
                if not isinstance(p.parmTemplate(), hou.StringParmTemplate):
                    continue
                try:
                    p.expression()
                    continue
                except:
                    pass
                texpath = p.eval()
                #texpath = _texpath.replace('%(UDIM)d', '<UDIM>')

                texname = get_publish_name(texpath)

                new_texpath = textures.get(texname, None)
                if new_texpath:
                    # if _texpath != texpath:
                    #    new_texpath = new_texpath.replace('<UDIM>', '%(UDIM)d')
                    p.set(new_texpath.replace('\\', '/'))

        for node in matnet.children():
            _tex_upver(node)
            ntc = node.childTypeCategory()
            if (not node.isLockedHDA()) and ntc and ntc.name() == 'Vop':
                for n in node.children():
                    _tex_upver(n)

    def matnet_node(assetname, readable=False):
        matnet = hou.node('/shop/%s' % assetname)
        if matnet and matnet.type().name() != 'matnet':
            matnet.destroy()
            matnet = None
        if not matnet:
            matnet = hou.node('/shop').createNode('matnet', assetname)

        if readable and not matnet.comment().strip().startswith('#'):
            network_io.add_network_reader_parms(matnet, pattern="*.matnet")

        return matnet

    def update_matnet(asset, shot=None, stepname='Surface'):

        filters = [
            ['entity.Shot.id', 'is', shot['id']] if shot else [
                'entity.Asset.id', 'is', asset['id']],
            ['published_file_type.PublishedFileType.code', 'is', 'Material Network'],
            ['name', 'is', asset['name'] + '.matnet']
        ]
        if stepname:
            filters.append(['task.Task.step.Step.code', 'is', stepname])

        path = sg.find_one("PublishedFile",
                           filters,
                           fields=["path"],
                           order=[
                               {'field_name': 'version_number', 'direction': 'desc'}],
                           )
        if not path:
            return

        path = path['path']
        path = path['local_path_' + platform.system().lower()
                    ].replace('\\', '/')

        matnet = matnet_node(asset['name'], readable=True)
        if matnet.comment().strip().startswith('#'):
            return

        matnet.parm('network_filename').set(path)
        matnet.parm('network_reload').pressButton()

        return True

    entity_type = ctx.entity['type']

    if entity_type == 'Asset':
        assetname = ctx.entity['name']
        matnet = matnet_node(assetname)

        if ctx.step['name'] in ('Surface', 'Texture'):
            mattype = RENDER2MAT.get(RENDERNAME, None)
            if not mattype:
                raise Exception(
                    "Invalid 'RENDER' field in SG. Please set valid render string in SG project 'RENDER' field")

            for n in hou.node('/obj').children():
                if n.childTypeCategory().name() != 'Sop':
                    continue
                sop = n.renderNode()
                if not sop:
                    continue
                generate_matnet_from_geo(matnet, mattype, sop)

            if ctx.step['name'] == 'Texture':
                textures = work_textures()
                generate_matnet(matnet, mattype, textures,
                                en.get_template_by_name("work_asset_texture"))
            else:
                textures = published_textures()
                generate_matnet(matnet, mattype, textures,
                                en.get_template_by_name("publish_asset_texture"))
                update_textures(matnet, textures)

            matnet.setSelected(True, True)

        else:
            subassets = sg.find_one(
                "Asset", [["id", "is", ctx.entity['id']]], ['assets'])
            assets = subassets.get('assets', []) if subassets else []
            assets.append(ctx.entity)

            for asset in assets:
                update_matnet(asset, stepname='Surface')

    elif entity_type == 'Shot':
        assets = sg.find_one(
            "Shot", [["id", "is", ctx.entity['id']]], ['assets'])
        if assets:
            assets = assets.get('assets', [])

        for asset in assets:
            if not update_matnet(asset, shot=ctx.entity, stepname=None):
                update_matnet(asset, stepname='Surface')

            subassets = sg.find_one(
                "Asset", [["id", "is", asset['id']]], ['assets'])
            subassets = subassets.get('assets', []) if subassets else []

            for subasset in subassets:
                if not update_matnet(subasset, shot=ctx.entity, stepname=None):
                    update_matnet(subasset, stepname='Surface')

    hou.node('/shop').layoutChildren()


def update_rops(create_if_not_exists=False):
    import hou
    import sgtk

    main_template = "${STEPPATH}/publish/render/${TASK}/\${OS}/${VER}/${ENTITY}_${TASK}_\${OS}_acescg.${VER}.\$F4.exr"
    cryptoobj_template = "${STEPPATH}/publish/render/${TASK}/\${OS}/${VER}/${ENTITY}_${TASK}_\${OS}_cryptoobj.${VER}.\$F4.exr"
    cryptomat_template = "${STEPPATH}/publish/render/${TASK}/\${OS}/${VER}/${ENTITY}_${TASK}_\${OS}_cryptomat.${VER}.\$F4.exr"

    en = sgtk.platform.current_engine()
    ctx = en.context
    sg = en.shotgun

    ROPTYPEMAP = {
        'mantra': 'ifd',
        'redshift': 'Redshift_ROP',
    }

    RENDERNAME = project_field_value('sg_render', 'mantra').lower()
    ROPTYPE = ROPTYPEMAP[RENDERNAME]

    def create_beauty_rop():
        outnet = hou.node("/out")
        beauty_node = outnet.node('beauty')
        if beauty_node and beauty_node.type().name() != ROPTYPE:
            beauty_node.destroy()
            beauty_node = None

        if not beauty_node:
            beauty_node = outnet.createNode(ROPTYPE, 'beauty')
            beauty_node.moveToGoodPosition()

    if create_if_not_exists:
        create_beauty_rop()

    if RENDERNAME == 'mantra':
        outnet = hou.node("/out")

        for node in outnet.children():
            if node.type().name() != ROPTYPE:
                continue
            main_p = node.parm('vm_picture')
            if not main_p:
                continue

            checkpoint_p = node.parm('vm_writecheckpoint')
            if checkpoint_p:
                checkpoint_p.deleteAllKeyframes()
                checkpoint_p.set(False)

            main_p.deleteAllKeyframes()
            main_p.set(hou.text.expandString(main_template))
            for i in range(1, node.evalParm('vm_cryptolayers') + 1):
                cryptolayeroutput_p = node.parm('vm_cryptolayeroutput%s' % i)
                cryptolayeroutput_p.deleteAllKeyframes()
                if node.evalParm('vm_cryptolayerprop%s' % i) == 'name':
                    cryptolayeroutput_p.set(
                        hou.text.expandString(cryptoobj_template))
                else:
                    cryptolayeroutput_p.set(
                        hou.text.expandString(cryptomat_template))

    elif RENDERNAME == 'redshift':
        outnet = hou.node("/out")

        for node in outnet.children():
            if node.type().name() != ROPTYPE:
                continue
            main_p = node.parm('RS_outputFileNamePrefix')
            if not main_p:
                continue
            main_p.deleteAllKeyframes()
            main_p.set(hou.text.expandString(main_template))
            for i in range(1, node.evalParm('RS_aov') + 1):
                if node.parm('RS_aovID_%s' % i).evalAsString() != 'CRYPTOMATTE':
                    continue
                cryptolayeroutput_p = node.parm('RS_aovCustomPrefix_%s' % i)
                cryptolayeroutput_p.deleteAllKeyframes()
                cryptotype = node.parm(
                    'RS_aovCryptomatteType_%s' % i).evalAsString()
                if cryptotype == 'RS_BLOCKSINKCRYPTOMATTETYPE_MESHID':
                    cryptolayeroutput_p.set(
                        hou.text.expandString(cryptoobj_template))
                elif cryptotype == 'RS_BLOCKSINKCRYPTOMATTETYPE_MATERIALID':
                    cryptolayeroutput_p.set(
                        hou.text.expandString(cryptomat_template))


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
    update_rops()


def set_env(ctx=None, filepath=None):
    import sgtk

    if ctx is None:
        en = sgtk.platform.current_engine()
        ctx = en.context
        sg = en.shotgun
        if filepath is None:
            filepath = hou.hipFile.name()

    hou.hscript('setenv -u JOB')
    hou.hscript('setenv -u SHOTPATH')
    hou.hscript('setenv -u ASSETPATH')
    hou.hscript('setenv -u ENTITYPATH')
    hou.hscript('setenv -u ENTITY')
    hou.hscript('setenv -u STEPPATH')
    hou.hscript('setenv -u RELSTEPPATH')
    hou.hscript('setenv -u SHOT')
    hou.hscript('setenv -u ASSET')
    hou.hscript('setenv -u STEP')
    hou.hscript('setenv -u TASK')
    hou.hscript('setenv -u VER')

    if not filepath:
        hou.hscript('varchange')
        update_rops()
        return

    ver = ver_from_path(filepath)
    if ver is not None:
        hou.hscript('setenv VER = %s' % ver)

    en = sgtk.platform.current_engine()
    ctx.sgtk.create_filesystem_structure(ctx.entity['type'], ctx.entity['id'])

    root_template_name = ctx.entity.get('type', '').lower() + '_root'
    root_template = en.get_template_by_name(root_template_name)
    if not root_template:
        return

    root_path = None
    entity_root_path = None

    job = ctx.sgtk.roots.get('primary')
    if job:
        hou.hscript('setenv JOB = %s' % job.replace('\\', '/'))

    fields = ctx.as_template_fields(root_template)
    root_path = ctx.sgtk.paths_from_template(
        root_template, fields)

    if not root_path:
        return

    root_path = root_path[0].replace("\\", "/")
    entity_root_path, stepcode = os.path.split(root_path)
    hou.hscript('setenv ENTITYPATH = %s' % entity_root_path)
    hou.hscript('setenv ENTITY = %s' % ctx.entity['name'])

    if ctx.step:
        hou.hscript('setenv STEPPATH = %s' % root_path)
        hou.hscript('setenv STEP = %s' % stepcode)

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
    update_rops()
    sync_frame_range_and_fps()


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

    finally:
        node.setDisplayFlag(is_display)
        scale_p.set(old_scale)
        scale_p.lock(is_locked)


def alembic_export(root, objects, filename, start=1, end=1, preroll=0, samples=2, build_from_path=False):
    is_animated = end > start
    if is_animated:
        is_animated = False
        for node_path in objects.split():
            node = hou.node(node_path)
            if not node:
                continue
            if is_time_dependent(node):
                is_animated = True
                break

    # add 2 frames to the ends and preroll
    start_frame = max(0, start - 2 - preroll)
    end_frame = end + 2

    tmp_alembic_node = hou.node('/out/__tmp__alembic__')
    if tmp_alembic_node:
        tmp_alembic_node.destroy()
    tmp_alembic_node = hou.node(
        '/out').createNode('alembic', '__tmp__alembic__')
    tmp_filename = get_tempfile_name() + '.abc'
    try:
        tmp_alembic_node.setParms({
            'trange': int(is_animated),
            'filename': tmp_filename,
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
        try:
            os.rename(tmp_filename, filename)
        except:
            os.remove(filename)
            os.rename(tmp_filename, filename)

    finally:
        tmp_alembic_node.destroy()
        try:
            os.remove(tmp_filename)
        except:
            pass
