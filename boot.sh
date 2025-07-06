#!/bin/bash
ascii_art='''
   _____                     _ _____
  / ____|                   | |  __ \
 | (___  _ __   ___  ___  __| | |__) |   _
  \___ \| |_ \ / _ \/ _ \/ _| |  ___/ | | |
  ____) | |_) |  __/  __/ (_| | |   | |_| |
 |_____/| .__/ \___|\___|\__,_|_|    \__, |
        | |                           __/ |
        |_|                          |___/ '''


echo -e "$ascii_art"
echo "=> SpeedPy.com Django-based Boilerplate requires Docker installed."
. ./pre_check.sh
echo "Selecting the clone target path:"
target_path="project"

while [ -e "./$target_path" ]; do
    target_path="project_$(( RANDOM % 1000 ))"
done

echo "Using path: $target_path"

echo "Cloning install scripts:"
git clone -q https://github.com/speedpy/speedpy.git $target_path >/dev/null
cd $target_path
if [[ $SPEEDPYCOM_REF != "master" ]]; then
	git fetch -q origin "${SPEEDPYCOM_REF:-master}" && git checkout "${SPEEDPYCOM_REF:-master}"
fi
rm -rf .git
echo "Initializing the project starting..."
bash init.sh