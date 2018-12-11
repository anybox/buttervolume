from setuptools import setup, find_packages
import sys

if sys.version_info < (3, 5):
    sys.exit("Buttervolume currently works only with Python >= 3.5. "
             "We will accept any contribution to support older versions")

setup(
    name="buttervolume",
    version="3.6",
    author="Christophe Combelles",
    author_email="ccomb@anybox.fr",
    url="https://github.com/anybox/buttervolume",
    license="Apache License, Version 2.0",
    description="Docker plugin to manage Docker Volumes as BTRFS subvolumes",
    long_description=open('README.rst').read() + '\n'
        + open('CHANGES.rst').read(),
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "buttervolume = buttervolume.cli:main",
        ],
    },
    install_requires=[
        "bottle",
        "urllib3<=1.22",
        "requests-unixsocket",
        "waitress",
        "webtest",
    ],
    tests_require=[
    ],
    test_suite='test',
    classifiers=[
        "Programming Language :: Python :: 3",
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: POSIX :: Linux",
        "Topic :: System :: Clustering",
        ],
)
