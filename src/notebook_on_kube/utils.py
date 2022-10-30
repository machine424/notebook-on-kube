import logging
import subprocess
from typing import Final

logger = logging.getLogger(__name__)


KUBECTL_CMD: Final[str] = "kubectl"
HELM_CMD: Final[str] = "helm"

JUPYTER_NOTEBOOK_CHART_NAME: Final[str] = "jupyter-notebook"


class NOKException(Exception):
    pass


def run_command(*, command: list[str], **kw_args) -> str:
    """
    times out after 1h (security)
    """
    try:
        # TODO: Remove (only for debug)
        # print(f"RUNNING: {' '.join(command)}")
        return subprocess.check_output(
            command, timeout=3600, text=True, stderr=subprocess.PIPE, **kw_args
        )
    except subprocess.CalledProcessError as e:
        raise NOKException(e.stderr)
    except FileNotFoundError as e:
        raise NOKException(e)


def kubectl(*, body: list[str], kube_token: str) -> str:
    assert kube_token
    command = [KUBECTL_CMD, *body, "--token", kube_token]
    return run_command(command=command)


def helm(*, body: list[str], kube_token: str) -> str:
    assert kube_token
    command = [HELM_CMD, *body, "--kube-token", kube_token]
    return run_command(command=command)


def valid_name(*, string: str) -> str:
    _max_size = 40
    if not string:
        raise NOKException("Empty string cannot be used as Kubernetes label value.")
    if len(string) > _max_size or not string[0].isalnum() or not string[-1].isalnum():
        raise NOKException(
            f"{string=} has more than {_max_size} characters or does not begin and start with an alphanumeric character."
        )
    if any(not c.isalnum() and c not in ("-", "_", ".") for c in string):
        raise NOKException(
            f"{string=} cannot be used as Kubernetes label value, change it."
        )
    return string


def is_notebook_release(*, release_name: str, chart: str) -> bool:
    if chart.startswith(f"{JUPYTER_NOTEBOOK_CHART_NAME}-"):
        return True
    else:
        logger.info(
            f"The {release_name=} deploys {chart=} instead of {JUPYTER_NOTEBOOK_CHART_NAME}."
        )
        return False
