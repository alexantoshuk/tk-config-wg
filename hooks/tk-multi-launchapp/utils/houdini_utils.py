
import hou
import sys
import os
import shutil
import tempfile
from common_utils import project_field_value, entity_field_value


def injectJOB(path):
    def expand_var(path, var):
        if var and path.startswith(var + '/'):
            return "/".join((hou.getenv(var[1:]), path[len(var) + 1:]))
        return path

    def collapse_var(path, var):
        varval = hou.getenv(var[1:])
        if varval and path.startswith(varval):
            return var + path[len(varval):]
        return path

    path = expand_var(path, "$HIP")
    path = expand_var(path, "$JOB")

    path = collapse_var(path, "$LIB")
    path = collapse_var(path, "$JOB")

    return path


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


def sync_fps():
    fps = int(project_field_value('sg_fps', 25))
    cur_fps = hou.fps()
    hou.setFps(fps)


def sync_frame_range_and_fps():
    fps = int(project_field_value('sg_fps', 25))
    edit_handles = int(entity_field_value('sg_edit_handles', 0))
    cut_in = int(entity_field_value('sg_cut_in', 1001)) - edit_handles
    cut_out = int(entity_field_value('sg_cut_out', 1100)) + edit_handles

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

        result = [path_from_name(d['group_name'], d['summaries'].get(
            'version_number', 0)) for d in data]

        return result

    def generate_matnet_from_geo(matnet, mattype, sop):
        if not matnet:
            return
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

            asset = s[-2]
            if asset != matnet_name:
                continue
            mat_name = s[-1]
            mat_node = matnet.node(mat_name)

            if not mat_node:
                mat_node = matnet.createNode(mattype, mat_name)
                new_nodes_count += 1
                # mat_node.moveToGoodPosition()
            mat_node.setMaterialFlag(True)
        if new_nodes_count:
            matnet.layoutChildren()

    def generate_matnet(matnet, mattype, textures, template):
        """
        Generation of materials from published textures
        """

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

    def generate_matnet_old(matnet, mattype, texpath):

        def validate_and_get_fields(file):
            dirname, basename = os.path.split(file)
            mat_name = os.path.basename(dirname)
            if mat_name == "tex":
                mat_name = "default"
            basename = basename.split(".", 1)[0]
            mat_channel, _, colorspace = basename.partition("_")
            if not colorspace:
                return None
            return {"mat.name": mat_name, "mat.channel": mat_channel}

        def textures(texpath):
            texs = set()
            for tex in glob.iglob(texpath.replace("\\", "/") + "/*/*.exr"):
                _tex, ext = os.path.splitext(tex)
                before, _, udim = _tex.partition(".")
                if udim and udim.startswith("10"):
                    tex = "{}.<UDIM>{}".format(before, ext)
                texs.add(injectJOB(tex))
            return list(texs)

        new_nodes_count = 0
        for file in textures(texpath):
            fields = validate_and_get_fields(file)
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

    mattype = RENDER2MAT.get(RENDERNAME, None)
    if not mattype:
        raise Exception(
            "Invalid 'RENDER' field in SG. Please set valid render string in SG project 'RENDER' field")

    if entity_type == 'Asset':
        assetname = ctx.entity['name']
        matnet = matnet_node(assetname)

        if ctx.step['name'] in ('Surface', 'Texture'):

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
        #! FIXME: update old type assets
        mat = hou.node("/obj").node("mat")
        if not mat:
            mat = hou.node("/obj").createNode("subnet", "mat")
        for sop in hou.nodeType("Sop/file").instances():
            file = sop.evalParm("file")
            dirname, basename = os.path.split(file)
            assetname = os.path.basename(dirname)
            matnet_path = "/obj/mat/" + assetname
            matnet = hou.node(matnet_path)
            if matnet:
                continue

            texpath = dirname + "/tex"
            if not os.path.isdir(texpath):
                continue

            matnet = mat.createNode("matnet", assetname)
            generate_matnet_from_geo(matnet, mattype, sop)
            generate_matnet_old(matnet, mattype, texpath)

        # Matnets update from published data
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


def update_rops(env, create_if_not_exists=False):
    import hou

    main_path = injectJOB("{STEPPATH}/publish/render/${{OS}}/{VER}/{ENTITY}_{TASK}_${{OS}}_acescg.{VER}.$F4.exr".format(
        **env))
    cryptoobj_path = injectJOB("{STEPPATH}/publish/render/${{OS}}/{VER}/{ENTITY}_{TASK}_${{OS}}_cryptoobj.{VER}.$F4.exr".format(
        **env))
    cryptomat_path = injectJOB("{STEPPATH}/publish/render/${{OS}}/{VER}/{ENTITY}_{TASK}_${{OS}}_cryptomat.{VER}.$F4.exr".format(
        **env))

    ROPTYPEMAP = {
        'mantra': 'ifd',
        'redshift': 'Redshift_ROP',
    }
    mantra_rop_type = ROPTYPEMAP['mantra']
    redshift_rop_type = ROPTYPEMAP['redshift']

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

    outnet = hou.node("/out")
    for node in outnet.children():
        if node.type().name() == mantra_rop_type:
            main_p = node.parm('vm_picture')
            if not main_p:
                continue

            checkpoint_p = node.parm('vm_writecheckpoint')
            if checkpoint_p:
                checkpoint_p.deleteAllKeyframes()
                checkpoint_p.set(False)

            main_p.deleteAllKeyframes()
            main_p.set(main_path)
            for i in range(1, node.evalParm('vm_cryptolayers') + 1):
                cryptolayeroutput_p = node.parm('vm_cryptolayeroutput%s' % i)
                cryptolayeroutput_p.deleteAllKeyframes()
                if node.evalParm('vm_cryptolayerprop%s' % i) == 'name':
                    cryptolayeroutput_p.set(cryptoobj_path)
                else:
                    cryptolayeroutput_p.set(cryptomat_path)

        elif node.type().name() == redshift_rop_type:
            main_p = node.parm('RS_outputFileNamePrefix')
            if not main_p:
                continue
            main_p.deleteAllKeyframes()
            main_p.set(main_path)
            for i in range(1, node.evalParm('RS_aov') + 1):
                if node.parm('RS_aovID_%s' % i).evalAsString() != 'CRYPTOMATTE':
                    continue
                cryptolayeroutput_p = node.parm('RS_aovCustomPrefix_%s' % i)
                cryptolayeroutput_p.deleteAllKeyframes()
                cryptotype = node.parm(
                    'RS_aovCryptomatteType_%s' % i).evalAsString()
                if cryptotype == 'RS_BLOCKSINKCRYPTOMATTETYPE_MESHID':
                    cryptolayeroutput_p.set(cryptoobj_path)
                elif cryptotype == 'RS_BLOCKSINKCRYPTOMATTETYPE_MATERIALID':
                    cryptolayeroutput_p.set(cryptomat_path)


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


def env(ctx=None, hip_filepath=None):
    import sgtk

    en = sgtk.platform.current_engine()
    if ctx is None:
        ctx = en.context
        sg = en.shotgun

    if hip_filepath is None:
        hip_filepath = hou.hipFile.name()

    env_dict = {}

    ctx.sgtk.create_filesystem_structure(ctx.entity['type'], ctx.entity['id'])
    root_template_name = ctx.entity.get('type', '').lower() + '_root'
    root_template = en.get_template_by_name(root_template_name)
    if not root_template:
        return env_dict

    fields = ctx.as_template_fields(root_template)
    root_path = ctx.sgtk.paths_from_template(
        root_template, fields)

    if not root_path:
        return env_dict

    ver = ver_from_path(hip_filepath)
    if not ver:
        ver = 'v000'

    env_dict['VER'] = ver

    root_path = root_path[0].replace("\\", "/")
    entity_root_path, stepcode = os.path.split(root_path)
    env_dict['ENTITYPATH'] = entity_root_path
    env_dict['ENTITY'] = ctx.entity['name']

    if ctx.step:
        env_dict['STEPPATH'] = root_path
        env_dict['STEP'] = stepcode

    if ctx.task:
        env_dict['TASK'] = ctx.task['name']

    if ctx.entity.get('type', None) == 'Shot':
        env_dict['SHOTPATH'] = entity_root_path
        env_dict['SHOT'] = ctx.entity['name']

    elif ctx.entity.get('type', None) == 'Asset':
        env_dict['ASSETPATH'] = entity_root_path
        env_dict['ASSET'] = ctx.entity['name']

    return env_dict


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


def is_time_dependent(node):
    td = [False]

    def _walk(node):
        if node.type().category().name() not in ('Object', 'Sop'):
            return
        if node.isTimeDependent():
            td[0] = True
            return True
        child_cat_name = node.childTypeCategory().name()
        if child_cat_name == 'Object':
            for n in node.children():
                if _walk(n):
                    return True
        elif child_cat_name == 'Sop':
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

    is_display = node.isDisplayFlagSet()
    node.setDisplayFlag(1)
    try:
        alembic_export('/obj', subnetpath, filename,
                       start, end, preroll, samples, build_from_path=True, scale=scale)

    finally:
        node.setDisplayFlag(is_display)


def alembic_export(root, objects, filename, start=1, end=1, preroll=0, samples=2, build_from_path=False, scale=1.0):
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

    tmp_alembic_node = hou.node(
        '/out').createNode('alembic', '__tmp__alembic__')
    tmp_filename_base = get_tempfile_name()
    tmp_filename = tmp_filename_base + '.abc'

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

    try:
        tmp_alembic_node.render()

        if scale != 1.0:
            tmp_filename_scaled = tmp_filename_base + '_scaled.abc'
            read_tmp_alembic_obj_node = hou.node(
                '/obj').createNode('geo', '__tmp__alembic__')
            read_tmp_alembic_node = read_tmp_alembic_obj_node.createNode(
                'alembic')
            read_tmp_alembic_node.parm('fileName').set(tmp_filename)
            xform_node = read_tmp_alembic_node.createOutputNode('xform')
            xform_node.setDisplayFlag(True)
            xform_node.setRenderFlag(True)
            xform_node.parm('scale').set(scale)

            tmp_alembic_node.setParms({
                'filename': tmp_filename_scaled,
                'root': '/obj',
                'objects': read_tmp_alembic_obj_node.path(),
            })
            tmp_alembic_node.render()

            shutil.move(tmp_filename_scaled, filename)

        else:
            shutil.move(tmp_filename, filename)

    finally:
        tmp_alembic_node.destroy()
        try:
            read_tmp_alembic_obj_node.destroy()
        except:
            pass
        try:
            os.remove(tmp_filename)            
        except:
            pass
        try:
            os.remove(tmp_filename_scaled)       
        except:
            pass


def inject_JOB_in_subnet(subnet):
    def _walk(n):
        for p in n.parms():
            if (not isinstance(p.parmTemplate(), hou.StringParmTemplate)) or p.keyframes():
                continue

            s = injectJOB(p.unexpandedString())
            try:
                p.set(s)
            except:
                continue
        if n.isLockedHDA():
            return
        for n in n.children():
            _walk(n)

    _walk(subnet)


FLAG_COLOR = {
    '# Publish Alembic': hou.Color((0.04, 0.7, 0.04)),
    '# Publish Camera': hou.Color((0.7, 0.2, 0.25)),
    '# Publish Network': hou.Color((0.2, 0.4, 0.7)),
    '# Publish Material Network': hou.Color((0.2, 0.4, 0.7)),
}


def mix_colors(colors):
    sum_l = 0.0
    sum_a = 0.0
    sum_b = 0.0
    n = len(colors)
    for c in colors:
        l, a, b = c.lab()
        sum_l += l
        sum_a += a
        sum_b += b
    result = hou.Color()
    result.setLAB((sum_l / n, sum_a / n, sum_b / n))
    return result


def set_flag(node, flag):
    valid_flags = FLAG_COLOR.keys()
    if flag not in valid_flags:
        return

    node.setColor(FLAG_COLOR[flag])
    node.setComment(flag)
    node.setGenericFlag(hou.nodeFlag.DisplayComment, True)


def add_flag(node, flag):
    comment = node.comment()
    valid_flags = FLAG_COLOR.keys()

    flags = set(line.strip() for line in comment.split(
        "\n") if line.strip() in valid_flags)
    flag = flag.strip()
    if flag in valid_flags:
        flags.add(flag)

    flags = list(flags)
    clr = mix_colors([FLAG_COLOR[flag] for flag in flags])
    node.setColor(clr)
    node.setComment('\n'.join(flags))
    node.setGenericFlag(hou.nodeFlag.DisplayComment, True)


def remove_flags(node):
    comment = node.comment()
    if not comment:
        return

    node.setColor(node.type().defaultColor())
    node.setComment("")


def get_flags(node):
    comment = node.comment()
    if not comment:
        return []
    valid_flags = FLAG_COLOR.keys()
    flags = set(line.strip() for line in comment.split(
        "\n") if line.strip() in valid_flags)

    return list(flags)


def is_publish_matnet(node):
    return "# Publish Material Network" in get_flags(node)


def is_publish_objnet(node):
    return "# Publish Network" in get_flags(node)


def is_publish_geometry(node):
    return "# Publish Alembic" in get_flags(node)


def is_publish_camera(node):
    return "# Publish Camera" in get_flags(node)
