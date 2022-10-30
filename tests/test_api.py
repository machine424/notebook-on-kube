from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from notebook_on_kube.main import (
    HTTPException,
    NOKException,
    app,
    complete_notebook_name_from_form,
    existing_notebook_name,
    username_from_email,
    valid_kube_token,
    validate_kube_token,
    yaml,
)

FAKE_USERNAME = "my-username"
# FAKE_USERNAME's
FAKE_OIDC_TOKEN = (
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsImtpZCI6IndpWjBQa3pVY3ExdUkzaE94Z3NRM2FZaV90ekxnTkcxOE9HQz"
    "EzbHNGaWsifQ.eyJpc3MiOiJodHRwczovL2Zvby5iYXIiLCJzdWIiOiIxIiwiYXVkIjoiZm9vIiwiZXhwIjoxLCJpYXQiOj"
    "EsImF1dGhfdGltZSI6MSwic3ViX2xlZ2FjeSI6ImZvbyIsImVtYWlsIjoibXktdXNlcm5hbWVAZm9vLmJhciIsImVtYWlsX"
    "3ZlcmlmaWVkIjp0cnVlfQ.eB6-HFkD21FrzXgYJDoi_2YVtvycgs5mrVDedOJX98MWtJe2bsr5nyNBEKraNP1cXGeReW4dy"
    "7QwNVJ_mBUe41SrS8mfeCnYtCbkMAOxUaQRhHu8R88YOdBIpITpiRBtYthEnWddB2wPegj-RfYigRMASxssg4kL4_9srCmc"
    "KZ6UCcaWFLS64ZReU9SHPvWlROZTGkGyTYM_XTZvNu9_M-WY8ISTdglt7Kv6R_EMb0U41TKHIdTTz4GWXMvXmoZjs9kEf4J"
    "n0rbW0MTykCAxdFSyHf-tCaKRoRiIn2T6iltq8HzcWloR5vWGsdd_rZ27SevB7KEqW61NIww89KJPFA"
)
FAKE_NOTEBOOK = "my-notebook"

client = TestClient(app)


@pytest.fixture()
def validate_kube_token_mock(mocker):
    mocker.patch("notebook_on_kube.main.validate_kube_token")


@pytest.mark.parametrize(
    "exception",
    [None, NOKException],
)
def test_validate_kube_token(mocker, exception):
    if exception is None:
        run_command = mocker.patch("notebook_on_kube.utils.run_command")
        validate_kube_token(kube_token=FAKE_OIDC_TOKEN)
    else:
        run_command = mocker.patch("notebook_on_kube.utils.run_command", side_effect=exception)
        with pytest.raises(HTTPException) as exc_info:
            validate_kube_token(kube_token=FAKE_OIDC_TOKEN)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail.startswith("The Kubernetes token in not valid:")
    run_command.assert_called_once_with(
        command=["kubectl", "auth", "can-i", "list", "secret", "--namespace", "default", "--token", FAKE_OIDC_TOKEN]
    )


@pytest.mark.parametrize(
    "kube_token, exception",
    [
        (
            FAKE_OIDC_TOKEN,
            None,
        ),
        ("", HTTPException),
        (None, HTTPException),
    ],
)
def test_valid_kube_token(mocker, kube_token, exception):
    mocker.patch("notebook_on_kube.utils.run_command")
    if exception is None:
        assert valid_kube_token(kube_token=kube_token) == kube_token
    else:
        with pytest.raises(exception) as exc_info:
            valid_kube_token(kube_token=kube_token)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Where is my kube_token Cookie? Please log in."


@pytest.mark.parametrize(
    "helm_list_output, exception, status_code, detail_prefix",
    [
        ('[{"foo": "bar"}]', None, 400, None),
        ("{}", HTTPException, 400, f"The Notebook notebook_name='{FAKE_NOTEBOOK}' does not exist."),
    ],
)
def test_existing_notebook_name(mocker, helm_list_output, exception, status_code, detail_prefix):
    helm = mocker.patch("notebook_on_kube.main.helm", return_value=helm_list_output)
    if exception is None:
        assert existing_notebook_name(notebook_name=FAKE_NOTEBOOK, kube_token=FAKE_OIDC_TOKEN) == FAKE_NOTEBOOK
        helm.assert_called_once_with(
            body=["list", "--filter", f"^{FAKE_NOTEBOOK}$", "--all", "--output", "json"], kube_token=FAKE_OIDC_TOKEN
        )
    else:
        with pytest.raises(HTTPException) as exc_info:
            existing_notebook_name(notebook_name=FAKE_NOTEBOOK, kube_token=FAKE_OIDC_TOKEN)
        assert exc_info.value.status_code == status_code
        assert exc_info.value.detail.startswith(detail_prefix)


@pytest.mark.parametrize(
    "kube_token, expected, exception",
    [
        (
            FAKE_OIDC_TOKEN,
            FAKE_USERNAME,
            None,
        ),
        ("invalid", None, HTTPException),
    ],
)
def test_username_from_email(kube_token, expected, exception):
    if exception is None:
        assert username_from_email(kube_token=kube_token) == expected
    else:
        with pytest.raises(exception) as exc_info:
            username_from_email(kube_token=kube_token)
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail.startswith("Could not get a valid username from the Kubernetes token:")


@pytest.mark.parametrize(
    "notebook_name, username, complete_notebook_name",
    [
        ("foo", "bar", "nok-bar-foo"),
        (FAKE_NOTEBOOK, FAKE_USERNAME, f"nok-{FAKE_USERNAME}-{FAKE_NOTEBOOK}"),
    ],
)
def test_complete_notebook_name_from_form(mocker, notebook_name, username, complete_notebook_name):
    mocker.patch("notebook_on_kube.main.valid_name")
    assert complete_notebook_name_from_form(notebook_name=notebook_name, username=username) == complete_notebook_name


def test_healthz():
    response = client.get("api/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "Seems healthy"


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.template.name == "index.html"
    assert response.context["kube_cluster_name"] is None


def test_login(validate_kube_token_mock):
    response = client.post("api/login/", data={"kube_token": FAKE_OIDC_TOKEN}, allow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/api/notebooks/"
    # We do not send the cookie when connecting to Notebooks (non /api)
    assert response.cookies.get_dict(path="/api")["kube_token"] == FAKE_OIDC_TOKEN


def test_notebooks(mocker, validate_kube_token_mock):
    helm = mocker.patch("notebook_on_kube.main.helm", return_value="{}")
    response = client.get("api/notebooks/", cookies={"kube_token": FAKE_OIDC_TOKEN})
    helm.assert_called_once_with(
        body=["list", "--filter", f"^nok-{FAKE_USERNAME}-.+$", "--all", "--output", "json"], kube_token=FAKE_OIDC_TOKEN
    )
    assert response.status_code == 200
    assert response.template.name == "notebooks.html"
    assert response.context["username"] == FAKE_USERNAME
    assert response.context["notebook_status"] == {
        "kube_cluster_name": None,
        "not_running": "Not Running",
        "notebooks": [],
        "notebooks_namespace": "default",
    }


@pytest.mark.parametrize(
    "existing, helm_list_output, status_code", [(False, "{}", 400), (True, '[{"foo": "bar"}]', 303)]
)
def test_delete_notebook(mocker, validate_kube_token_mock, existing, helm_list_output, status_code):
    helm = mocker.patch("notebook_on_kube.main.helm", return_value=helm_list_output)
    helm_list_call = mocker.call(
        body=["list", "--filter", f"^{FAKE_NOTEBOOK}$", "--all", "--output", "json"], kube_token=FAKE_OIDC_TOKEN
    )
    response = client.post(
        f"api/delete_notebook/{FAKE_NOTEBOOK}", cookies={"kube_token": FAKE_OIDC_TOKEN}, allow_redirects=False
    )
    assert response.status_code == status_code
    if existing:
        assert response.headers["location"] == "/api/notebooks/"
        assert helm.call_count == 2
        helm.assert_has_calls([helm_list_call, mocker.call(body=["delete", FAKE_NOTEBOOK], kube_token=FAKE_OIDC_TOKEN)])
    else:
        assert response.json()["detail"] == f"The Notebook notebook_name='{FAKE_NOTEBOOK}' does not exist."
        assert helm.call_count == 1
        helm.assert_has_calls([helm_list_call])


@pytest.mark.parametrize("event", ["foo bar", "", "foo\nbar"])
def test_notebook_events(mocker, validate_kube_token_mock, event):
    mocker.patch("notebook_on_kube.main.notebook_exists", return_value=True)
    kubectl = mocker.patch("notebook_on_kube.main.kubectl", return_value=event)
    response = client.get(f"api/notebook_events/{FAKE_NOTEBOOK}", cookies={"kube_token": FAKE_OIDC_TOKEN})
    assert response.status_code == 200
    assert (
        response.text
        == f"* Events involving {FAKE_NOTEBOOK}:\n\n{event}\n* Events involving {FAKE_NOTEBOOK}-0:\n\n{event}\n* Events involving data-{FAKE_NOTEBOOK}-0:\n\n{event}"  # noqa
    )
    assert kubectl.call_count == 3
    kubectl.assert_has_calls(
        [
            mocker.call(
                body=["get", "event", "--field-selector", f"involvedObject.name={FAKE_NOTEBOOK}"],
                kube_token=FAKE_OIDC_TOKEN,
            ),
            mocker.call(
                body=["get", "event", "--field-selector", f"involvedObject.name={FAKE_NOTEBOOK}-0"],
                kube_token=FAKE_OIDC_TOKEN,
            ),
            mocker.call(
                body=["get", "event", "--field-selector", f"involvedObject.name=data-{FAKE_NOTEBOOK}-0"],
                kube_token=FAKE_OIDC_TOKEN,
            ),
        ]
    )


@pytest.mark.parametrize("scale", ["0", "1"])
def test_scale_notebook(mocker, validate_kube_token_mock, scale):
    mocker.patch("notebook_on_kube.main.notebook_exists", return_value=True)
    kubectl = mocker.patch("notebook_on_kube.main.kubectl")
    response = client.get(
        f"api/scale_notebook/{FAKE_NOTEBOOK}?scale={scale}",
        cookies={"kube_token": FAKE_OIDC_TOKEN},
        allow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/api/notebooks/"
    kubectl.assert_called_once_with(
        body=[
            "scale",
            "statefulset",
            "--selector",
            f"app.kubernetes.io/instance={FAKE_NOTEBOOK}",
            "--replicas",
            scale,
        ],
        kube_token=FAKE_OIDC_TOKEN,
    )


def test_new_notebook(validate_kube_token_mock):
    response = client.get(
        "api/new_notebook/",
        cookies={"kube_token": FAKE_OIDC_TOKEN},
    )
    assert response.status_code == 200
    assert response.template.name == "new_notebook.html"
    assert response.context["username"] == FAKE_USERNAME
    # If values.yaml changes, then copy/past it here ;)
    assert response.context["notebook_config"] == {
        "helm_values": 'image:\n  repository: jupyter/datascience-notebook\n  pullPolicy: IfNotPresent\n  tag: "notebook-6.5.1"\n\npodAnnotations: {}\n\nargs: []\n\nresources:\n  requests:\n    cpu: "1"\n    memory: "1Gi"\n  limits:\n    cpu: "1"\n    memory: "1Gi"\n\nextraEnv: {}\nextraSecretEnv: {}\n\npersistence:\n  enabled: true\n  # size: ""\n  # mountPath: ""\n\nnodeSelector: {}\n\ntolerations: []\n\naffinity: {}\n',  # noqa
        "notebooks_namespace": "default",
    }


@pytest.mark.parametrize(
    "existing, helm_values, status_code",
    [(False, "image:\n  repository: foo\n", 303), (False, "", 303), (False, "\n", 303), (True, None, 400)],
)
def test_create_notebook(mocker, validate_kube_token_mock, existing, helm_values, status_code):
    mocker.patch("notebook_on_kube.main.notebook_exists", return_value=existing)
    helm = mocker.patch("notebook_on_kube.main.helm")

    yaml_load = mocker.spy(yaml, "load")
    yaml_dump = mocker.spy(yaml, "dump")

    response = client.post(
        "api/create_notebook/",
        cookies={"kube_token": FAKE_OIDC_TOKEN},
        data={"notebook_name": FAKE_NOTEBOOK, "helm_values": helm_values},
        allow_redirects=False,
    )
    assert response.status_code == status_code
    if not existing:
        assert response.headers["location"] == "/api/notebooks/"
        # helm_values content was retrieved
        yaml_load.assert_called_once_with(helm_values)
        assert yaml_dump.call_count == 1
        assert yaml_dump.call_args.kwargs["data"] == yaml_load.spy_return
        values_file = yaml_dump.call_args.kwargs["stream"].name
        # file was deleted
        assert not Path(values_file).is_file()
        helm.assert_called_once_with(
            body=[
                "install",
                f"nok-{FAKE_USERNAME}-{FAKE_NOTEBOOK}",
                "chart/jupyter-notebook",
                "--values",
                values_file,
            ],
            kube_token=FAKE_OIDC_TOKEN,
        )
    else:
        assert (
            response.json()["detail"]
            == f"The Notebook notebook_name='nok-{FAKE_USERNAME}-{FAKE_NOTEBOOK}' already exists."
        )
        assert helm.call_count == 0
