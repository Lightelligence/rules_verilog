"""Bounded, fail-closed provenance for mutable discovery metadata.

This is not a Starlark evaluator. Only direct, literal native local repository
declarations are proven here. Macros, repository rules, overrides and unknown
external labels fall back to Bazel discovery instead of guessing their inputs.
"""

import ast
import os
import stat
import subprocess

MAX_ENTRIES = 50000
MAX_METADATA = 4096
MAX_DEPTH = 32
MAX_FILE_BYTES = 4 * 1024 * 1024
LOCAL_RULES = {"local_repository", "new_local_repository"}


def project_directory_symlink_error(project_root):
    """Check link topology without walking ordinary tracked source directories."""
    project_root = os.path.abspath(project_root)
    repositories = [project_root]
    directories = []
    repositories_seen = set()
    inspected = 0
    output_links = {
        "bazel-bin", "bazel-out", "bazel-testlogs", "bazel-{}".format(os.path.basename(project_root)),
        "bazel-{}".format(os.path.basename(os.path.realpath(project_root))), ".last_sim", ".last_fail"
    }

    def unsafe(path, detail):
        return {"kind": "incomplete_dependency_provenance", "path": path, "detail": detail}

    def excluded(path):
        parts = os.path.relpath(path, project_root).split(os.sep)
        return any(part in (".git", ".simmer") for part in parts) or parts[0] in output_links

    def directory_link(mode):
        return stat.S_ISLNK(mode.st_mode) or getattr(mode, "st_reparse_tag", 0) == getattr(
            stat, "IO_REPARSE_TAG_MOUNT_POINT", -1)

    def inspect(path, enqueue_directory=True):
        nonlocal inspected
        if excluded(path):
            return None
        inspected += 1
        if inspected > MAX_ENTRIES:
            return unsafe(path, "Project directory link inspection limit exceeded")
        try:
            mode = os.lstat(path)
            if directory_link(mode) and os.path.isdir(path):
                return unsafe(path, "Project directory symlink or junction requires fresh Bazel discovery")
            if stat.S_ISDIR(mode.st_mode) and enqueue_directory:
                directories.append((path, 0))
        except OSError:
            return unsafe(path, "Project directory links cannot be completely inspected")
        return None

    while repositories:
        repository = repositories.pop()
        if repository in repositories_seen:
            continue
        repositories_seen.add(repository)
        if repository != project_root:
            error = inspect(repository, enqueue_directory=False)
            if error:
                return error
            # Initialized submodules have their own Git index; inspect that
            # instead of recursively walking their ordinary tracked sources.
        commands = (
            ["git", "ls-files", "--cached", "--stage", "--others", "--directory", "--exclude-standard", "-z"],
            ["git", "ls-files", "--modified", "-z"],
            ["git", "ls-files", "--others", "--ignored", "--directory", "--exclude-standard", "-z"],
        )
        for command in commands:
            try:
                result = subprocess.run(command,
                                        cwd=repository,
                                        capture_output=True,
                                        check=False,
                                        text=True,
                                        encoding="utf-8",
                                        errors="surrogateescape")
            except OSError:
                return unsafe(repository, "Project directory links cannot be completely inspected")
            if result.returncode != 0:
                # Non-Git workspaces retain a bounded filesystem fallback.
                directories.append((repository, 0))
                break
            for record in result.stdout.split("\0"):
                if not record:
                    continue
                stage, separator, relative_path = record.partition("\t")
                fields = stage.split(" ")
                indexed = separator and len(fields) == 3 and fields[0] in ("100644", "100755", "120000", "160000")
                if indexed:
                    if fields[0] in ("100644", "100755"):
                        continue
                    path = os.path.join(repository, relative_path)
                    if fields[0] == "160000":
                        repositories.append(path)
                        continue
                else:
                    path = os.path.join(repository, record.rstrip("/"))
                error = inspect(path)
                if error:
                    return error

    visited = set()
    while directories:
        directory, depth = directories.pop()
        directory = os.path.abspath(directory)
        if directory in visited or excluded(directory):
            continue
        visited.add(directory)
        if depth > MAX_DEPTH:
            return unsafe(directory, "Project directory link inspection depth limit exceeded")
        try:
            with os.scandir(directory) as children:
                for entry in children:
                    if excluded(entry.path):
                        continue
                    inspected += 1
                    if inspected > MAX_ENTRIES:
                        return unsafe(directory, "Project directory link inspection limit exceeded")
                    if (entry.is_symlink() or entry.is_dir(follow_symlinks=False)) and directory_link(
                            entry.stat(follow_symlinks=False)) and entry.is_dir():
                        return unsafe(entry.path,
                                      "Project directory symlink or junction requires fresh Bazel discovery")
                    if entry.is_dir(follow_symlinks=False):
                        directories.append((entry.path, depth + 1))
        except OSError:
            return unsafe(directory, "Project directory links cannot be completely inspected")
    return None


def _symbol(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _literal_string(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def external_metadata(project_root, project_paths):
    paths = set()
    reasons = []
    repositories = {}
    parsed = []

    def unsafe(path, detail):
        reasons.append({"kind": "incomplete_dependency_provenance", "path": path, "detail": detail})

    def parse(path, external=False):
        name = os.path.basename(path)
        if not (name.startswith("BUILD") or name.endswith(".bzl")
                or name in ("WORKSPACE", "WORKSPACE.bazel", "MODULE.bazel")):
            if name not in (".bazelversion", ".bazelignore", ".gitmodules", "MODULE.bazel.lock"):
                try:
                    with open(path, encoding="utf-8") as stream:
                        source = stream.read(MAX_FILE_BYTES + 1)
                        if len(source) > MAX_FILE_BYTES:
                            unsafe(path, "Bazel configuration exceeds the bounded parser size")
                        elif "--override_repository" in source:
                            unsafe(path, "Repository overrides require fresh Bazel discovery")
                except FileNotFoundError:
                    pass
                except (OSError, UnicodeError):
                    unsafe(path, "Cannot inspect Bazel configuration")
            return
        try:
            with open(path, encoding="utf-8") as stream:
                source = stream.read(MAX_FILE_BYTES + 1)
            if len(source) > MAX_FILE_BYTES:
                unsafe(path, "Metadata exceeds the bounded parser size")
                return
            tree = ast.parse(source, filename=path)
        except (OSError, UnicodeError, SyntaxError, RecursionError) as exc:
            unsafe(path, "Cannot inspect metadata ({})".format(type(exc).__name__))
            return
        parsed.append((path, tree, external))
        workspace = name in ("WORKSPACE", "WORKSPACE.bazel")
        top_calls = {
            id(node.value)
            for node in tree.body if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
        }
        for node in ast.walk(tree):
            if workspace and isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id in LOCAL_RULES:
                unsafe(path, "Repository builtin is rebound in the workspace")
            if not isinstance(node, ast.Call):
                continue
            call = node.func
            direct = isinstance(call, ast.Name) or (isinstance(call, ast.Attribute)
                                                    and isinstance(call.value, ast.Name) and call.value.id == "native")
            function = _symbol(call)
            if workspace and function == "load":
                bindings = [_literal_string(argument) for argument in node.args[1:]]
                bindings.extend(keyword.arg for keyword in node.keywords)
                if LOCAL_RULES.intersection(bindings):
                    unsafe(path, "Loaded repository symbol is not a proven native builtin")
            if function in LOCAL_RULES:
                keywords = {keyword.arg: keyword.value for keyword in node.keywords}
                repo_name = _literal_string(keywords.get("name"))
                repo_path = _literal_string(keywords.get("path"))
                declaration_is_direct = workspace and not external and id(node) in top_calls and direct
                attributes_are_literal = repo_name and repo_path is not None and None not in keywords and "repo_mapping" not in keywords
                if not declaration_is_direct or not attributes_are_literal:
                    unsafe(path, "Local repository declaration is not directly resolvable")
                    continue
                resolved = os.path.realpath(os.path.join(project_root, repo_path))
                if repo_name in repositories and repositories[repo_name] != resolved:
                    unsafe(path, "Ambiguous local repository name")
                repositories[repo_name] = resolved
                if function == "new_local_repository":
                    # Injected BUILD content can itself load metadata outside
                    # the source root. Do not infer its dependency closure.
                    unsafe(path, "Injected repository BUILD inputs require fresh Bazel discovery")
            elif workspace and function not in ("load", "workspace"):
                unsafe(path, "Workspace macro or repository rule requires fresh Bazel discovery")
            elif function in ("repository_rule", "module_extension", "glob"):
                unsafe(path, "Dynamic repository or glob inputs require fresh Bazel discovery")
            for argument in list(node.args) + [keyword.value for keyword in node.keywords]:
                if _symbol(argument) in LOCAL_RULES:
                    unsafe(path, "Wrapped repository declaration requires fresh Bazel discovery")
        if name == "MODULE.bazel" and source.strip():
            unsafe(path, "Module repository provenance requires fresh Bazel discovery")

    for path in project_paths:
        parse(path)

    if reasons:
        # No amount of source-tree scanning can prove a dynamic declaration.
        return [], reasons[0]

    entries = 0
    visited = set()
    for repo_root in sorted(set(repositories.values())):
        pending = [(repo_root, 0)]
        while pending:
            directory, depth = pending.pop()
            real = os.path.realpath(directory)
            if real in visited:
                continue
            visited.add(real)
            if depth > MAX_DEPTH:
                unsafe(directory, "External metadata directory depth limit exceeded")
                break
            try:
                with os.scandir(directory) as children:
                    for entry in children:
                        entries += 1
                        if entries > MAX_ENTRIES:
                            unsafe(directory, "External metadata entry limit exceeded")
                            return sorted(paths), reasons[0]
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name not in (".git", ".simmer"):
                                pending.append((entry.path, depth + 1))
                        elif entry.is_symlink() and entry.is_dir():
                            unsafe(entry.path, "External directory symlink requires fresh Bazel discovery")
                        elif entry.name.startswith("BUILD") or entry.name.endswith(".bzl") or entry.name in (
                                "WORKSPACE", "WORKSPACE.bazel", "MODULE.bazel"):
                            paths.add(entry.path)
                            if len(paths) > MAX_METADATA:
                                unsafe(directory, "External metadata file limit exceeded")
                                return sorted(paths), reasons[0]
                            parse(entry.path, external=True)
            except OSError:
                unsafe(directory, "External repository cannot be completely inspected")

    for path, tree, external in parsed:
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value,
                                                             str) and node.value.startswith("@") and "//" in node.value:
                repository = node.value.split("//", 1)[0][1:]
                if external or repository not in repositories:
                    unsafe(path, "External label has no proven local repository provenance")
    return sorted(paths), reasons[0] if reasons else None
