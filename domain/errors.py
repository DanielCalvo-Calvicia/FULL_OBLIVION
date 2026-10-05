"""The one error the whole tool raises for something the operator must fix."""


class DeployError(Exception):
    """A problem the operator must fix; the CLI prints it without a traceback."""
