FROM python:3.13.12-trixie
SHELL ["/bin/bash", "-c"]
ENV PYTHONUNBUFFERED 1
ENV PYTHONDONTWRITEBYTECODE 0
ENV COLUMNS 80
RUN apt-get update \
  && apt-get install -y \
  nano gettext chrpath libssl-dev libxft-dev \
  libfreetype6 libfreetype6-dev  libfontconfig1 libfontconfig1-dev\
  && rm -rf /var/lib/apt/lists/*
ENV NODE_VERSION=25.8.1
ENV NVM_DIR=/usr/local/nvm
RUN apt install -y curl
RUN mkdir -p $NVM_DIR && curl -o- https://raw.githubusercontent.com/creationix/nvm/v0.40.4/install.sh | bash
RUN . "$NVM_DIR/nvm.sh" && nvm install ${NODE_VERSION}
RUN . "$NVM_DIR/nvm.sh" && nvm use v${NODE_VERSION}
RUN . "$NVM_DIR/nvm.sh" && nvm alias default v${NODE_VERSION}
ENV PATH="/usr/local/nvm/versions/node/v${NODE_VERSION}/bin/:${PATH}"
RUN node --version
RUN npm --version
RUN npm install --global yarn@1.22.22
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
WORKDIR /code/
COPY pyproject.toml uv.lock /code/
RUN UV_PROJECT_ENVIRONMENT=/usr/local uv sync --frozen
COPY . /code/
RUN useradd -ms /bin/bash code
USER code
