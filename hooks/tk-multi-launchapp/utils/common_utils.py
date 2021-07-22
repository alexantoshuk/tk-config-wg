import glob
import os
from datetime import datetime


def seq_files(seqpath):
    s = seqpath.rsplit('.', 2)
    if len(s) < 3:
        return None

    s[-2] = '*'
    pattern = '.'.join(s)
    l = sorted(os.path.normpath(f) for f in glob.iglob(pattern))
    if l:
        return l
    return None


def datetime_str():
    now = datetime.now()
    return now.strftime("%b-%d-%Y %H:%M:%S")


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
