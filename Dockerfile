FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV WOSP_DOCKER=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    wget \
    curl \
    ca-certificates \
    python3 \
    python3-pip \
    python3-venv \
    libngspice0-dev \
    libusb-1.0-0-dev \
    pkg-config \
    bison \
    flex \
    texinfo \
    libglib2.0-dev \
    libpixman-1-dev \
    ninja-build \
    libfdt-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy repo
COPY . /app

# Create venv and install dependencies
RUN python3 -m venv .venv && \
    .venv/bin/pip install --upgrade pip && \
    .venv/bin/pip install -r requirements.txt

# Create necessary directories
RUN mkdir -p third_party/qemu logs

# Try to fetch prebuilt QEMU or run setup
RUN .venv/bin/python tools/fetch_qemu.py || true

# Run environment doctor
RUN .venv/bin/python tools/doctor.py || true

# Write .env.local
RUN .venv/bin/python -c "from bridge.toolchain_resolver import ToolchainResolver; r=ToolchainResolver(); print(r.write_env_local())" || true

# Default command - run core unit tests
CMD [".venv/bin/python", "-m", "pytest", "tests/test_adversarial_stress.py", "tests/test_load_step_injection.py", "tests/test_binary_runner.py", "tests/test_qemu_monitor_unit.py", "tests/test_adc_conversion.py", "tests/test_control_law_unit.py", "-v"]
