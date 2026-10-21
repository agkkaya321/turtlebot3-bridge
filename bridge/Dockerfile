# syntax=docker/dockerfile:1
FROM rust:1.90-slim-bookworm AS rust

FROM ros:jazzy-ros-base AS build
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libclang-dev pkg-config file \
    ros-jazzy-turtlebot3-msgs \
    && rm -rf /var/lib/apt/lists/*
COPY --from=rust /usr/local/cargo /usr/local/cargo
COPY --from=rust /usr/local/rustup /usr/local/rustup
ENV PATH="/usr/local/cargo/bin:${PATH}" \
    RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    IDL_PACKAGE_FILTER="builtin_interfaces;std_msgs;std_srvs;geometry_msgs;nav_msgs;sensor_msgs;turtlebot3_msgs"
WORKDIR /build
COPY Cargo.* ./
COPY src ./src
COPY tools/smoke_test.py ./tools/smoke_test.py
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/build/target \
    source /opt/ros/jazzy/setup.bash && \
    if [ ! -f Cargo.lock ]; then cargo generate-lockfile; fi && \
    cargo test --release --locked && \
    cargo build --release --locked && \
    python3 tools/smoke_test.py target/release/turtlebot-speed-bridge && \
    mkdir -p /out/target/release && \
    cp target/release/turtlebot-speed-bridge /out/target/release/ && \
    cp Cargo.lock /out/ && \
    { rustc --version; uname -m; cat /etc/os-release; \
      dpkg-query -W 'ros-jazzy-*'; \
      file /out/target/release/turtlebot-speed-bridge; \
      ldd /out/target/release/turtlebot-speed-bridge; \
    } > /out/build-info.txt && \
    cd /out && sha256sum target/release/turtlebot-speed-bridge > SHA256SUMS
COPY run.sh robot.env.example /out/

FROM scratch AS artifact
COPY --from=build /out/ /
