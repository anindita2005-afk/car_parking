FROM python:3.11-slim
WORKDIR /app
# Install system dependencies for OpenCV and EasyOCR
RUN apt-get update && apt-get install -y libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Keep container alive so user can exec into it and run scripts manually for testing
CMD ["tail", "-f", "/dev/null"]
