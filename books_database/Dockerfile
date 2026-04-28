FROM python:3.11-slim

# Install grpcio and related tools
RUN pip install --no-cache-dir grpcio==1.60.0 grpcio-tools==1.60.0

# Create working directory
WORKDIR /app

# Copy the entire project context (for proto files and dependencies)
COPY . .

# Install requirements
RUN pip install --no-cache-dir -r books_database/requirements.txt

# Set Python to run in unbuffered mode for better logging
ENV PYTHONUNBUFFERED=TRUE

# Run the books database application
CMD ["python", "books_database/src/app.py"]
