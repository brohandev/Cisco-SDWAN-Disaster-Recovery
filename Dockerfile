# Choose version of Python
FROM python:3.10

# Setup working directory so that the program can live somewhere
WORKDIR /code

# Copy requirements into the working directory so it gets cached by itself
COPY ./requirements.txt /code/requirements.txt

# Install the dependencies from the requirements file
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Copy the code into the working directory
COPY ./app /code/app

# Issue Python command to execute code, which will be running inside container now
CMD ["py", "app/controller.py"]
