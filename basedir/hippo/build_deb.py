import re
from pathlib import Path

from buildbot.plugins import changes, schedulers, steps, util

from . import test_build
from .common import success


def create_deb_factory(
    job_name: str, repourl: str, pkg_name: str, triggers: list[str], arch: str
):
    factory = util.BuildFactory()
    lock = util.MasterLock('reprepro')

    @util.renderer
    def make_includedeb_command(props):
        filename = props.getProperty('debfile')
        basename = Path(filename).stem
        deb_pkg, ver_and_code, arch = basename.split('_')
        distro = deb_pkg.split('-')[1]  # noqa: F841
        m = re.search(r'[a-zA-Z]+', ver_and_code)
        code = m.group(0)
        command = [
            './scripts/reprepro-includedeb',
            deb_pkg,
            filename,
            code,
            arch,
        ]
        return command

    def uname_to_arch(rc, stdout, stderr):
        if 'x86_64' in stdout:
            return {'arch': 'amd64'}
        if 'aarch64' in stdout:
            return {'arch': 'arm64'}
        else:
            return {'arch': 'unknown'}

    # checkout
    build_steps = [
        steps.ShellCommand(
            name=f'{job_name}-apt-update',
            command=[
                'sudo',
                'apt-get',
                'update',
            ],
            haltOnFailure=True,
            hideStepIf=success,
            locks=[lock.access('exclusive')],
        ),
        steps.ShellCommand(
            name=f'{job_name}-rosdep-update',
            command=['rosdep', 'update'],
            haltOnFailure=True,
            hideStepIf=success,
            locks=[lock.access('exclusive')],
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
            name=f'{job_name}-bloom-generate',
            command=[
                'bloom-generate',
                'rosdebian',
            ],
            haltOnFailure=True,
        ),
        steps.ShellCommand(
            name=f'{job_name}-generate-deb',
            command=['fakeroot', 'debian/rules', 'binary'],
            haltOnFailure=True,
        ),
        steps.SetPropertyFromCommand(
            command=r"find .. -name '*.deb' -exec basename {} \;",
            property='debfile',
            haltOnFailure=True,
        ),
        steps.SetPropertyFromCommand(
            command="find .. -name '*.deb'",
            property='debpath',
            haltOnFailure=True,
            hideStepIf=success,
        ),
        steps.FileUpload(
            name=f'{job_name}-upload-deb',
            workersrc=util.Interpolate('%(prop:debpath)s'),
            masterdest=util.Interpolate('binarydebs/%(prop:debfile)s'),
            haltOnFailure=True,
        ),
        steps.MasterShellCommand(
            name=f'{job_name}-includedeb',
            command=make_includedeb_command,
            haltOnFailure=True,
            locks=[lock.access('exclusive')],
        ),
    ]
    for build_step in build_steps:
        factory.addStep(build_step)

    def should_trigger(step):
        return step.build.hasProperty(
            'is_full_build'
        ) and step.build.getProperty('is_full_build')

    # do not trigger anything for now, since this massively increases
    # the amount of useless rebuilds

    if triggers:
        factory.addStep(
            steps.Trigger(
                schedulerNames=[
                    f'{x.replace("_", "-")}-triggerable-{arch}'
                    for x in triggers
                ],
                set_properties={'is_triggered': True, 'is_full_build': True},
                doStepIf=should_trigger,
                waitForFinish=False,
            )
        )
    return factory


def deb_jobs(c, repos: list[str], worker: dict[str, list[str]]):
    builders = []

    for i_repo, repo in enumerate(repos):
        repo_name = repo['name'].replace('_', '-')
        main_branch_scheduler_name = f'{repo_name}-main-branch-scheduler'
        dependent_deb_scheduler_name = f'{repo_name}-dependent-scheduler'
        colcon_builders = []
        deb_builders = []
        for arch in worker:
            triggerable_name = f'{repo_name}-triggerable-{arch}'
            deb_builder_name = f'{repo_name}-deb-{arch}'
            colcon_builder_name = f'{repo_name}-colcon-{arch}'
            colcon_builders.append(colcon_builder_name)
            deb_builders.append(deb_builder_name)
            repourl = (
                f'https://github.com/HippoCampusRobotics/{repo["name"]}.git'
            )
            try:
                next_repo = [repos[i_repo + 1]['name']]
            except IndexError:
                next_repo = None
            except KeyError:
                next_repo = None
            deb_factory = create_deb_factory(
                repo['name'], repourl, repo['name'], next_repo, arch
            )
            colcon_factory = test_build.build_factory(
                repo['name'], repourl, repo['name']
            )

            c['builders'].append(
                util.BuilderConfig(
                    name=deb_builder_name,
                    workernames=[w.name for w in worker[arch]],
                    factory=deb_factory,
                )
            )
            c['builders'].append(
                util.BuilderConfig(
                    name=colcon_builder_name,
                    workernames=[w.name for w in worker[arch]],
                    factory=colcon_factory,
                )
            )
            # create the triggerables for arm/amd for each repo name
            c['schedulers'].append(
                schedulers.Triggerable(
                    name=triggerable_name, builderNames=[deb_builder_name]
                )
            )
            builders.append(deb_builder_name)
            builders.append(colcon_builder_name)

        main_branch_scheduler = schedulers.SingleBranchScheduler(
            name=main_branch_scheduler_name,
            treeStableTimer=10,
            builderNames=colcon_builders,
            change_filter=util.ChangeFilter(
                repository=repourl.removesuffix('.git'), branch='main'
            ),
        )
        c['schedulers'].append(main_branch_scheduler)
        c['schedulers'].append(
            schedulers.Dependent(
                name=dependent_deb_scheduler_name,
                builderNames=deb_builders,
                upstream=main_branch_scheduler,
            )
        )

    c['schedulers'].append(
        schedulers.ForceScheduler(name='force', builderNames=builders)
    )
    c['schedulers'].append(
        schedulers.Nightly(
            name='nightly-deb-amd64',
            properties={'is_full_build': True},
            hour=22,
            minute=3,
            builderNames=[name for name in builders if 'deb-amd64' in name],
            change_filter=util.ChangeFilter(branch='main'),
        ),
    )
    c['schedulers'].append(
        schedulers.Nightly(
            name='nightly-deb-arm64',
            properties={'is_full_build': True},
            hour=1,
            minute=21,
            builderNames=[name for name in builders if 'deb-arm64' in name],
            change_filter=util.ChangeFilter(branch='main'),
        ),
    )
