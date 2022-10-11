#!/bin/bash

set -e

VERSION=$1
if [ "$VERSION" == "" ]; then
    VERSION="HEAD"
    echo "#####################"
    echo "Building version HEAD. You can build another version with: ./rebuild.sh <VERSION>"
    echo "Please not that only locally commited changes will be built"
    echo "#####################"
else
    echo "#####################"
    echo "Building version $VERSION"
    echo "#####################"
fi

# First remove the plugin
if [ "`docker plugin ls | grep anybox/buttervolume:$VERSION | wc -l`" == "1" ]; then
    echo "Removing existing pluging with the same version..."
    docker plugin rm anybox/buttervolume:$VERSION
    if [ $? -ne 0 ]; then
        echo "anybox/buttervolume:$VERSION cannot be removed. Is it running? First disable it with docker plugin disable anybox/buttervolume:$VERSION"
    fi
fi

pushd $( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd ) > /dev/null

echo "Creating an archive for the intended version"
rm -f buttervolume.zip
git archive -o buttervolume.zip $VERSION

echo "Building an image with this version..."
docker build -t rootfs . --no-cache

echo "Exporting the image to a rootfs dir and cleanup the image..."
rm -rf rootfs
id=$(docker create rootfs true)
mkdir rootfs
docker export "$id" | tar -x -C rootfs
docker rm -vf "$id"
docker rmi rootfs

echo "Building the new plugin..."
docker plugin create anybox/buttervolume:$VERSION .

echo "Succeeded!"
popd > /dev/null

echo
echo "Now you can enable the plugin with:"
echo "docker plugin enable anybox/buttervolume:$VERSION"
