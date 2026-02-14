import docker
import tempfile
import os
import shutil

DOCKER_IMAGE = "python:3.11-slim"


class DockerSandbox:
    def __init__(self, image: str = DOCKER_IMAGE):
        self.client = docker.from_env()
        self.image = image
        self._ensure_image()

    def _ensure_image(self):
        """Pull image if not exists"""
        try:
            self.client.images.get(self.image)
        except:
            print(f"Pulling Docker image {self.image}...")
            self.client.images.pull(self.image)

    def execute(self, code: str, context: str) -> str:
        """Execute code in isolated Docker container"""

        # Create temp directory for the container
        temp_dir = tempfile.mkdtemp()

        try:
            # Write context to file
            context_path = os.path.join(temp_dir, "context.txt")
            with open(context_path, "w", encoding="utf-8") as f:
                f.write(context)

            # Create execution script
            script = f"""
import re

# Load context
with open("context.txt", "r") as f:
    context = f.read()

# Execute user code
{code}
"""
            script_path = os.path.join(temp_dir, "execute.py")
            with open(script_path, "w") as f:
                f.write(script)

            # Run in container
            container = self.client.containers.run(
                self.image,
                f"python execute.py",
                volumes={temp_dir: {"bind": "/app", "mode": "ro"}},
                working_dir="/app",
                remove=True,
                mem_limit="256m",
                cpu_period=100000,
                cpu_quota=50000,
                network_disabled=True,
                detach=True,
            )

            # Wait for container to finish
            result = container.wait()

            # Get logs
            output = container.logs(stdout=True, stderr=True).decode("utf-8")
            return output if output else "Code executed successfully (no output)"

        finally:
            # Cleanup
            shutil.rmtree(temp_dir, ignore_errors=True)

    def close(self):
        """Close docker client"""
        self.client.close()
