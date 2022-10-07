#!/bin/bash

set -e

# version found in VERSION file
VERSION=$(python -c 'print(float(open("buttervolume/VERSION").read().strip()))')

# last version found in the changelog
CHANGES_VERSION=$(grep '^[0-9].*(.*)' CHANGES.rst | head -1 | cut -d' ' -f1)

# last date found in the changelog
LASTDATE=$(grep '^[0-9].*(.*)' CHANGES.rst | head -1 | cut -d' ' -f2 | tr -d '(' | tr -d ')')


if [ "$VERSION" == "" ]; then echo "Check version number"; exit 1; fi
if [ "$VERSION" != "$CHANGES_VERSION" ]; then echo "Check version in VERSION and CHANGES.rst"; exit 1; fi
if ! date --date=$LASTDATE "+%d-%B-%Y" > /dev/null; then echo "Check the last date in the CHANGES.rst"; exit 1; fi
echo "OK"
echo "(Release Check List)"
echo "- check the changelog"
echo "- git tag"
echo "- start from a clean git clone"
echo "- build the plugin"
echo "- push it to the docker hub"
echo "- publish to PyPI (python setup.py ...)"
