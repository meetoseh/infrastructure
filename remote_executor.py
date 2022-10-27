"""Provides the RemoteExecution dynamic resource which allows you to
upload and execute scripts on remote machines managed by pulumi.
In particular, this supports the ability to proxy requests through
a bastion server - a common pattern when using VPCs.
"""
import traceback
import pulumi
import paramiko
from typing import Optional, TypedDict, Tuple, Dict
import io
import os
import secrets
import time
import hashlib
import re


class RemoteExecutionInputs:
    """The inputs that define a remote execution."""

    script_name: pulumi.Input[str]
    """The path to the script folder to execute. The script folder must
    at minimum have a `main.sh` file, but the entire folder is uploaded
    and then executed where the current working directory is at the root
    of the script folder.
    
    For example, if the script folder is `setup-scripts/reverse-proxy`,
    this will upload the folder `setup-scripts/reverse-proxy` to the
    target host, then cd into that folder, and execute `./main.sh`
    using `bash`. Finally, the target folder will be deleted from the
    remote machine and this will output the stdout and stderr.

    Furthermore, if the script folder has the `delete.sh` file, it
    will be executed if the resource is destroyed using the same process.
    """

    file_substitutions: pulumi.Input[Dict[str, Dict[str, str]]]
    """An optional list of substituions to make within script files. 
    The outermost keys refer to file names by relative path within the
    script folder, e.g., "main.sh". The innermost keys refer to the
    variables to substitute in the file, and the values are the values
    to substitute in.

    So, for example,

    file_substitutions = { "main.sh": { "VAR1": "value1" }}

    will replace {{VAR1}} in the main.sh file with "value1". Note
    that indentation is preserved during this process. Note that
    where slashes are used as a path separator, they must be unix-style
    (/)..
    """

    host: pulumi.Input[str]
    """If the host machine is directly reachable, this is the public
    ip address of the target machine. Otherwise, this is the private
    ip address of the target machine, which will be accessed via proxying
    through the bastion server.
    """

    private_key: pulumi.Input[str]
    """The private key to use to access the target machine and, if
    specified, the bastion. This should be a file path to the private
    key file stored in OpenSSH format.
    """

    bastion: pulumi.Input[Optional[str]]
    """If the target machine is not directly publicly reachable, the
    bastion server to proxy the ssh connection through.
    """

    shared_script_name: pulumi.Input[Optional[str]]
    """A path to an additional directory whose scripts should be installed
    on the remote machine. They will be accessible under the "shared" directory
    in the current working directory.
    """

    def __init__(
        self,
        script_name: str,
        file_substitutions: Dict[str, Dict[str, str]],
        host: str,
        private_key: str,
        bastion: Optional[str] = None,
        shared_script_name: Optional[str] = None,
    ):
        self.script_name = script_name
        self.file_substitutions = file_substitutions
        self.host = host
        self.private_key = private_key
        self.bastion = bastion
        self.shared_script_name = shared_script_name


class _RemoteExecutionInputs(TypedDict):
    script_name: str
    file_substitutions: Dict[str, Dict[str, str]]
    host: str
    private_key: str
    bastion: Optional[str]
    shared_script_name: Optional[str]


class _RemoteExecutionOutputs(TypedDict):
    """The outputs of a remote execution."""

    stdout: str
    """The resulting stdout from the execution."""

    stderr: str
    """The resulting stderr from the execution."""

    script_name: str
    """The path to the script folder which was executed"""

    file_substitutions: Dict[str, Dict[str, str]]
    """The file substitutions that were made during the execution."""

    script_hash: str
    """A stable hash of the contents of the script folder when the execution occurred,
    before substitutions have been made."""

    private_key: str
    """The private key used to access the target machine and, if
    specified, the bastion. This should be a file path to the private
    key file stored in OpenSSH format.
    """

    host: str
    """The host machine that the script was executed on"""

    bastion: Optional[str]
    """The bastion server that the script was executed through"""

    shared_script_name: Optional[str]
    """A path to an additional directory whose scripts should be installed
    on the remote machine. They will be accessible under the "shared" directory
    in the current working directory.
    """


class RemoteExecutionProvider(pulumi.dynamic.ResourceProvider):
    """Executes the scripts in setup-scripts/<script_name> on the remote
    host. In particular, this uploads the entire folder and runs main.sh,
    then deletes the folder. The started working directory is a subdirectory
    of "/usr/local/src"
    """

    def create(self, inputs: _RemoteExecutionInputs) -> pulumi.dynamic.CreateResult:
        id_ = secrets.token_hex(16)
        try:
            return pulumi.dynamic.CreateResult(
                id_=id_,
                outs=self.execute_remotely(
                    inputs["script_name"],
                    inputs.get("file_substitutions"),
                    inputs["host"],
                    inputs["private_key"],
                    inputs.get("bastion"),
                    inputs.get("shared_script_name"),
                ),
            )
        except:
            with open(f"remote_execution_error_{id_}.txt", "a") as f_out:
                print(f"{inputs=}", file=f_out)
                traceback.print_exc(file=f_out)
            raise

    def delete(self, id: str, olds: _RemoteExecutionOutputs) -> None:
        if not os.path.exists(os.path.join(olds["script_name"], "delete.sh")):
            return
        self.execute_remotely(
            olds["script_name"],
            olds.get("file_substitutions"),
            olds["host"],
            olds["private_key"],
            olds.get("bastion"),
            olds.get("shared_script_name"),
            "delete.sh",
        )

    def diff(
        self, id: str, olds: _RemoteExecutionOutputs, news: _RemoteExecutionInputs
    ) -> pulumi.dynamic.DiffResult:
        script_hash = hash_directory(news["script_name"])
        if news.get("shared_script_name") is not None:
            script_hash += "+" + hash_directory(news["shared_script_name"])

        replaces = []
        if olds["script_name"] != news["script_name"]:
            replaces.append("script_name")

        if olds.get("file_substitutions") != news.get("file_substitutions"):
            replaces.append("file_substitutions")

        if olds["script_hash"] != script_hash:
            replaces.append("script_hash")

        if olds["host"] != news["host"]:
            replaces.append("host")

        if olds.get("bastion") != news.get("bastion"):
            replaces.append("bastion")

        if not replaces:
            return pulumi.dynamic.DiffResult(changes=False)

        return pulumi.dynamic.DiffResult(
            changes=True,
            replaces=replaces,
            delete_before_replace=olds["host"] == news["host"],
        )

    def execute_remotely(
        self,
        script_name: str,
        file_substitutions: Dict[str, Dict[str, str]],
        host: str,
        private_key: str,
        bastion: Optional[str] = None,
        shared_script_name: Optional[str] = None,
        entrypoint: str = "main.sh",
    ) -> _RemoteExecutionOutputs:
        """Executes the given script on the remote host. May configure the
        entrypoint, ie., which file to execute once the script is uploaded.
        """
        dirhash = hash_directory(script_name)

        if shared_script_name is not None:
            dirhash += "+" + hash_directory(shared_script_name)

        single_file_script = io.StringIO()
        single_file_script.write("cd /usr/local/src\n")
        single_file_script.write('echo "sfs here 0"\n')

        remote_dir = secrets.token_hex(8)
        key_file = None if bastion is None else secrets.token_hex(8)
        write_echo_commands_for_folder(
            script_name,
            remote_dir,
            single_file_script,
            file_substitutions=file_substitutions,
        )

        if shared_script_name is not None:
            write_echo_commands_for_folder(
                shared_script_name,
                os.path.join(remote_dir, "shared"),
                single_file_script,
                file_substitutions=file_substitutions,
            )

        if bastion is None:
            single_file_script.write(f"cd {remote_dir}\n")
            single_file_script.write(f"bash {entrypoint}\n")
            single_file_script.write("cd ..\n")
        else:
            write_echo_commands_for_file(
                private_key, key_file, single_file_script, mark_executable=False
            )
            single_file_script.write(f"chmod 400 {key_file}\n")
            single_file_script.write('echo "sfs here 1"\n')
            single_file_script.write(
                f"while ! ssh -i {key_file} -oStrictHostKeyChecking=no -oBatchMode=no ec2-user@{host} true\n"
            )
            single_file_script.write("do\n")
            single_file_script.write("  sleep 1\n")
            single_file_script.write("done\n")

            single_file_script.write(
                f"sftp -i {key_file} -oStrictHostKeyChecking=no -oBatchMode=no -b - ec2-user@{host} <<EOF\n"
            )
            single_file_script.write(f"put -r {remote_dir}\n")
            single_file_script.write("EOF\n")
            single_file_script.write('echo "sfs here 2"\n')
            single_file_script.write(
                f"ssh -i {key_file} -oStrictHostKeyChecking=no -oBatchMode=no ec2-user@{host} <<EOF\n"
            )
            single_file_script.write(f"cd {remote_dir}\n")
            single_file_script.write(f"sudo bash {entrypoint}\n")
            single_file_script.write("cd ..\n")
            single_file_script.write(f"rm -rf {remote_dir}\n")
            single_file_script.write("EOF\n")
            single_file_script.write('echo "sfs here 3"\n')

        single_file_script.write(f"rm -rf {remote_dir}\n")

        if bastion is not None:
            single_file_script.write(f"rm -f {key_file}\n")

        single_file_script_str = single_file_script.getvalue()

        for _ in range(150):
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                client.connect(
                    hostname=host if bastion is None else bastion,
                    username="ec2-user",
                    key_filename=private_key,
                    look_for_keys=False,
                    auth_timeout=5,
                    banner_timeout=5,
                )
            except Exception:
                time.sleep(2)
                continue
            sftp = client.open_sftp()

            single_file_script_iden = secrets.token_hex(8) + ".sh"
            single_file_script_remote_path = f"/home/ec2-user/{single_file_script_iden}"
            with sftp.open(single_file_script_remote_path, "w") as remote_file:
                remote_file.write(single_file_script_str)

            sftp.chmod(single_file_script_remote_path, 0o755)
            sftp.close()

            exec_simple(client, "cd ~")
            stdout, stderr = exec_simple(client, f"sudo bash {single_file_script_iden}")
            exec_simple(client, f"rm {single_file_script_iden}")

            client.close()

            return _RemoteExecutionOutputs(
                stdout=stdout,
                stderr=stderr,
                script_name=script_name,
                file_substitutions=file_substitutions,
                script_hash=dirhash,
                private_key=private_key,
                host=host,
                bastion=bastion,
            )


class RemoteExecution(pulumi.dynamic.Resource):
    """Executes the given scripts on the remote server. This is provided
    a directory of scripts, for which the "main.sh" script is executed
    when the RemoteExecution is created and the "delete.sh" script is
    executed when the RemoteExecution is destroyed.

    The RemoteExecution is considered invalidated if the target directory
    changes - when this happens, the _new_ delete.sh script is executed.
    """

    stdout: pulumi.Output[str]
    """The resulting stdout from the execution."""

    stderr: pulumi.Output[str]
    """The resulting stderr from the execution."""

    script_name: pulumi.Output[str]
    """The path to the script folder which was executed"""

    script_hash: pulumi.Output[str]
    """A stable hash of the contents of the script folder when the execution occurred"""

    host: pulumi.Output[str]
    """The host machine that the script was executed on"""

    bastion: pulumi.Output[Optional[str]]
    """The bastion server that the script was executed through"""

    def __init__(
        self,
        name: str,
        props: RemoteExecutionInputs,
        opts: Optional[pulumi.ResourceOptions] = None,
    ):
        super().__init__(
            RemoteExecutionProvider(),
            name,
            {
                "stdout": None,
                "stderr": None,
                "script_name": None,
                "file_substitutions": None,
                "script_hash": None,
                "host": None,
                "bastion": None,
                **vars(props),
            },
            opts,
        )


def exec_simple(
    client: paramiko.SSHClient, command: str, timeout=15, cmd_timeout=3600
) -> Tuple[str, str]:
    """Executes the given command on the paramiko client, waiting for
    the command to finish before returning the stdout and stderr
    """
    chan = client.get_transport().open_session(timeout=timeout)
    chan.settimeout(cmd_timeout)
    chan.exec_command(command)
    stdout = chan.makefile("r", 8192)
    stderr = chan.makefile_stderr("r", 8192)

    all_stdout = io.BytesIO()
    all_stderr = io.BytesIO()

    while not chan.exit_status_ready():
        time.sleep(0.1)

        from_stdout = stdout.read(4096)
        from_stderr = stderr.read(4096)

        if from_stdout is not None:
            all_stdout.write(from_stdout)

        if from_stderr is not None:
            all_stderr.write(from_stderr)

    while from_stdout := stdout.read(4096):
        all_stdout.write(from_stdout)

    while from_stderr := stderr.read(4096):
        all_stderr.write(from_stderr)

    return all_stdout.getvalue().decode(
        "utf-8", errors="replace"
    ), all_stderr.getvalue().decode("utf-8", errors="replace")


def hash_directory(dirpath: str) -> str:
    """Returns a stable hash of the given directory"""
    hasher = hashlib.sha256()
    for root, _, files in os.walk(dirpath):
        for file in files:
            with open(os.path.join(root, file), "rb") as f:
                hasher.update(f.read())
    return hasher.hexdigest()


def write_echo_commands_for_folder(
    infile_path: str,
    echo_path: str,
    writer: io.StringIO,
    file_substitutions: Optional[Dict[str, Dict[str, str]]] = None,
) -> None:
    """Writes the appropriate commands to echo the local folder at infile_path
    to the remote folder at echo_path. Only supports text files.
    """
    writer.write(f"mkdir -p {echo_path.replace(os.path.sep, '/')}\n")
    for root, _, files in os.walk(infile_path):
        relative_root = os.path.relpath(root, infile_path)
        if relative_root != ".":
            writer.write(
                f"mkdir -p {os.path.join(echo_path, relative_root).replace(os.path.sep, '/')}\n"
            )

        for file in files:
            infile_filepath = os.path.join(root, file)
            echo_file_path = os.path.join(
                echo_path, relative_root if relative_root != "." else "", file
            )
            this_file_subs = None
            if file_substitutions is not None:
                echo_file_path_normalized = os.path.join(
                    relative_root if relative_root != "." else "", file
                ).replace(os.path.sep, "/")
                this_file_subs = file_substitutions.get(echo_file_path_normalized)
            write_echo_commands_for_file(
                infile_filepath,
                echo_file_path,
                writer,
                file_substitutions=this_file_subs,
            )


def write_echo_commands_for_file(
    infile_path: str,
    echo_file_path: str,
    writer: io.StringIO,
    mark_executable: bool = True,
    file_substitutions: Optional[Dict[str, str]] = None,
) -> None:
    """Writes the appropriate c ommands to echo the local file at infile_path
    to the remote file at echo_file_path. Only supports text files.
    """
    echo_file_path = echo_file_path.replace(os.path.sep, "/")
    with open(infile_path, "r") as infile:
        for original_line in infile:
            for line in apply_substitutions(original_line, file_substitutions):
                cleaned_line = line.rstrip().replace("\\", "\\\\").replace("'", "\\'")
                writer.write(f"echo $'{cleaned_line}' >> {echo_file_path}\n")

    if mark_executable:
        writer.write(f"chmod +x {echo_file_path}\n")
    writer.write(f'echo "finished writing {echo_file_path}"\n')
    # print file size:
    writer.write(f"du -sh {echo_file_path}\n")


INDENTATION_PRESERVED_REGEX = re.compile(r"^(?P<indent>\s*)\{\{(?P<key>.+?)\}\}")
SIMPLE_SUBSTITUTION_REGEX = re.compile(r"\{\{(?P<key>.+?)\}\}")


def apply_substitutions(line: str, file_substitutions: Optional[Dict[str, str]] = None):
    """Applies the given substitutions to the given line. This acts in
    two formats - when the line consists of just whitespace followed
    by a single substitution and the substituted value contains newlines,
    then we will preserve indentation. So '  {{foo}}' where foo is 'a\nb'
    will be converted to '  a\n  b'.

    In all other cases, the substitution is direct.

    Returns the list of lines that were generated.
    """
    if not file_substitutions:
        return [line]

    if match := INDENTATION_PRESERVED_REGEX.match(line):
        indent = match.group("indent")
        key = match.group("key")

        assert key in file_substitutions, f"{key=} not in {file_substitutions=}"

        value = file_substitutions[key]

        result = []
        for subline in value.split("\n"):
            result.append(indent + subline)
        return result

    return [
        SIMPLE_SUBSTITUTION_REGEX.sub(
            lambda m: file_substitutions.get(m.group("key"), ""), line
        )
    ]
