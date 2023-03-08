import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import IO, Any, ClassVar, Final, Literal

import jwt
from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Request,
    status,
)
from fastapi.datastructures import FormData
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Extra
from ruamel.yaml import YAML
from ruamel.yaml.compat import StringIO
from ruamel.yaml.error import YAMLError

from notebook_on_kube.utils import (
    KUBE_CLUSTER_NAME,
    NOTEBOOKS_NAMESPACE,
    NOKException,
    get_notebook_pod_name,
    helm,
    is_notebook_release,
    kubectl,
    valid_name,
)

logger = logging.getLogger(__name__)

yaml = YAML()
yaml.preserve_quotes = True  # type: ignore

KUBE_TOKEN_COOKIE_NAME: Final[str] = "kube_token"
JUPYTER_NOTEBOOK_CHART_PATH: Final[str] = "chart/jupyter-notebook"


app = FastAPI()
templates = Jinja2Templates(directory="templates")
router = APIRouter(prefix="/api")


def validate_kube_token(*, kube_token: str) -> None:
    """
    Check the token is valid (signature) as we retrieve the username from it.
    """
    try:
        kubectl(body=["auth", "can-i", "list", "secret"], kube_token=kube_token)
    except NOKException as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=f"The Kubernetes token in not valid: {exc}")


def valid_kube_token(kube_token: str | None = Cookie(default=None)) -> str:
    if kube_token:
        validate_kube_token(kube_token=kube_token)
        return kube_token
    else:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=f"Where is my {KUBE_TOKEN_COOKIE_NAME} Cookie? Please log in.",
        )


def username_from_email(*, kube_token: str = Depends(valid_kube_token)) -> str:
    """
    Suppose "email" is present and the local part of the email is unique and valid
    """
    try:
        # the Kube API takes care of the signature verification
        content = jwt.decode(kube_token, options={"verify_signature": False})
        local_part = content["email"].split("@", maxsplit=1)[0]
        return valid_name(string=local_part, max_size=20)
    except (jwt.exceptions.InvalidTokenError, KeyError, IndexError, NOKException) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not get a valid username from the Kubernetes token: {exc}",
        )


def complete_notebook_name_from_form(
    *, notebook_name: str = Form(), username: str = Depends(username_from_email)
) -> str:
    complete_name = f"nok-{username}-{notebook_name}"
    try:
        valid_name(string=complete_name, max_size=40)
        return complete_name
    except NOKException as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"The Notebook {complete_name=} is not valid: {exc}",
        )


def notebook_exists(*, notebook_name: str, kube_token: str) -> bool | None:
    body: list[str] = [
        "list",
        "--filter",
        f"^{notebook_name}$",
        "--all",
        "--output",
        "json",
    ]
    try:
        return len(json.loads(helm(body=body, kube_token=kube_token))) == 1
    except NOKException as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not check if the Notebook {notebook_name=} exists: {exc}",
        )


def existing_notebook_name(*, notebook_name: str, kube_token: str = Depends(valid_kube_token)) -> str:
    if not notebook_exists(notebook_name=notebook_name, kube_token=kube_token):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"The Notebook {notebook_name=} does not exist.",
        )
    return notebook_name


def get_notebook_pod(*, release_name: str, kube_token: str) -> dict | None:
    """
    Assumes there is only one
    """
    kubectl_body: list[str] = [
        "get",
        "pod",
        "--selector",
        f"app.kubernetes.io/instance={release_name}",
        "--output",
        "json",
    ]
    try:
        return json.loads(kubectl(body=kubectl_body, kube_token=kube_token))["items"][0]
    except IndexError:
        return None


def get_notebook_events(*, notebook_name: str, kube_token: str) -> str:
    pod_name = get_notebook_pod_name(notebook_name=notebook_name)
    objects = (
        notebook_name,
        pod_name,
        f"data-{pod_name}",
    )
    events: list[str] = []
    for obj in objects:
        events.append(f"* Events involving {obj}:\n")
        kubectl_body: list[str] = [
            "get",
            "event",
            "--field-selector",
            f"involvedObject.name={obj}",
        ]
        try:
            events.append(kubectl(body=kubectl_body, kube_token=kube_token))
        except NOKException as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Could not get events of {notebook_name=}: {exc}",
            )
    return "\n".join(events)


def get_notebook_statefulset(*, release_name: str, kube_token: str) -> dict | None:
    """
    Assumes there is only one
    """
    kubectl_body: list[str] = [
        "get",
        "statefulset",
        "--selector",
        f"app.kubernetes.io/instance={release_name}",
        "--output",
        "json",
    ]
    try:
        return json.loads(kubectl(body=kubectl_body, kube_token=kube_token))["items"][0]
    except IndexError:
        return None


def scale_notebook_statefulset(*, notebook_name: str, kube_token: str, replicas: int) -> None:
    kubectl_body: list[str] = [
        "scale",
        "statefulset",
        "--selector",
        f"app.kubernetes.io/instance={notebook_name}",
        "--replicas",
        str(replicas),
    ]
    kubectl(body=kubectl_body, kube_token=kube_token)


def list_releases(*, username: str, kube_token: str):
    helm_body: list[str] = [
        "list",
        "--filter",
        f"^nok-{username}-.+$",
        "--all",
        "--output",
        "json",
    ]
    try:
        return json.loads(helm(body=helm_body, kube_token=kube_token))
    except NOKException as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Could not list Notebooks: {exc}"
        )


def deploy_notebook(*, notebook_name: str, values_file: IO | None, kube_token: str) -> None:
    """
    closes values_file at the end
    """
    body: list[str] = ["install", notebook_name, JUPYTER_NOTEBOOK_CHART_PATH]
    if values_file is not None:
        body = [*body, "--values", values_file.name]
    try:
        helm(body=body, kube_token=kube_token)
    except NOKException as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not deploy the Notebook {notebook_name=}: {exc}",
        )
    finally:
        if values_file is not None:
            values_file.close()


async def get_form_data(*, request: Request) -> FormData:
    return await request.form()


class NotebookConfig:
    @classmethod
    def template_context(cls) -> Any:
        helm_values = StringIO()
        # extra empty line added at the end.
        yaml.dump(stream=helm_values, data=yaml.load(Path(f"{JUPYTER_NOTEBOOK_CHART_PATH}/values.yaml")))
        return {"notebooks_namespace": NOTEBOOKS_NAMESPACE, "helm_values": helm_values.getvalue()}

    @classmethod
    def form_data_to_values_file(cls, *, form_data: FormData) -> IO | None:
        """
        This should take care of the extra config validation.
        """
        helm_values_key = "helm_values"
        # We keep empty value
        if helm_values_key not in form_data:
            return None
        values_file = tempfile.NamedTemporaryFile()
        try:
            # We do extra validation for now (maybe have a schema validation in the front and here)
            yaml.dump(stream=values_file, data=yaml.load(form_data[helm_values_key]))
            return values_file
        except YAMLError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Provided {helm_values_key} cannot be parsed: {exc}",
            )


class NotebookStatus:
    class Notebook(BaseModel, extra=Extra.forbid):
        missing_statefulset: ClassVar[str] = "StatefulSet Missing"
        not_running: ClassVar[str] = "Not Running"
        error: ClassVar[str] = "Error"

        name: str
        image: str = error
        status: str = error
        start_time: datetime | str = error

    @classmethod
    def fetch_notebook_info(cls, *, release_name: str, kube_token: str) -> dict[str, str]:
        statefulset = get_notebook_statefulset(release_name=release_name, kube_token=kube_token)
        pod = get_notebook_pod(release_name=release_name, kube_token=kube_token)
        info: dict[str, str] = {}

        if statefulset:
            info |= {
                "image": statefulset["spec"]["template"]["spec"]["containers"][0]["image"],
                "status": cls.Notebook.not_running,
                "start_time": cls.Notebook.not_running,
            }
        else:
            info |= {
                "status": cls.Notebook.missing_statefulset,
                "image": cls.Notebook.missing_statefulset,
                "start_time": cls.Notebook.missing_statefulset,
            }
        if pod:
            info |= {
                "image": pod["spec"]["containers"][0]["image"],
                "status": pod["status"]["phase"],
            }
            start_time = pod["status"].get("startTime")
            if start_time is not None:
                info["start_time"] = start_time
        return info

    @classmethod
    def template_context(cls, *, username: str, kube_token: str) -> Any:
        """
        Supposes every release from JUPYTER_NOTEBOOK_CHART_NAME is notebook-on-kube's
        """
        notebooks: list[NotebookStatus.Notebook] = []
        for release in list_releases(username=username, kube_token=kube_token):
            release_name = release["name"]
            if not is_notebook_release(release_name=release_name, chart=release["chart"]):
                continue
            notebook_info = {"name": release_name}
            try:
                notebook_info |= cls.fetch_notebook_info(release_name=release_name, kube_token=kube_token)
            except NOKException as exc:
                logger.error(f"Could not fetch info about {release_name=}: {exc}")
            notebooks.append(cls.Notebook(**notebook_info))

        return {
            "kube_cluster_name": KUBE_CLUSTER_NAME,
            "notebooks_namespace": NOTEBOOKS_NAMESPACE,
            "notebooks": notebooks,
            "not_running": cls.Notebook.not_running,
        }


@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "kube_cluster_name": KUBE_CLUSTER_NAME})


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/favicon.ico")


@router.post("/login/", response_class=RedirectResponse)
def login(kube_token: str = Form()) -> RedirectResponse:
    # Maybe by stripping it we help a hacker getting a valid token :)
    kube_token = kube_token.strip()
    validate_kube_token(kube_token=kube_token)
    response = RedirectResponse(url=app.url_path_for("list_notebooks"), status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=KUBE_TOKEN_COOKIE_NAME,
        value=kube_token,
        path=router.prefix,
        # 8 hours
        max_age=28800,
        httponly=True,
        samesite="strict",
    )
    return response


@router.get("/notebooks/", response_class=HTMLResponse)
def list_notebooks(
    request: Request,
    kube_token: str = Depends(valid_kube_token),
    username: str = Depends(username_from_email),
    notebook_status: NotebookStatus = Depends(),
):
    return templates.TemplateResponse(
        "notebooks.html",
        {
            "request": request,
            "username": username,
            "notebook_status": notebook_status.template_context(username=username, kube_token=kube_token),
        },
    )


@router.get("/new_notebook/", response_class=HTMLResponse)
def new_notebook(
    request: Request, username: str = Depends(username_from_email), notebook_config: NotebookConfig = Depends()
):
    return templates.TemplateResponse(
        "new_notebook.html",
        {"request": request, "username": username, "notebook_config": notebook_config.template_context()},
    )


@router.post("/create_notebook/")
def create_notebook(
    kube_token: str = Depends(valid_kube_token),
    notebook_name: str = Depends(complete_notebook_name_from_form),
    form=Depends(get_form_data),
    notebook_config: NotebookConfig = Depends(),
) -> RedirectResponse:
    if notebook_exists(notebook_name=notebook_name, kube_token=kube_token):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"The Notebook {notebook_name=} already exists.",
        )

    deploy_notebook(
        notebook_name=notebook_name,
        values_file=notebook_config.form_data_to_values_file(form_data=form),
        kube_token=kube_token,
    )
    return RedirectResponse(url=app.url_path_for("list_notebooks"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/delete_notebook/{notebook_name}")
def delete_notebook(kube_token: str = Depends(valid_kube_token), notebook_name: str = Depends(existing_notebook_name)):
    body: list[str] = ["delete", notebook_name]
    try:
        helm(body=body, kube_token=kube_token)
    except NOKException as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not delete the Notebook {notebook_name=}: {exc}",
        )
    return RedirectResponse(url=app.url_path_for("list_notebooks"), status_code=status.HTTP_303_SEE_OTHER)


@router.get("/scale_notebook/{notebook_name}")
def scale_notebook(
    scale: Literal["0", "1"],
    kube_token: str = Depends(valid_kube_token),
    notebook_name: str = Depends(existing_notebook_name),
):
    try:
        scale_notebook_statefulset(notebook_name=notebook_name, kube_token=kube_token, replicas=int(scale))
    except NOKException as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not scale the Notebook {notebook_name=}: {exc}",
        )
    return RedirectResponse(url=app.url_path_for("list_notebooks"), status_code=status.HTTP_303_SEE_OTHER)


@router.get("/notebook_events/{notebook_name}", response_class=PlainTextResponse)
def notebook_events(kube_token: str = Depends(valid_kube_token), notebook_name: str = Depends(existing_notebook_name)):
    return get_notebook_events(notebook_name=notebook_name, kube_token=kube_token)


@router.get("/healthz")
def healthz():
    return {"status": "Seems healthy"}


# Allow users with not "well-formed" tokens to test.
if os.environ.get("NOK_TEST_MODE") == "on":
    logger.warning("notebooks-on-kube is running in test mode!")

    def username_from_email_mock(*, kube_token: str = Depends(valid_kube_token)) -> str:
        return "tester"

    app.dependency_overrides[username_from_email] = username_from_email_mock

# Keep at the end
app.include_router(router)


def run():
    import uvicorn

    uvicorn.run("notebook_on_kube.main:app", host="0.0.0.0", port=8000, reload=True)
