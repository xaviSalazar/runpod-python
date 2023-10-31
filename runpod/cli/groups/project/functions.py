'''
RunPod | CLI | Project | Functions
'''

import os
import sys
import uuid

import click
import tomlkit
from tomlkit import document, comment, table, nl

from runpod import __version__, get_pod, create_template, create_endpoint
from runpod.cli.utils.ssh_cmd import SSHConnection
from .helpers import get_project_pod, copy_template_files, attempt_pod_launch, load_project_config
from ...utils.rp_sync import sync_directory

STARTER_TEMPLATES = os.path.join(os.path.dirname(__file__), 'starter_templates')

# -------------------------------- New Project ------------------------------- #
def create_new_project(project_name, runpod_volume_id, python_version, # pylint: disable=too-many-locals, too-many-arguments, too-many-statements
                       model_type=None, model_name=None, init_current_dir=False):
    """ Create a new project. """
    if not init_current_dir:
        project_folder = os.path.join(os.getcwd(), project_name)
        if not os.path.exists(project_folder):
            os.makedirs(project_folder)

        if model_type is None:
            model_type = "default"

        template_dir = os.path.join(STARTER_TEMPLATES, model_type)

        copy_template_files(template_dir, project_folder)

        # Replace placeholders in requirements.txt
        requirements_path = os.path.join(project_folder, "builder/requirements.txt")
        with open(requirements_path, 'r', encoding='utf-8') as requirements_file:
            requirements_content = requirements_file.read()

        if "dev" in __version__:
            requirements_content = requirements_content.replace(
                '<<RUNPOD>>', 'git+https://github.com/runpod/runpod-python.git')
        else:
            requirements_content = requirements_content.replace(
                '<<RUNPOD>>', f'runpod=={__version__}')

        with open(requirements_path, 'w', encoding='utf-8') as requirements_file:
            requirements_file.write(requirements_content)

        # If there's a model_name, replace placeholders in handler.py
        if model_name:
            handler_path = os.path.join(project_name, "src/handler.py")
            with open(handler_path, 'r', encoding='utf-8') as file:
                handler_content = file.read()
                handler_content = handler_content.replace('<<MODEL_NAME>>', model_name)

            with open(handler_path, 'w', encoding='utf-8') as file:
                file.write(handler_content)
    else:
        project_folder = os.getcwd()

    project_uuid = str(uuid.uuid4())[:8]

    toml_config = document()
    toml_config.add(comment('RunPod Project Configuration'))
    toml_config.add(nl())
    toml_config.add("tittle", project_name)

    project_table = table()
    project_table.add("uuid", project_uuid)
    project_table.add("name", project_name)
    project_table.add("base_image", "runpod/base:0.2.1")
    project_table.add("gpu_types", [
        "NVIDIA RTX A4000", "NVIDIA RTX A4500", "NVIDIA RTX A5000",
        "NVIDIA GeForce RTX 3090", "NVIDIA RTX A6000"])
    project_table.add("gpu_count", 1)
    project_table.add("storage_id", runpod_volume_id)
    project_table.add("volume_mount_path", "/runpod-volume")
    project_table.add("ports", "8080/http, 22/tcp")
    project_table.add("container_disk_size_gb", 10)
    project_table.add("env_vars", {"RUNPOD_PROJECT_ID": project_uuid})
    toml_config.add("project", project_table)

    template_table = table()
    template_table.add("model_type", str(model_type))
    template_table.add("model_name", str(model_name))
    toml_config.add("template", template_table)

    runtime_table = table()
    runtime_table.add("python_version", python_version)
    runtime_table.add("handler_path", "src/handler.py")
    runtime_table.add("requirements_path", "builder/requirements.txt")
    toml_config.add("runtime", runtime_table)

    with open(os.path.join(project_folder, "runpod.toml"), 'w', encoding="UTF-8") as config_file:
        tomlkit.dump(toml_config, config_file)


# ------------------------------ Launch Project ------------------------------ #
def launch_project(): # pylint: disable=too-many-locals, too-many-branches
    '''
    Launch the project development environment from runpod.toml
    # SSH into the pod and create a project folder within the volume
    # Create a folder in the volume for the project that matches the project uuid
    # Create a folder in the project folder that matches the project name
    # Copy the project files into the project folder
    # crate a virtual environment using the python version specified in the project config
    # install the requirements.txt file
    '''
    config = load_project_config()

    for config_item in config['project']:
        print(f'    - {config_item}: {config["project"][config_item]}')
    print("")

    # Check if the project pod already exists.
    if get_project_pod(config['project']['uuid']):
        print('Project pod already launched. Run "runpod project start" to start.')
        return

    print("Launching pod on RunPod...")
    environment_variables = {"RUNPOD_PROJECT_ID": config["project"]["uuid"]}
    for variable in config['project']['env_vars']:
        if variable != "RUNPOD_PROJECT_ID":
            environment_variables[variable] = config['project']['env_vars'][variable]

    selected_gpu_types = config['project'].get('gpu_types',[])
    if config['project'].get('gpu', None):
        selected_gpu_types.append(config['project']['gpu'])

    new_pod = attempt_pod_launch(config, environment_variables)
    if new_pod is None:
        print("Selected GPU types unavailable, try again later or use a different type.")
        return

    print("Waiting for pod to come online... ", end="")
    sys.stdout.flush()

    # Wait for the pod to come online
    while new_pod.get('desiredStatus', None) != 'RUNNING' or new_pod.get('runtime', None) is None:
        new_pod = get_pod(new_pod['id'])

    print(f"Project {config['project']['name']} pod ({new_pod['id']}) created.")
    print("")

    ssh_conn = SSHConnection(new_pod['id'])

    project_path_uuid = f'{config["project"]["volume_mount_path"]}/{config["project"]["uuid"]}'
    project_path = f'{project_path_uuid}/{config["project"]["name"]}'

    print(f'Creating project folder: {project_path} on pod {new_pod["id"]}')
    ssh_conn.run_commands([f'mkdir -p {project_path}'])

    print(f'Copying files to pod {new_pod["id"]}')
    ssh_conn.rsync(os.getcwd(), project_path_uuid)

    venv_path = os.path.join(project_path_uuid, "venv")

    print(f'Creating virtual environment: {venv_path} on pod {new_pod["id"]}')
    commands = [
        f'python{config["runtime"]["python_version"]} -m venv {venv_path}',
        f'source {venv_path}/bin/activate &&' \
        f'cd {project_path} &&' \
        'python -m pip install --upgrade pip &&' \
        f'python -m pip install -r {config["runtime"]["requirements_path"]}'
    ]

    ssh_conn.run_commands(commands)


# ------------------------------- Start Project ------------------------------ #
def start_project_api():
    '''
    python handler.py --rp_serve_api --rp_api_host="0.0.0.0" --rp_api_port=8080
    '''
    config = load_project_config()

    project_pod = get_project_pod(config['project']['uuid'])
    if project_pod is None:
        raise click.ClickException(f'Project pod not found for uuid: {config["project"]["uuid"]}. Try running "runpod project launch" first.') # pylint: disable=line-too-long
    ssh_conn = SSHConnection(project_pod)

    project_uuid = config["project"]["uuid"]
    project_name = config["project"]["name"]
    volume_mount_path = config["project"]["volume_mount_path"]

    remote_project_path = os.path.join(volume_mount_path, project_uuid, project_name)

    requirements_path = os.path.join(remote_project_path, config['runtime']['requirements_path'])
    handler_path = os.path.join(remote_project_path, config['runtime']['handler_path'])

    sync_directory(ssh_conn, os.getcwd(), os.path.join(volume_mount_path, project_uuid))

    launch_api_server = [f'''
        pkill inotify

        function force_kill {{
            kill $1 2>/dev/null
            sleep 1

            if ps -p $1 > /dev/null; then
                echo "Graceful kill failed, attempting SIGKILL..."
                kill -9 $1 2>/dev/null
                sleep 1

                if ps -p $1 > /dev/null; then
                    echo "Failed to kill process with PID: $1"
                    exit 1
                else
                    echo "Killed process with PID: $1 using SIGKILL"
                fi

            else
                echo "Killed process with PID: $1"
            fi
        }}

        function cleanup {{
            echo "Cleaning up..."
            force_kill $last_pid
        }}

        trap cleanup EXIT

        if source {volume_mount_path}/{project_uuid}/venv/bin/activate; then
            echo -e "- Activated virtual environment."
        else
            echo "Failed to activate virtual environment."
            exit 1
        fi

        if cd {volume_mount_path}/{project_uuid}/{project_name}; then
            echo -e "- Changed to project directory."
        else
            echo "Failed to change directory."
            exit 1
        fi

        exclude_pattern='(__pycache__|\\.pyc$)'
        if [[ -f .runpodignore ]]; then
            while IFS= read -r line; do
                line=$(echo "$line" | tr -d '[:space:]')
                [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue # Skip comments and empty lines
                exclude_pattern="${{exclude_pattern}}|(${{line}})"
            done < .runpodignore
            echo -e "- Ignoring files matching pattern: $exclude_pattern"
        fi

        # Start the API server in the background, and save the PID
        python {handler_path} --rp_serve_api --rp_api_host="0.0.0.0" --rp_api_port=8080 --rp_api_concurrency=1 &
        last_pid=$!

        echo -e "- Started API server with PID: $last_pid" && echo ""
        echo "> Connect to the API server at:"
        echo "https://$RUNPOD_POD_ID-8080.proxy.runpod.net/docs" && echo ""

        while true; do
            if changed_file=$(inotifywait -q -r -e modify,create,delete --exclude "$exclude_pattern" {remote_project_path} --format '%w%f'); then
                echo "Detected changes in: $changed_file"
            else
                echo "Failed to detect changes."
                exit 1
            fi

            force_kill $last_pid

            if [[ $changed_file == *"requirements"* ]]; then
                echo "Installing new requirements..."
                python -m pip install --upgrade pip && python -m pip install -r {requirements_path}
            fi

            python {handler_path} --rp_serve_api --rp_api_host="0.0.0.0" --rp_api_port=8080 --rp_api_concurrency=1 &
            last_pid=$!

            echo "Restarted API server with PID: $last_pid"
        done
    ''']

    try:
        ssh_conn.run_commands(launch_api_server)
    finally:
        ssh_conn.close()


# ------------------------------ Deploy Project ------------------------------ #
def create_project_endpoint():
    """ Create a project endpoint.
    - Create a serverless template for the project
    - Create a new endpoint using the template
    """
    config = load_project_config()

    environment_variables = {}
    for variable in config['project']['env_vars']:
        environment_variables[variable] = config['project']['env_vars'][variable]

    # Construct the docker start command
    docker_start_cmd_prefix = 'bash -c "'
    activate_cmd = f'. /runpod-volume/{config["project"]["uuid"]}/venv/bin/activate'
    python_cmd = f'python -u /runpod-volume/{config["project"]["uuid"]}/{config["project"]["name"]}/{config["runtime"]["handler_path"]}' # pylint: disable=line-too-long
    docker_start_cmd_suffix = '"'
    docker_start_cmd = docker_start_cmd_prefix + activate_cmd + ' && ' + python_cmd + docker_start_cmd_suffix # pylint: disable=line-too-long

    project_endpoint_template = create_template(
        name =  f'{config["project"]["name"]}-endpoint | {config["project"]["uuid"]}',
        image_name = config['project']['base_image'],
        container_disk_in_gb = config['project']['container_disk_size_gb'],
        docker_start_cmd = docker_start_cmd,
        env = environment_variables, is_serverless = True
    )

    deployed_endpoint = create_endpoint(
        name = f'{config["project"]["name"]}-endpoint | {config["project"]["uuid"]}',
        template_id = project_endpoint_template['id'],
        network_volume_id=config['project']['storage_id'],
    )

    return deployed_endpoint['id']