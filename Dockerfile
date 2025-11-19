FROM python:3.13.9-bullseye
SHELL ["/bin/bash", "--login", "-c"]
ENV PIP_NO_CACHE_DIR off
ENV PIP_DISABLE_PIP_VERSION_CHECK on
ENV PYTHONUNBUFFERED 1
ENV PYTHONDONTWRITEBYTECODE 0
ENV COLUMNS 80
RUN apt-get update \
  && apt-get install -y --force-yes \
  curl nano python3-pip gettext chrpath libssl-dev libxft-dev \
  libfreetype6 libfreetype6-dev  libfontconfig1 libfontconfig1-dev \
  && rm -rf /var/lib/apt/lists/*

ENV NODE_VERSION=20.18.0
RUN mkdir /nvm
ENV NVM_DIR=/nvm
RUN apt install -y curl
RUN curl -o- https://raw.githubusercontent.com/creationix/nvm/v0.40.3/install.sh | bash
RUN . "$NVM_DIR/nvm.sh" && nvm install ${NODE_VERSION}
RUN . "$NVM_DIR/nvm.sh" && nvm use v${NODE_VERSION}
RUN . "$NVM_DIR/nvm.sh" && nvm alias default v${NODE_VERSION}
ENV PATH="${NVM_DIR}/versions/node/v${NODE_VERSION}/bin/:${PATH}"
RUN node --version
RUN npm --version
RUN npm install --global yarn@1.22.22

WORKDIR /code/
COPY requirements.txt /code/
RUN pip install wheel
RUN pip install -r requirements.txt
COPY . /code/
RUN useradd -ms /bin/bash code
USER code
