from setuptools import setup, find_packages

setup(
    name="buttervolume",
    version="1.0",
    author="Christophe Combelles",
    author_email="ccomb@anybox.fr",
    url="https://github.com/anybox/buttervolume",
    license="Apache License, Version 2.0",
    description="Docker plugin to manage Docker Volumes as BTRFS subvolumes",
    long_description=open('README.rst').read() + '\n' + open('CHANGES.rst').read(),
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "buttervolume = buttervolume.plugin:main",
        ],
    },
    install_requires=[
        "bottle",
        "waitress",
    ],
    tests_require=[
        "bottle",
        "webtest",
    ],
    test_suite='test',
)
