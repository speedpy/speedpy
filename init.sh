#!/bin/sh

# Generate random port between 9000 and 9999
WEB_PORT=$((9000 + $RANDOM % 1000))
echo " * Using random port: $WEB_PORT"

# Update docker-compose.yml with the random port
sed -i.bak "s/127.0.0.1:9000:9000/127.0.0.1:$WEB_PORT:9000/g" docker-compose.yml

open_url() {
    url=$1

    case "$(uname -s)" in
        Linux*)
            if grep -qi microsoft /proc/version; then
                # WSL
                cmd.exe /c start "$url" >/dev/null 2>&1
            else
                # Regular Linux
                xdg-open "$url" >/dev/null 2>&1
            fi
            ;;
        Darwin*)
            # macOS
            open "$url" >/dev/null 2>&1
            ;;
        *)
            echo "Unsupported operating system"
            exit 1
            ;;
    esac
}
. ./pre_check.sh
USE_TTY=""
test -t 1 && USE_TTY="-T"
echo "USE_TTY=${USE_TTY}"
git init -b master

cp .docker.env .env
echo " * docker compose down -v --remove-orphans"
docker compose down -v --remove-orphans
echo " * Building the Docker image for the project (might take a while)"
docker compose build -q
echo " * Starting DB and redis"
docker compose up -d db redis
sleep 2
echo " * Generating directories for tailwind config"
docker compose run --rm ${USE_TTY} web python manage.py generate_tailwind_directories
echo " * Installing tailwind and dependencies"
docker compose run --rm ${USE_TTY} web bash -c "npm i && npm run tailwind:build"
echo " * Initializing the project"
docker compose run --rm ${USE_TTY} web python manage.py makemigrations
docker compose run --rm ${USE_TTY} web python manage.py migrate
docker compose run --rm ${USE_TTY} web python manage.py makesuperuser > local_password.txt
cat local_password.txt
echo " * Created local superuser credentials are stored in local_password.txt file for your convenience"
git add .
git commit -q -m "Initial commit"

echo " * Starting the project..."
docker compose up -d
sleep 1

count=0; max_retries=5; until curl -s -f -o /dev/null "http://127.0.0.1:$WEB_PORT" || [ $count -ge $max_retries ]; do echo "Waiting... $((count+1))/$max_retries"; count=$((count+1)); sleep 1; done; if [ $count -lt $max_retries ]; then echo "Site is up!"; else echo "App is still down after $max_retries retries"; exit 1; fi

open_url http://127.0.0.1:$WEB_PORT
echo "Open your browser at http://127.0.0.1:$WEB_PORT"