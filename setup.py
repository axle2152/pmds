# Fallback for older setuptools (< 61), such as the one Ubuntu 22.04 ships, which cannot read
# the [project] table in pyproject.toml or do a modern editable install. Newer setuptools takes
# everything from pyproject.toml and this file just calls setup().
import setuptools
from setuptools import setup

if int(setuptools.__version__.split('.')[0]) < 61:
    setup(name='pmds', version='0.1.1', packages=['pmds'], install_requires=['numpy'],
          python_requires='>=3.8')
else:
    setup()
