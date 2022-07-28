from agent_build.tools.environment_deployments.deployments import CacheableBuilder, ShellScriptDeploymentStep
from agent_build.tools.constants import Architecture, SOURCE_ROOT


# Step that runs small script which installs requirements for the test/dev environment.
INSTALL_TEST_REQUIREMENT_STEP = ShellScriptDeploymentStep(
    name="install_test_requirements",
    architecture=Architecture.UNKNOWN,
    script_path= SOURCE_ROOT / "agent_build/tools/environment_deployments/steps/deploy-test-environment.sh",
    tracked_file_globs=[SOURCE_ROOT / "agent_build/requirement-files*.txt"],
    cacheable=True
)


class BuildTestEnvironment(CacheableBuilder):
    NAME = "test_environment"
    DEPLOYMENT_STEP = INSTALL_TEST_REQUIREMENT_STEP