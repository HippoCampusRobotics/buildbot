ARG ROS_DISTRO=jazzy
FROM ros:${ROS_DISTRO}
ARG ROS_DISTRO
ARG USERNAME=buildbot

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get -qq install -y \
    dumb-init \
    python3-bloom \
    python3-rosdep \
    python3-pip \
    python3-dev \
    python3-venv \
    fakeroot \
    debhelper \
    dh-python \
# massivley reduces build time for builds having gazebo dependencies due to long dependency install process
    ros-${ROS_DISTRO}-ros-gz \ 
    && echo "deb [ signed-by=/etc/apt/keyrings/hippocampus-robotics.asc ] https://repositories.hippocampus-robotics.net/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" > /etc/apt/sources.list.d/hippocampus.list \
    && curl https://repositories.hippocampus-robotics.net/hippo-archive.key -o /etc/apt/keyrings/hippocampus-robotics.asc \
    && rm /etc/ros/rosdep/sources.list.d/20-default.list \
    && rosdep init \
    && echo "yaml https://raw.githubusercontent.com/HippoCampusRobotics/hippo_infrastructure/main/rosdep-${ROS_DISTRO}.yaml" > /etc/ros/rosdep/sources.list.d/50-hippocampus-packages.list \
    && apt-get autoremove -y \
    && apt-get clean -y \
    && rm -rf /var/lib/apt/lists/*

ENV TERM=xterm-256color
RUN python3 -m venv /buildbot_venv \
    && /buildbot_venv/bin/pip3 install 'buildbot[bundle]' \
    && mkdir /worker \
    && useradd -s /bin/bash -m ${USERNAME} \
    && usermod -g ${USERNAME} ${USERNAME}

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
