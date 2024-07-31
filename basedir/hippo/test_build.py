from buildbot.plugins import steps, util

from .common import success


def build_factory(job_name: str, repourl: str, pkg_name: str):
    factory = util.BuildFactory()
    factory.addSteps(
        [
            steps.SetPropertyFromCommand(
                command=['ls', '/opt/ros'],
                property='rosdistro',
                haltOnFailure=True,
            ),
            steps.ShellCommand(
                name=f'{job_name}-apt-update',
                command=['sudo', 'apt-get', 'update'],
                haltOnFailure=True,
                hideStepIf=success,
            ),
            steps.ShellCommand(
                name=f'{job_name}-rosdep-update',
                command=['rosdep', 'update'],
                haltOnFailure=True,
                hideStepIf=success,
            ),
            steps.Git(
                repourl=repourl,
                branch='main',
                mode='full',
                submodules=True,
                haltOnFailure=True,
            ),
            steps.ShellCommand(
                name=f'{job_name}-rosdep-install',
                command=[
                    'rosdep',
                    'install',
                    '--from-paths',
                    '.',
                    '-y',
                ],
                haltOnFailure=True,
                hideStepIf=success,
            ),
            steps.ShellCommand(
                name=f'{job_name}-colcon-build',
                command=util.Interpolate(
                    '. /opt/ros/%(prop:rosdistro)s/setup.sh '
                    '&& colcon build --symlink-install --cmake-args '
                    '--no-warn-unused-cli'
                ),
                haltOnFailure=True,
            ),
        ]
    )
    return factory
