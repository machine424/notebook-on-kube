## Usage

[Helm](https://helm.sh) must be installed to use the charts.  Please refer to
Helm's [documentation](https://helm.sh/docs) to get started.

Once Helm has been set up correctly, add the repo as follows:

  helm repo add notebook-on-kube https://machine424.github.io/notebook-on-kube

If you had already added this repo earlier, run `helm repo update` to retrieve
the latest versions of the packages.  You can then run `helm search repo
notebook-on-kube` to see the charts.

To install the notebook-on-kube chart:

    helm install nok notebook-on-kube/notebook-on-kube

To uninstall the chart:

    helm delete nok