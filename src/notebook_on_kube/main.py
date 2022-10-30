import json
import logging
from enum import Enum
from functools import lru_cache
from typing import Final, Literal

import jwt
from fastapi import Cookie, Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.datastructures import FormData
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Extra

from notebook_on_kube.utils import (
    NOKException,
    helm,
    is_notebook_release,
    kubectl,
    valid_name,
)

logger = logging.getLogger(__name__)

NOTEBOOKS_NAMESPACE: Final[str] = "default"
KUBE_TOKEN_COOKIE_NAME: Final[str] = "kube_token"
JUPYTER_NOTEBOOK_CHART_PATH: Final[str] = "helm-chart/jupyter-notebook"


class StrictModel(BaseModel, extra=Extra.forbid):
    pass


app = FastAPI()
# TODO: Temp, use nginx
app.mount("/static", StaticFiles(directory="ui"), name="static")
templates = Jinja2Templates(directory="ui")


class NoteBookSpecialStatus(Enum):
    MISSING_STATEFULSET = "Statefulset Missing"
    NOT_RUNNING = "Not Running"


class Notebook(StrictModel):
    name: str
    image: str
    status: str = NoteBookSpecialStatus.NOT_RUNNING.value
    start_time: str = NoteBookSpecialStatus.NOT_RUNNING.value
    events: str | None = None
    errors: str | None = None

    def connect_link(self) -> str:
        return f"/connect_notebook/{self.name}"

    def pause_resume_link(self) -> str:
        scale = 1 if self.status == NoteBookSpecialStatus.NOT_RUNNING.value else 0
        return f"/scale_notebook/{self.name}?scale={scale}"

    def delete_link(self) -> str:
        return f"/delete_notebook/{self.name}"

    def events_link(self) -> str:
        return f"/notebook_events/{self.name}"


def validate_kube_token(*, kube_token: str) -> None:
    """
    We require being able to list secrets in NOTEBOOKS_NAMESPACE
    """
    try:
        body = [
            "auth",
            "can-i",
            "list",
            "secret",
            "--namespace",
            NOTEBOOKS_NAMESPACE,
        ]
        kubectl(body=body, kube_token=kube_token)
    except NOKException as e:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail=f"The kube_token in not valid: {e}",
        )


def valid_kube_token(kube_token: str | None = Cookie(default=None)) -> str:
    if kube_token:
        validate_kube_token(kube_token=kube_token)
        return kube_token
    else:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Where is my kube_token cookie?",
        )


@lru_cache(maxsize=32)
def valid_username(*, kube_token: str = Depends(valid_kube_token)) -> str:
    """
    Suppose "email" is present and the local part of the email is a valid
    """
    try:
        # the Kube API takes care of the signature verification
        content = jwt.decode(kube_token, options={"verify_signature": False})
        email = content["email"]
        local_part = email.split("@", maxsplit=1)[0]
        return valid_name(string=local_part)
    except (jwt.exceptions.InvalidTokenError, KeyError, IndexError, NOKException) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not get a valid username from kube_token: {e}",
        )


def complete_notebook_name_from_form(
    *, notebook_name: str = Form(), username: str = Depends(valid_username)
) -> str:
    complete_name = f"{username}-{notebook_name}"
    try:
        valid_name(string=complete_name)
        return complete_name
    except NOKException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"The Notebook {complete_name=} is not valid: {e}",
        )


def notebook_exists(*, notebook_name: str, kube_token: str) -> bool | None:
    body: list[str] = [
        "list",
        "--filter",
        f"^{notebook_name}$",
        "--all",
        "--namespace",
        NOTEBOOKS_NAMESPACE,
        "--output",
        "json",
    ]
    try:
        return len(json.loads(helm(body=body, kube_token=kube_token))) == 1
    except (NOKException, AssertionError) as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not check if the Notebook {notebook_name=} exists: {e}",
        )


def existing_notebook_name(
    *, notebook_name: str, kube_token: str = Depends(valid_kube_token)
) -> str:
    if not notebook_exists(notebook_name=notebook_name, kube_token=kube_token):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"The Notebook {notebook_name=} does not exist.",
        )
    return notebook_name


@app.post("/login/", response_class=RedirectResponse)
def login(kube_token: str = Form()) -> RedirectResponse:
    # Maybe by stripping it we help a hacker getting a valid token :)
    kube_token = kube_token.strip()
    validate_kube_token(kube_token=kube_token)
    response = RedirectResponse(
        url="/notebooks/", status_code=status.HTTP_303_SEE_OTHER
    )
    response.set_cookie(key=KUBE_TOKEN_COOKIE_NAME, value=kube_token, httponly=True)
    return response


def get_notebook_pod(*, release_name: str, kube_token: str) -> dict | None:
    """
    Assumes there is only one
    """
    kubectl_body: list[str] = [
        "get",
        "pod",
        "--selector",
        f"app.kubernetes.io/instance={release_name}",
        "--namespace",
        NOTEBOOKS_NAMESPACE,
        "--output",
        "json",
    ]
    try:
        return json.loads(kubectl(body=kubectl_body, kube_token=kube_token))["items"][0]
    except IndexError:
        return None


def get_notebook_statefulset(*, release_name: str, kube_token: str) -> dict | None:
    """
    Assumes there is only one
    """
    kubectl_body: list[str] = [
        "get",
        # TODO: Change to statefulset
        "deployment",
        "--selector",
        f"app.kubernetes.io/instance={release_name}",
        "--namespace",
        NOTEBOOKS_NAMESPACE,
        "--output",
        "json",
    ]
    try:
        return json.loads(kubectl(body=kubectl_body, kube_token=kube_token))["items"][0]
    except IndexError:
        return None


def scale_notebook_statefulset(*, notebook_name: str, kube_token: str, replicas: int):
    kubectl_body: list[str] = [
        "scale",
        # TODO: Change to statefulset
        "deployment",
        "--selector",
        f"app.kubernetes.io/instance={notebook_name}",
        "--replicas",
        str(replicas),
        "--namespace",
        NOTEBOOKS_NAMESPACE,
    ]
    kubectl(body=kubectl_body, kube_token=kube_token)


def fetch_notebook_info(*, release_name: str, kube_token: str) -> dict[str, str]:
    statefulset = get_notebook_statefulset(
        release_name=release_name, kube_token=kube_token
    )
    pod = get_notebook_pod(release_name=release_name, kube_token=kube_token)
    info = {}
    if not statefulset:
        info |= {
            "status": NoteBookSpecialStatus.MISSING_STATEFULSET.value,
            "image": NoteBookSpecialStatus.MISSING_STATEFULSET.value,
        }
    elif pod:
        info |= {
            "status": pod["status"]["phase"],
            "image": pod["spec"]["containers"][0]["image"],
        }
        start_time = pod["status"].get("startTime")
        if start_time is not None:
            info["start_time"] = start_time
    else:
        info |= {
            "image": statefulset["spec"]["template"]["spec"]["containers"][0]["image"]
        }
    return info


def fetch_notebooks(*, username: str, kube_token: str) -> list[Notebook]:
    """
    Supposes every release from JUPYTER_NOTEBOOK_CHART_NAME is notebook-on-kube's
    """
    helm_body: list[str] = [
        "list",
        "--filter",
        f"^{username}-.+$",
        "--all",
        "--namespace",
        NOTEBOOKS_NAMESPACE,
        "--output",
        "json",
    ]
    try:
        releases = json.loads(helm(body=helm_body, kube_token=kube_token))
    except NOKException as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not list Notebooks: {e}",
        )

    notebooks: list[Notebook] = []
    for release in releases:
        release_name = release["name"]
        if not is_notebook_release(release_name=release_name, chart=release["chart"]):
            continue
        notebook_info = {"name": release_name}
        try:
            notebook_info |= fetch_notebook_info(
                release_name=release_name, kube_token=kube_token
            )
        except NOKException as e:
            notebook_info["errors"] = f"Could not fetch info about Notebook: {e}"
        notebooks.append(Notebook(**notebook_info))
    return notebooks


@app.get("/notebooks/", response_class=HTMLResponse)
def list_notebooks(
    request: Request,
    kube_token: str = Depends(valid_kube_token),
    username: str = Depends(valid_username),
):
    return templates.TemplateResponse(
        "notebooks.html",
        {
            "request": request,
            "username": username,
            "notebooks_namespace": NOTEBOOKS_NAMESPACE,
            "notebooks": fetch_notebooks(username=username, kube_token=kube_token),
            "notebook_not_running": NoteBookSpecialStatus.NOT_RUNNING.value,
        },
    )


class NewNotebookExtraConfig:
    @classmethod
    def template_to_include(cls) -> str | None:
        return None

    @classmethod
    def form_data_to_helm_values(cls, *, form_data: FormData) -> dict[str, str]:
        """
        This should take care of the extra config validation.
        """
        return {}


@app.get("/new_notebook/", response_class=HTMLResponse)
def new_notebook(
    request: Request,
    username: str = Depends(valid_username),
    new_notebook_extra_config: NewNotebookExtraConfig = Depends(),
):
    return templates.TemplateResponse(
        "new_notebook.html",
        {
            "request": request,
            "notebooks_namespace": NOTEBOOKS_NAMESPACE,
            "username": username,
            "template_to_include": new_notebook_extra_config.template_to_include(),
        },
    )


def deploy_notebook(
    *,
    notebook_name: str,
    extra_helm_values: dict[str, str],
    kube_token: str,
):
    body: list[str] = [
        "install",
        notebook_name,
        JUPYTER_NOTEBOOK_CHART_PATH,
        "--namespace",
        NOTEBOOKS_NAMESPACE,
    ]
    if extra_helm_values:
        body.extend(
            [
                "--set",
                ",".join([f"{key}={value}" for key, value in extra_helm_values]),
            ]
        )
    try:
        helm(body=body, kube_token=kube_token)
    except NOKException as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not deploy the Notebook {notebook_name=}: {e}",
        )


async def get_form_data(*, request: Request) -> FormData:
    return await request.form()


@app.post("/create_notebook/")
def create_notebook(
    kube_token: str = Depends(valid_kube_token),
    notebook_name: str = Depends(complete_notebook_name_from_form),
    form=Depends(get_form_data),
    new_notebook_extra_config: NewNotebookExtraConfig = Depends(),
) -> RedirectResponse:
    if notebook_exists(notebook_name=notebook_name, kube_token=kube_token):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"The Notebook {notebook_name=} already exists.",
        )

    extra_helm_values = new_notebook_extra_config.form_data_to_helm_values(
        form_data=form
    )
    deploy_notebook(
        notebook_name=notebook_name,
        extra_helm_values=extra_helm_values,
        kube_token=kube_token,
    )
    return RedirectResponse(url="/notebooks/", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/delete_notebook/{notebook_name}")
def delete_notebook(
    kube_token: str = Depends(valid_kube_token),
    notebook_name: str = Depends(existing_notebook_name),
):
    body: list[str] = [
        "delete",
        notebook_name,
        "--namespace",
        NOTEBOOKS_NAMESPACE,
    ]
    try:
        helm(body=body, kube_token=kube_token)
    except NOKException as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not delete the Notebook {notebook_name=}: {e}",
        )
    return RedirectResponse(url="/notebooks/", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/scale_notebook/{notebook_name}")
def scale_notebook(
    scale: Literal["0", "1"],
    kube_token: str = Depends(valid_kube_token),
    notebook_name: str = Depends(existing_notebook_name),
):
    try:
        scale_notebook_statefulset(
            notebook_name=notebook_name, kube_token=kube_token, replicas=int(scale)
        )
    except NOKException as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not scale the Notebook {notebook_name=}: {e}",
        )
    return RedirectResponse(url="/notebooks/", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/notebook_events/{notebook_name}")
def notebook_events(
    kube_token: str = Depends(valid_kube_token),
    notebook_name: str = Depends(existing_notebook_name),
):
    # TODO: do job
    return RedirectResponse(url="/notebooks/", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/connect_notebook/{notebook_name}")
def connect_notebook(
    kube_token: str = Depends(valid_kube_token),
    notebook_name: str = Depends(existing_notebook_name),
):
    # TODO: do job
    return RedirectResponse(url="/notebooks/", status_code=status.HTTP_303_SEE_OTHER)


def main():
    import uvicorn

    # TODO: remove reload
    uvicorn.run("notebook_on_kube.main:app", host="0.0.0.0", port=8000, reload=True)
