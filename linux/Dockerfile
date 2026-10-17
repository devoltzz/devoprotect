# The Linux build: Ubuntu 22.04, Python 3.14, GTK and WebKitGTK for the window.
FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -q \
 && apt-get install -y -q --no-install-recommends software-properties-common gpg-agent git \
 && add-apt-repository -y ppa:deadsnakes/ppa \
 && apt-get update -q \
 && apt-get install -y -q --no-install-recommends python3.14 python3.14-dev python3.14-venv build-essential \
    bison flex pkg-config libgirepository1.0-dev libcairo2-dev gir1.2-gtk-3.0 gir1.2-webkit2-4.1 ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN python3.14 -m venv /venv \
 && /venv/bin/pip install -q --upgrade pip \
 && /venv/bin/pip install -q "numpy>=1.24" "pillow>=10.0" "pywebview>=6.2" "pyinstaller>=6.0" "PyGObject<3.51" \
    pycairo ziglang==0.16.0 zopfli==0.4.3 lupa==2.8
ENV PATH=/venv/bin:$PATH
