import re
from pathlib import Path

from buildbot.plugins import steps, util
from buildbot.process import buildstep
from twisted.internet import defer

from hippo.common import success


class GenerateDebSteps(buildstep.ShellMixin, steps.BuildStep):
    def __init__(self, job_name, master_lock, **kwargs):
        kwargs = self.setupShellMixin(kwargs, prohibitArgs=['command'])
        super().__init__(**kwargs)
        self.job_name = job_name
        self.master_lock = master_lock

    def extract_packages(self, stdout: str):
        lines = stdout.splitlines()
        pkgs = []
        for line in lines:
            name, path, _ = line.split('\t')
            pkgs.append({'name': name, 'path': path})
        return pkgs

    @defer.inlineCallbacks
    def run(self):
        cmd = yield self.makeRemoteShellCommand(
            command=['colcon', 'list', '-t'], collectStdout=True
        )
        yield self.runCommand(cmd)
        result = cmd.results()
        if result != util.SUCCESS:
            return result
        pkgs = self.extract_packages(cmd.stdout)
        keys_to_skip = ','.join(pkg['name'] for pkg in pkgs)
        for pkg in pkgs:
            name = pkg['name']
            path = pkg['path']
            workdir = f'build/{path}'
            self.build.addStepsAfterCurrentStep(
                [
                    steps.ShellCommand(
                        name=f'{self.job_name}-rosdep-install',
                        command=[
                            'rosdep',
                            'install',
                            '--from-paths',
                            '.',
                            '-y',
                            f'--skip-keys={keys_to_skip}',
                        ],
                        workdir=workdir,
                        haltOnFailure=True,
                        hideStepIf=success,
                    ),
                    steps.ShellCommand(
                        name=f'{self.job_name}-bloom-generate',
                        command=[
                            'bloom-generate',
                            'rosdebian',
                        ],
                        haltOnFailure=True,
                        workdir=workdir,
                    ),
                    steps.ShellCommand(
                        name=f'{self.job_name}-generate-deb',
                        command=['fakeroot', 'debian/rules', 'binary'],
                        haltOnFailure=True,
                        workdir=workdir,
                    ),
                    steps.FileDownload(
                        mastersrc='scripts/install_deb',
                        workerdest='install_deb',
                        haltOnFailure=True,
                    ),
                    steps.ShellCommand(
                        name=f'{self.job_name}-install-deb',
                        command=['./install_deb', name, path],
                        haltOnFailure=True,
                    ),
                    steps.FileDownload(
                        mastersrc='scripts/move_deb_to_builddir',
                        workerdest='install_deb',
                        haltOnFailure=True,
                    ),
                    steps.ShellCommand(
                        name=f'{self.job_name}-move-deb',
                        command=['./move_deb_to_builddir', name, path],
                        haltOnFailure=True,
                    ),
                ]
            )

        def extract_deb_files(rc, stdout, stderr):
            files = [line.strip() for line in stdout.splitlines()]
            return {'debfiles': files}

        def extract_deb_names(rc, stdout, stderr):
            files = [line.strip() for line in stdout.splitlines()]
            return {'debnames': files}

        self.build.addBuildStepsAfterCurrent(
            [
                steps.SetPropertyFromCommand(
                    command=r"find . -name '*.deb'",
                    extract_fn=extract_deb_files,
                    haltOnFailure=True,
                ),
                steps.SetPropertyFromCommand(
                    command=r"find . -name '*.deb' -exec basename {} \;",
                    extract_fn=extract_deb_names,
                    haltOnFailure=True,
                ),
                steps.MultipleFileUpload(
                    workersrcs=util.Property('debfiles'),
                    masterdest='binarydebs/',
                    haltOnFailure=True,
                ),
            ]
        )

        # util.renderer
        def make_includedeb_command(props, i):
            debnames = props.getProperty('debnames')
            filename = debnames[i]
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

        for i in range(len(pkgs)):
            self.build.addBuildStepsAfterCurrent(
                [
                    steps.MasterShellCommand(
                        name=f'{self.job_name}-includedeb-{i}',
                        command=make_includedeb_command.withArgs(int(i)),
                        locks=[self.master_lock.access('exclusive')],
                    )
                ]
            )
        return cmd.results()
