import logging
import os
import re
import subprocess
from typing import Final

logger = logging.getLogger(__name__)

# Sometimes we should pass through a proxy for OIDC e.g. (passed as --server to kubectl and --kube-apiserver to helm)
# Should be a name for which the Certificate was signed.
KUBE_API_SERVER: str | None = os.environ.get("NOK_KUBE_APISERVER")
KUBE_TLS_SERVER_NAME: str | None = os.environ.get("NOK_KUBE_TLS_SERVER_NAME")
# inside a container, kubectl forgets about the CA when using --token
IN_CLUSTER_CRT: Final[str] = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"

KUBE_CLUSTER_NAME: str | None = os.environ.get("NOK_KUBE_CLUSTER_NAME")
NOTEBOOKS_NAMESPACE: Final[str] = os.environ.get("NOK_NAMESPACE", "default")

KUBECTL_CMD: Final[str] = "kubectl"
HELM_CMD: Final[str] = "helm"

JUPYTER_NOTEBOOK_CHART_NAME: Final[str] = "jupyter-notebook"


class NOKException(Exception):
    pass


def run_command(*, command: list[str], **kw_args) -> str:
    """
    times out after 10 min as we're not supposed to wait.
    """
    try:
        return subprocess.check_output(command, timeout=600, text=True, stderr=subprocess.PIPE, **kw_args)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        raise NOKException(e.stderr)
    except FileNotFoundError as e:
        raise NOKException(e)


def kubectl(
    *,
    body: list[str],
    kube_token: str,
    kube_apiserver: str | None = KUBE_API_SERVER,
    tls_server_name: str | None = KUBE_TLS_SERVER_NAME,
    namespace: str = NOTEBOOKS_NAMESPACE,
) -> str:
    assert kube_token
    if kube_apiserver is not None:
        body = [*body, "--server", kube_apiserver, "--certificate-authority", IN_CLUSTER_CRT]
    if tls_server_name is not None:
        body = [*body, "--tls-server-name", tls_server_name]
    command = [KUBECTL_CMD, *body, "--namespace", namespace, "--token", kube_token]
    return run_command(command=command)


def helm(
    *,
    body: list[str],
    kube_token: str,
    kube_apiserver: str | None = KUBE_API_SERVER,
    tls_server_name: str | None = KUBE_TLS_SERVER_NAME,
    namespace: str = NOTEBOOKS_NAMESPACE,
) -> str:
    assert kube_token
    if kube_apiserver is not None:
        body = [*body, "--kube-apiserver", kube_apiserver, "--kube-ca-file", IN_CLUSTER_CRT]
    if tls_server_name is not None:
        body = [*body, "--kube-tls-server-name", tls_server_name]
    command = [HELM_CMD, *body, "--namespace", namespace, "--kube-token", kube_token]
    return run_command(command=command)


def valid_name(*, string: str, max_size: int = 30) -> str:
    regex = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$")
    if len(string) > max_size:
        raise NOKException(f"{string=} has more than {max_size} characters.")
    if not regex.match(string):
        raise NOKException(
            f"{string=} must consist of lower case alphanumeric characters, '-' or '.',"
            f" must start and end with an alphanumeric character and match the regex {regex.pattern}."
        )
    return string


def is_notebook_release(*, release_name: str, chart: str) -> bool:
    if chart.startswith(f"{JUPYTER_NOTEBOOK_CHART_NAME}-"):
        return True
    else:
        logger.warning(f"The {release_name=} deploys {chart=} instead of {JUPYTER_NOTEBOOK_CHART_NAME}.")
        return False


def get_notebook_pod_name(*, notebook_name: str) -> str:
    """
    Assumes there is only one Pod
    """
    return f"{notebook_name}-0"
