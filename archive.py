#!/bin/python
import os
import datetime

curdir = os.path.dirname(__file__)
basename = os.path.basename(curdir)
now = datetime.datetime.now()
timestr = now.strftime("%d.%m.%Y_%H.%M")
out = f"../{basename}_{timestr}.zip"

os.system(f'git archive -o "{out}" HEAD')
