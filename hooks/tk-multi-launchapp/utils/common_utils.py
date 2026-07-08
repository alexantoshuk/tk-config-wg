import glob
import os
from datetime import datetime
import sys
import subprocess
import platform


def need_update():
    import sgtk

    # Get the current engine
    engine = sgtk.platform.current_engine()

    # Access the ShotGrid API
    sg = engine.shotgun

    # Get the current engine
    engine = sgtk.platform.current_engine()

    # Get the breakdown app
    breakdown_app = engine.apps["tk-multi-breakdown"]

    # Run the scene analysis
    breakdown_items = breakdown_app.analyze_scene()
    print("SG DEBUG: ", breakdown_items)
    for breakdown_item in breakdown_items:
        sg_data = breakdown_item['sg_data']
        if not sg_data:
            continue
        project = sg_data['project']
        entity = sg_data['entity']
        filters = [
            ["name", "is", sg_data['name']],
            ["published_file_type", "is", sg_data['published_file_type']],
            ["entity", "is", entity],
            ["project", "is", project]
        ]

        fields = ["version_number"]

        versions = sg.find("PublishedFile", filters, fields, order=[
                           {"field_name": "version_number", "direction": "desc"}])

        # Check if versions exist
        if versions:
            # The first version in the sorted list is the latest version
            latest_version = versions[0]
            latest_version_number = latest_version["version_number"]
            cur_version_number = sg_data['version_number']
            if latest_version_number != cur_version_number:
                return True

    return False


def remove_version_from_path(path):
    path = path.rsplit('.', 2)
    del path[-2]
    path = '.'.join(path)
    return path


def perforce_username():
    out = subprocess.check_output(['p4', 'user', '-o'])
    return out.rsplit(sep=None, maxsplit=1)[-1].decode()


def perforce_login():
    passwd = os.environ['P4PASSWD']
    return subprocess.check_output(['p4', 'login'], input=passwd.encode())


def perforce_add(client, filename):
    out = subprocess.check_output(['p4', '-c', client, 'add', filename])
    return out


def perforce_edit(client, filename):
    out = subprocess.check_output(['p4', '-c', client, 'edit', filename])
    return out


def perforce_submit(client, filename, description):
    out = subprocess.check_output(
        ['p4', '-c', client, 'submit', '-d', description, filename])
    return out


def perforce_client_name(dirname, username):
    def _info(client_str):
        splited = client_str.split()
        return (splited[1], splited[4].replace('\\', '/'), splited[-2][:-1])

    hostname = platform.node()
    result = []
    out = subprocess.check_output(['p4', 'clients'])
    for c in out.decode().split('\n')[:-1]:
        data = _info(c)
        _client, _dirname, _username = data
        if dirname == _dirname and username == _username and hostname in _client:
            return _client

    return None


def perforce_checkout(ue_projpath, filename):
    if not os.path.isfile(filename):
        return
    perforce_login()
    username = perforce_username()
    clientname = perforce_client_name(ue_projpath, username)

    try:
        perforce_add(clientname, filename)
    except Exception as e:
        sys.stderr.write("DEBUG PERFORCE: %s\n" % e)
        try:
            perforce_edit(clientname, filename)
        except Exception as e:
            sys.stderr.write("DEBUG PERFORCE: %s\n" % e)


def seq_files(seqpath, seq_pattern='<UDIM>'):
    pattern = seqpath.replace(seq_pattern, '*')
    if pattern == seqpath:
        return None

    l = sorted(os.path.normpath(f) for f in glob.iglob(pattern))
    if l:
        return l
    return None


def datetime_str():
    now = datetime.now()
    return now.strftime("%b-%d-%Y %H:%M:%S")


def project_field_value(name, default=None, context=None):
    import sgtk
    en = sgtk.platform.current_engine()
    ctx = context if context else en.context
    sg = en.shotgun

    field_val = sg.find_one(
        "Project", [["id", "is", ctx.project['id']]], [name])
    if field_val:
        field_val = field_val.get(name, default)
    if field_val is None:
        return default
    return field_val


def entity_field_value(name, default=None, context=None):
    import sgtk
    en = sgtk.platform.current_engine()
    ctx = context if context else en.context
    sg = en.shotgun

    entity_type = ctx.entity['type']
    entity_id = ctx.entity['id']

    field_val = sg.find_one(
        entity_type, [["id", "is", entity_id]], [name])
    if field_val:
        field_val = field_val.get(name, default)
    if field_val is None:
        return default
    return field_val


def task_field_value(name, default=None, context=None):
    import sgtk
    en = sgtk.platform.current_engine()
    ctx = context if context else en.context
    sg = en.shotgun

    field_val = sg.find_one(
        "Task", [["id", "is", ctx.task['id']]], [name])
    if field_val:
        field_val = field_val.get(name, default)
    if field_val is None:
        return default
    return field_val


def update_status():
    import sgtk
    en = sgtk.platform.current_engine()
    ctx = en.context
    sg = en.shotgun

    current_status = sg.find_one(
        "Task", [["id", "is", ctx.task['id']]], ['sg_status_list'])
    if current_status:
        current_status = current_status.get('sg_status_list')

    if current_status in ('fin', 'clsd'):
        return
    new_status = 'rev'
    try:
        sg.update("Task", ctx.task['id'], {'sg_status_list': new_status})
    except:
        sys.stderr.write(
            "WARNING: Can't update task status to '{0}' from this user.\n".format(new_status))


# def cleanup_seq_versions(path, seq_paths, max_versions=10, logger=None):
#     if max_versions <= 0:
#         return False
#     s = seq_paths[0].rsplit('.', 3)
#     if len(s) < 4:
#         return False
#     s[-3] = '*'
#     pattern = '.'.join(s)

#     valid_old_file = sorted(glob.iglob(pattern))[-max_versions]
#     s = valid_old_file.rsplit('.', 3)


def cleanup_versions(filepath, pattern="???.abc", max_versions=10, logger=None):
    # limit number of versions to max_versions
    if max_versions <= 0:
        return

    pattern = filepath[:-len(pattern)] + pattern
    files = []
    for f in sorted(glob.iglob(pattern))[:-max_versions]:
        try:
            os.remove(f)
            files.append()
            if logger:
                logger.info(
                    "Remove '{0}' because of version limit = {1}".format(f, max_versions))
        except:
            if logger:
                logger.info("Can't remove '{0}'".format(f))


def fbx_remove_namespaces(path):
    kwargs = {}
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

    result = subprocess.run(
        ["fbx_find_replace", path, path, "^.*:", "--regex"], check=True, capture_output=True, text=True, **kwargs)

    return result.stdout
