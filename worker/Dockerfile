FROM hippo-release-builder:jazzy

ARG DEBIAN_FRONTEND=noninteractive
ARG USERNAME=buildbot

RUN apt-get update \
    && apt-get -y install -q \
    dumb-init \
    python3-dev \
    python3-pip \
    python3-venv \
    sudo \
    && python3 -m venv /buildbot_venv \
    && /buildbot_venv/bin/pip3 install 'buildbot[bundle]' \
    && mkdir /worker \
    && useradd -s /bin/bash -m ${USERNAME} \
    && usermod -g ${USERNAME} ${USERNAME} \
    && apt-get autoremove -y \
    && apt-get clean -y \
    && rm -rf /var/lib/apt/lists/*

RUN echo $USERNAME ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/$USERNAME \
    && chmod 0440 /etc/sudoers.d/$USERNAME


COPY ./buildbot.tac /worker/buildbot.tac
RUN chown -R ${USERNAME}:${USERNAME} /worker \
    && chown -R ${USERNAME}:${USERNAME} /buildbot_venv \
    && chown -R $USERNAME:$USERNAME /home/$USERNAME

USER ${USERNAME}
WORKDIR /worker

ENTRYPOINT ["/usr/bin/dumb-init", "--"]
CMD ["/buildbot_venv/bin/twistd", "--pidfile=", "-ny", "buildbot.tac"]


