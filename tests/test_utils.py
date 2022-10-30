import pytest

from notebook_on_kube.utils import (
    NOKException,
    helm,
    is_notebook_release,
    kubectl,
    run_command,
    valid_name,
)


@pytest.mark.parametrize(
    "command, kw_args, expected, exception, stderr_match",
    [
        (["noexist"], {}, None, NOKException, ".* No such file or directory: 'noexist'.*"),
        (["false"], {}, None, NOKException, ""),
        (["echo", "foo"], {}, "foo\n", None, None),
        (["cat", "doesnotexist"], {}, None, NOKException, ".*cat: doesnotexist: No such file or directory.*"),
    ],
)
def test_run_command(command, kw_args, expected, exception, stderr_match):
    if exception is None:
        assert run_command(command=command, **kw_args) == expected
    else:
        with pytest.raises(exception, match=stderr_match):
            run_command(command=command, **kw_args)


@pytest.mark.parametrize(
    "body, kube_token, kube_apiserver, tls_server_name, namespace, command, exception",
    [
        (
            ["get", "pods"],
            "mytoken",
            "https://foo.bar",
            "https://1.2.3.4",
            "nok-namespace",
            [
                "kubectl",
                "get",
                "pods",
                "--server",
                "https://foo.bar",
                "--certificate-authority",
                "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
                "--tls-server-name",
                "https://1.2.3.4",
                "--namespace",
                "nok-namespace",
                "--token",
                "mytoken",
            ],
            None,
        ),
        (
            ["list", "statefulsets"],
            "mytoken",
            None,
            None,
            "default",
            [
                "kubectl",
                "list",
                "statefulsets",
                "--namespace",
                "default",
                "--token",
                "mytoken",
            ],
            None,
        ),
        (
            ["get", "pods"],
            None,
            None,
            None,
            None,
            None,
            AssertionError,
        ),
    ],
)
def test_kubectl(mocker, body, kube_token, kube_apiserver, tls_server_name, namespace, command, exception):
    run_command_mock = mocker.patch("notebook_on_kube.utils.run_command")
    if exception is None:
        kubectl(
            body=body,
            kube_token=kube_token,
            kube_apiserver=kube_apiserver,
            tls_server_name=tls_server_name,
            namespace=namespace,
        )
        run_command_mock.assert_called_with(command=command)
    else:
        with pytest.raises(exception):
            kubectl(body=body, kube_token=kube_token)


@pytest.mark.parametrize(
    "body, kube_token, kube_apiserver, tls_server_name, namespace, command, exception",
    [
        (
            ["list", "^foo$"],
            "mytoken",
            "https://foo.bar",
            "https://1.2.3.4",
            "nok-namespace",
            [
                "helm",
                "list",
                "^foo$",
                "--kube-apiserver",
                "https://foo.bar",
                "--kube-ca-file",
                "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
                "--kube-tls-server-name",
                "https://1.2.3.4",
                "--namespace",
                "nok-namespace",
                "--kube-token",
                "mytoken",
            ],
            None,
        ),
        (
            ["delete", "bar"],
            "mytoken",
            None,
            None,
            "default",
            [
                "helm",
                "delete",
                "bar",
                "--namespace",
                "default",
                "--kube-token",
                "mytoken",
            ],
            None,
        ),
        (
            ["list"],
            None,
            None,
            None,
            None,
            None,
            AssertionError,
        ),
    ],
)
def test_helm(mocker, body, kube_token, kube_apiserver, tls_server_name, namespace, command, exception):
    run_command_mock = mocker.patch("notebook_on_kube.utils.run_command")
    if exception is None:
        helm(
            body=body,
            kube_token=kube_token,
            kube_apiserver=kube_apiserver,
            tls_server_name=tls_server_name,
            namespace=namespace,
        )
        run_command_mock.assert_called_with(command=command)
    else:
        with pytest.raises(exception):
            helm(body=body, kube_token=kube_token)


@pytest.mark.parametrize(
    "string, expected, exception",
    [
        ("", None, NOKException),
        ("a" * 31, None, NOKException),
        ("_foo", None, NOKException),
        ("foo-", None, NOKException),
        (".foo", None, NOKException),
        ("foo.-bar", None, NOKException),
        ("foo..bar", None, NOKException),
        ("fo@o", None, NOKException),
        ("a" * 30, "a" * 30, None),
        ("foo", "foo", None),
        ("foo-bar", "foo-bar", None),
        ("foo.bar", "foo.bar", None),
    ],
)
def test_valid_name(string, expected, exception):
    if exception is None:
        assert valid_name(string=string) == expected
    else:
        with pytest.raises(exception):
            valid_name(string=string)


@pytest.mark.parametrize(
    "release_name, chart, expected",
    [
        ("foo", "jupyter-notebook-bar", True),
        ("foo", "bar-bar", False),
        ("foo", "bar", False),
    ],
)
def test_is_notebook_release(release_name, chart, expected):
    assert is_notebook_release(release_name=release_name, chart=chart) == expected
