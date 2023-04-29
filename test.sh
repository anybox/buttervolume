#!/bin/bash

VERSION=$1
rm -f buttervolume.zip
pushd $( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd ) > /dev/null
if [ "$VERSION" == "" ]; then
    VERSION="HEAD"
    echo "#####################"
    echo "Testing working directory with uncommited changes."
    echo "You can test another version with: ./test.sh <VERSION>"
    echo "#####################"
    git archive -o buttervolume.zip `git stash create`
else
    echo "#####################"
    echo "Testing version $VERSION"
    echo "#####################"
    git archive -o buttervolume.zip $VERSION
fi

docker build --build-arg VERSION=$VERSION -t anybox/buttervolume_test:$VERSION . --no-cache
test="sudo docker run -it --rm --privileged -v /var/lib/docker:/var/lib/docker -v $PWD:/usr/src/buttervolume -w /usr/src/buttervolume anybox/buttervolume_test:HEAD test"
$test
echo "#############################"
echo "You can run tests again with:"
echo "$test"
echo "#############################"
popd
