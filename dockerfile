# Use the official Python image from the Docker Hub
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install the dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire application into the container
COPY . .  # This copies everything from the root directory into /app

# Expose the port the app runs on
EXPOSE 8000

# Command to run the application using run.py
CMD ["python", "run.py"]