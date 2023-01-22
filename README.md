# notebook-on-kube

Create and manage your `Jupyter` notebooks on `Kubernetes` with ease using bare minimum code.

### Why?

If you want to deploy `Jupyter` notebooks on `Kubernetes` using available open-source solutions, you would have to choose between two major approaches:

- Solutions that re-implement the notebooks management logic the `Kubernetes` way (using [Operators](https://kubernetes.io/docs/concepts/extend-kubernetes/operator/) and [CRD](https://kubernetes.io/docs/concepts/extend-kubernetes/api-extension/custom-resources/)),
usually they are part of a bigger toolkit ([Kubeflow](https://www.kubeflow.org) e.g.), they are complicated, come with more features than one may need and add a lot of maintenance burden even for people who are familiar with `Kubernetes`.
- Solutions that re-use already existing notebooks management code (mainly [JupyterHub](https://jupyter.org/hub)) and try to integrate it with `Kubernetes`,
people who are familiar with managing notebooks outside/before Kubernetes don't feel unaccustomed this way, because of this we "Don't reinvent the wheel", but we end up with
hacky `Porting`/`Connector` code everywhere, and we introduce feature redundancy: Kubernetes already supports [auth](https://kubernetes.io/docs/reference/access-authn-authz/authentication/)/[authz](https://kubernetes.io/docs/reference/access-authn-authz/authorization/)(user management),
already has [Helm](https://helm.sh) to deploy and manage its resources and provides easy reverse proxying using [Ingress NGINX Controller](https://github.com/kubernetes/ingress-nginx). Why not using these features/tools that are already there and are tailored to run applications on `Kubernetes`?

`notebook-on-kube` is an attempt to provide such a tool!

<p align="center">
  <img src="artwork/notebook-on-kube.drawio.png" />
</p>

### Use

```bash
# Add repo
helm repo add notebook-on-kube https://machine424.github.io/notebook-on-kube
# Deploy
helm install nok notebook-on-kube/notebook-on-kube
# Port-forward
kubectl port-forward service/nok-ingress-nginx-controller 8080:80
# Go to
localhost:8080
```

You should land on

<p align="center">
  <img src="artwork/login.png" />
</p>

#### Create, connect to and delete a notebook

<p align="center">
  <img src="artwork/create-notebook.gif" />
</p>

#### Note

- the Kubernetes OIDC token should contain an `email` claim and the local part of it should be unique as it's used to identify users.
If you want to skip this validation and use any token to test, set the environment variable `NOK_TEST_MODE=on` (see [values.yaml](deploy/notebook-on-kube/values.yaml)).
- `notebook-on-kube` is not meant to be exposed to the internet as some paths are not "protected" (`/connect_notebook` e.g.),
use port-forwarding to interact with it, or use external authn ([Oauth2](https://kubernetes.github.io/ingress-nginx/examples/auth/oauth-external-auth/) e.g.) or other, if you don't have a choice.
- By default, the notebooks have token-based authentication on, the token is set to the notebook's name.

### TODO
- Automate helm chart release.
- Add JSON Schema for the Helm values (front + back (Python and/or Helm))
- Add a YAML Editor on `/create_notebook` (validation etc.)
- Replace `/scale_notebook` with a more generic `/edit_noetbook` (with YAML editor) that will `helm upgrade` with the new values.
- Enable culling support: Add Prometheus metric exporter + Kube HPA (prom adapter).
- Fastapi: More async?
- Maybe: Make this more generic to deploy other notebooks or even `xxx-on-kube`.
