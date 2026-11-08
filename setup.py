# Fallback for older setuptools (< 61), such as the one Ubuntu 22.04 ships, which cannot read
# the [project] table in pyproject.toml or do a modern editable install. Newer setuptools takes
# everything from pyproject.toml and this file just calls setup().
import os
import re

import setuptools
from setuptools import setup

if int(setuptools.__version__.split('.')[0]) < 61:
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, 'pyproject.toml')) as f:
        version = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M).group(1)
    setup(name='pmds', version=version, packages=['pmds'], install_requires=['numpy'],
          python_requires='>=3.8', py_modules=['pmds_addon', 'pmds_monitor'],
          entry_points={'all_mode_receiver.addons': ['pmds = pmds_addon:Addon']})
else:
    setup()
