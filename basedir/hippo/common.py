from buildbot.process import results


def success(result, step):
    return result == results.SUCCESS
