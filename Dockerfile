# set arguments for the dockerfile
ARG PYTHON_VERSION=3.12

# use an official Python runtime as a parent image as interpreter
FROM python:${PYTHON_VERSION}-alpine
RUN apk update && apk add git

# create a mount point for the volume
VOLUME /app/data

# set the working directory in the container
WORKDIR /app

# run command if interpreter is installed on windows machine
COPY . .

# install dependencies
RUN apk add gcc python3-dev musl-dev linux-headers

# load virtual environment
RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# install packages
RUN python -m pip install --upgrade pip
RUN pip install -r requirements.txt


# run the tests
ENV GH_TOKEN ${GH_TOKEN}
ENV PYTHONPATH "${PYTHONPATH}:/usr/src/app"
ENV ENV_ROOT_DIRECTORY "/usr/src/app"
ENV ENV "TEST"

RUN python get_started.py
CMD ["pytest"]


