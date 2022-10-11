#!/bin/bash

VERSION=$1
if [ "$VERSION" == "" ]; then
    VERSION="HEAD"
    echo "#####################"
    echo "Testing version HEAD. You can test another version with: ./test.sh <VERSION>"
    echo "Please not that only locally commited changes will be tested"
    echo "#####################"
else
    echo "#####################"
    echo "Testing version $VERSION"
    echo "#####################"
fi

pushd $( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd ) > /dev/null
rm -f buttervolume.zip
git archive -o buttervolume.zip $VERSION
docker build --build-arg VERSION=$VERSION -t anybox/buttervolume_test:$VERSION . --no-cache
test="sudo docker run -it --rm --privileged -v /var/lib/docker:/var/lib/docker -v $PWD:/usr/src/buttervolume -w /usr/src/buttervolume anybox/buttervolume_test:HEAD test"
$test
echo "You can run tests again with:"
echo "$test"
popd
