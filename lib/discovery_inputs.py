"""Bounded, fail-closed provenance for mutable external discovery metadata.

This is not a Starlark evaluator. Only direct, literal native local repository
declarations are proven here. Macros, repository rules, overrides and unknown
external labels fall back to Bazel discovery instead of guessing their inputs.
"""

import ast
import os

MAX_ENTRIES = 50000
MAX_METADATA = 4096
MAX_DEPTH = 32
MAX_FILE_BYTES = 4 * 1024 * 1024
LOCAL_RULES = {"local_repository", "new_local_repository"}


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
                        if "--override_repository" in stream.read(MAX_FILE_BYTES + 1):
                            unsafe(path, "Repository overrides require fresh Bazel discovery")
                except (OSError, UnicodeError):
                    pass
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
            if not isinstance(node, ast.Call):
                continue
            call = node.func
            direct = isinstance(call, ast.Name) or (isinstance(call, ast.Attribute)
                                                    and isinstance(call.value, ast.Name) and call.value.id == "native")
            function = call.id if isinstance(call, ast.Name) else call.attr if isinstance(call, ast.Attribute) else ""
            if function in LOCAL_RULES:
                keywords = {keyword.arg: keyword.value for keyword in node.keywords}
                literal = lambda key: keywords.get(key).value if isinstance(keywords.get(
                    key), ast.Constant) and isinstance(keywords[key].value, str) else None
                repo_name, repo_path = literal("name"), literal("path")
                if external or not workspace or id(
                        node
                ) not in top_calls or not direct or not repo_name or repo_path is None or None in keywords or "repo_mapping" in keywords:
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
                reference = argument.id if isinstance(
                    argument, ast.Name) else argument.attr if isinstance(argument, ast.Attribute) else ""
                if reference in LOCAL_RULES:
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
                            if entry.name not in (".git", ".simmer") and not entry.name.startswith("bazel-"):
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
