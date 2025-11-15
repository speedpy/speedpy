#!/bin/bash
ascii_art=$(cat <<'EOF'
   _____                     _ _____
  / ____|                   | |  __ \
 | (___  _ __   ___  ___  __| | |__) |   _
  \___ \| |_ \ / _ \/ _ \/ _| |  ___/ | | |
  ____) | |_) |  __/  __/ (_| | |   | |_| |
 |_____/| .__/ \___|\___|\__,_|_|    \__, |
        | |                           __/ |
        |_|                          |___/
EOF
)

echo "$ascii_art"
echo "=> SpeedPy.com Django-based Boilerplate requires Docker installed."

echo "Enter project name (press Enter for auto-generated name):"
read -r project_name

if [ -z "$project_name" ]; then
    # No name provided, use random generation
    echo "Selecting auto-generated clone target path..."
    target_path="project"
    while [ -e "./$target_path" ]; do
        target_path="project_$(( RANDOM % 1000 ))"
    done
    echo "Using auto-generated path: $target_path"
else
    # User provided a name
    target_path="$project_name"
    if [ -e "./$target_path" ]; then
        echo "Error: Directory '$target_path' already exists"
        echo "Please choose a different name or remove the existing directory"
        exit 1
    fi
    echo "Using path: $target_path"
fi

echo "Cloning install scripts:"
git clone -q https://github.com/speedpy/speedpy.git $target_path >/dev/null
cd "$target_path" || { echo "Error: Failed to change to directory $target_path"; exit 1; }
if [[ $SPEEDPYCOM_REF != "master" ]]; then
	git fetch -q origin "${SPEEDPYCOM_REF:-master}" && git checkout "${SPEEDPYCOM_REF:-master}"
fi
rm -rf .git
echo "Initializing project setup (init.sh) ..."
bash init.sh