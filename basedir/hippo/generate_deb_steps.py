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
        build_steps = []
        build_steps.extend(
            [
                steps.FileDownload(
                    name='download-install-script',
                    mastersrc='scripts/install_deb',
                    workerdest=util.Interpolate(
                        '%(prop:builddir)s/build/install_deb'
                    ),
                    mode=0o755,
                    haltOnFailure=True,
                    hideStepIf=success,
                ),
                steps.FileDownload(
                    name='download-move-deb-script',
                    mastersrc='scripts/move_deb_to_builddir',
                    workerdest=util.Interpolate(
                        '%(prop:builddir)s/build/move_deb_to_builddir'
                    ),
                    mode=0o755,
                    haltOnFailure=True,
                    hideStepIf=success,
                ),
            ]
        )
        build_steps.append(
            steps.SetProperty(
                property='generate_steps_for',
                value=pkgs,
            )
        )
        for pkg in pkgs:
            name = pkg['name']
            path = pkg['path']
            workdir = f'build/{path}'
            build_steps.extend(
                [
                    steps.ShellCommand(
                        name=f'rosdep-install-{name}',
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
                        name=f'bloom-generate-{name}',
                        command=[
                            'bloom-generate',
                            'rosdebian',
                        ],
                        haltOnFailure=True,
                        workdir=workdir,
                    ),
                    steps.ShellCommand(
                        name=f'generate-deb-{name}',
                        command=['fakeroot', 'debian/rules', 'binary'],
                        haltOnFailure=True,
                        workdir=workdir,
                    ),
                    steps.ShellCommand(
                        name=f'install-deb-{name}',
                        command=['./install_deb', name, path],
                        haltOnFailure=True,
                    ),
                    steps.ShellCommand(
                        name=f'move-deb-{name}',
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

        build_steps.extend(
            [
                steps.SetPropertyFromCommand(
                    name='set-debfiles',
                    command=r"find . -name '*.deb'",
                    extract_fn=extract_deb_files,
                    haltOnFailure=True,
                    hideStepIf=success,
                ),
                steps.SetPropertyFromCommand(
                    name='set-debnames',
                    command=r"find . -name '*.deb' -exec basename {} \;",
                    extract_fn=extract_deb_names,
                    haltOnFailure=True,
                    hideStepIf=success,
                ),
                steps.MultipleFileUpload(
                    name='upload-debfiles',
                    workersrcs=util.Property('debfiles'),
                    masterdest='binarydebs/',
                    haltOnFailure=True,
                ),
            ]
        )

        @util.renderer
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

        @util.renderer
        def interpolate_stepname(props, i):
            debnames = props.getProperty('debnames')
            filename = debnames[i]
            return f'includedeb-{filename}'

        for i in range(len(pkgs)):
            build_steps.extend(
                [
                    steps.MasterShellCommand(
                        name=interpolate_stepname.withArgs(int(i)),
                        command=make_includedeb_command.withArgs(int(i)),
                        locks=[self.master_lock.access('exclusive')],
                    )
                ]
            )
        self.build.addStepsAfterCurrentStep(build_steps)
        return cmd.results()
