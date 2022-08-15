from agent_build.docker_image_builders import K8S_DEFAULT_BUILDERS, K8S_EXTENDED_BUILDERS, ALL_DOCKER_IMAGE_BUILDERS


DEFAULT_KUBERNETES_VERSION = {
    "kubernetes_version": "v1.22.7",
    "minikube_driver": "",
    "container_runtime": "docker",
}

KUBERNETES_VERSIONS = [
    {
        "kubernetes_version": "v1.20.15",
        "minikube_driver": "",
        "container_runtime": "docker",
    },
    {
        "kubernetes_version": "v1.21.10",
        "minikube_driver": "",
        "container_runtime": "docker",
    },
    DEFAULT_KUBERNETES_VERSION,
    {
        "kubernetes_version": "v1.23.4",
        "minikube_driver": "docker",
        "container_runtime": "containerd",
    },
    {
        "kubernetes_version": "v1.24.0",
        "minikube_driver": "docker",
        "container_runtime": "containerd",
    },
    {
        "kubernetes_version": "v1.17.17",
        "minikube_driver": "",
        "container_runtime": "docker",
    },
]

TEST_PARAMS = []

for builder_cls in K8S_DEFAULT_BUILDERS:
    TEST_PARAMS.append(
        {"image_builder_name": builder_cls.get_name(), **DEFAULT_KUBERNETES_VERSION}
    )

DEFAULT_K8S_IMAGE_BUILDER = ALL_DOCKER_IMAGE_BUILDERS["k8s-debian"]

EXTENDED_TEST_PARAMS = TEST_PARAMS.copy()
for k_v in KUBERNETES_VERSIONS:
    EXTENDED_TEST_PARAMS.append(
        {"image_builder_name": DEFAULT_K8S_IMAGE_BUILDER.get_name(), **k_v}
    )
for builder_cls in K8S_EXTENDED_BUILDERS:
    TEST_PARAMS.append({"image_builder_name": builder_cls.get_name(), **DEFAULT_KUBERNETES_VERSION})