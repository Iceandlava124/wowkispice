# PROJECT_WOWKISPICE Cloud Co-Simulation Runner
# Automated headless mixed-signal simulator container

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system dependencies & ngspice shared libraries
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    ngspice \
    libngspice0 \
    libngspice0-dev \
    git \
    curl \
    wget \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency requirements
COPY requirements.txt /app/
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy simulation engine, circuits, and tests
COPY bridge/ /app/bridge/
COPY circuits/ /app/circuits/
COPY firmware/ /app/firmware/
COPY tests/ /app/tests/

# Default entrypoint runs automated co-simulation verification suite
CMD ["python3", "tests/test_closed_loop_buck.py"]
