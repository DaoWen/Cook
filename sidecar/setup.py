#!/usr/bin/env python3

from setuptools import setup

from cook.sidecar import version

requirements = [
    'Flask==1.1.0',
    'gunicorn==19.9.0',
    'requests==2.20.0',
]

test_requirements = [
]

setup(
    name='cook_sidecar',
    version=version.__version__,
    description="Two Sigma's Cook Sidecar",
    long_description="This package contains Two Sigma's Cook Sidecar. "
                     "The primary purposes are to serve log files and report job progress.",
    packages=['cook.sidecar'],
    entry_points={'console_scripts': ['cook-sidecar = cook.sidecar.__main__:main']},
    install_requires=requirements,
    tests_require=test_requirements
)
