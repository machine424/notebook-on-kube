# notebook-on-kube

![ci](https://github.com/machine424/notebook-on-kube/actions/workflows/test.yaml/badge.svg)
![docker](https://github.com/machine424/notebook-on-kube/actions/workflows/docker.yaml/badge.svg)
![helm](https://github.com/machine424/notebook-on-kube/actions/workflows/helm.yaml/badge.svg)

Create and manage your `Jupyter` notebooks on `Kubernetes` **without** `JupyterHub` :)

### How and why?

You can check out this [post](http://ouba.online/blog/2023/3/8/you_probably_dont_need_jupyterhub_on_kubernetes/post.html).

`notebook-on-kube` provides the following features:

- Authn/authz based on `Kubernetes'`.
- Customize and create notebooks.
- Connect to notebooks.
- Pause/Resume notebooks.
- Get notebooks' events.
- See [next steps](#next-steps).

<p align="center">
  <img src="artwork/notebook-on-kube.drawio.png" />
</p>

### How to use?

You need access to a `Kubernetes` cluster with an [OIDC token](https://kubernetes.io/docs/reference/access-authn-authz/authentication/#openid-connect-tokens).

- You can deploy `notebook-on-kube` on a `Kubernetes` cluster using Helm:
```bash
helm repo add notebook-on-kube https://machine424.github.io/notebook-on-kube
helm install nok notebook-on-kube/notebook-on-kube
```
- Or run the docker image directly from [here](https://hub.docker.com/repository/docker/machine424/notebook-on-kube/general).
- Or clone the repo and run:
```bash
pip install -e .
notebook-on-kube
```

You should land on:

<p align="center">
  <img src="artwork/login.png" />
</p>

#### Create, connect to and delete a notebook

<p align="center">
  <img src="artwork/create-notebook.gif" />
</p>

#### Notes

- the Kubernetes OIDC token should contain an `email` claim and the local part of it should be unique as it's used to identify users.
If you want to skip this validation and use any token to test, set the environment variable `NOK_TEST_MODE=on` (see [values.yaml](deploy/notebook-on-kube/values.yaml)).
- `notebook-on-kube` is not meant to be exposed to the internet as some paths are not "protected" (`/connect_notebook` e.g.),
use port-forwarding to interact with it, or use external authn ([Oauth2](https://kubernetes.github.io/ingress-nginx/examples/auth/oauth-external-auth/) e.g.) or other, if you don't have a choice.
- By default, the notebooks have token-based authentication on, the token is set to the notebook's name.

### Next steps
- Add JSON Schema for the Helm values (front + back (Python and/or Helm))
- Add a YAML Editor on `/create_notebook` (validation etc.)
- Replace `/scale_notebook` with a more generic `/edit_noetbook` (with YAML editor) that will `helm upgrade` with the new values.
- Enable culling support: Add Prometheus metric exporter + Kube HPA (prom adapter). Instead of [JupyterHub idle culler](https://github.com/jupyterhub/jupyterhub-idle-culler)
- Fastapi: More async?
- Maybe: Make this more generic to deploy other notebooks or even `xxx-on-kube`.
