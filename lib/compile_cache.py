"""Fingerprint simulator builds before allowing --no-compile reuse."""

import hashlib
import json
import os
import re
import shlex
import tempfile

FINGERPRINT_FILE = ".compile_fingerprint.json"


class CompileDirectoryLock:
    """Advisory lock held while validating or updating a compile directory."""

    def __init__(self, path):
        self.path = os.path.abspath(os.fspath(path))
        self._filep = None

    def acquire(self, blocking=True):
        if self._filep is not None:
            return True

        import fcntl

        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        filep = open(self.path, "a+", encoding="utf-8")
        operation = fcntl.LOCK_EX
        if not blocking:
            operation |= fcntl.LOCK_NB
        try:
            fcntl.flock(filep, operation)
        except BlockingIOError:
            filep.close()
            return False
        except BaseException:
            filep.close()
            raise
        self._filep = filep
        return True

    def release(self):
        if self._filep is None:
            return

        import fcntl

        try:
            fcntl.flock(self._filep, fcntl.LOCK_UN)
        finally:
            self._filep.close()
            self._filep = None


def _digest_bytes(*values):
    digest = hashlib.sha256()
    for value in values:
        digest.update(value)
        digest.update(b"\0")
    return digest.hexdigest()


def _file_bytes(path):
    try:
        with open(path, "rb") as filep:
            return filep.read()
    except OSError:
        return b"<missing>"


def _compile_inputs_digest(compile_inputs_path, runfiles_root, expected_digest=None):
    if not compile_inputs_path:
        return None

    digest = hashlib.sha256()
    shared_digest = hashlib.sha256(b"rules_verilog.compile_inputs.v2\0") if expected_digest else None
    with open(compile_inputs_path, "r", encoding="utf-8") as filep:
        for line in filep:
            entry = line.rstrip("\n")
            _, separator, relative_path = entry.partition("\t")
            if not separator:
                raise RuntimeError("Malformed compile input inventory entry: {!r}".format(entry))
            input_path = os.path.join(runfiles_root, relative_path)
            if not os.path.isfile(input_path):
                raise RuntimeError("Compile input inventory references missing file: {}".format(input_path))
            digest.update(entry.encode("utf-8"))
            digest.update(b"\0")
            content_digest = hashlib.sha256() if shared_digest is not None else None
            with open(input_path, "rb") as input_file:
                for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
                    digest.update(chunk)
                    if content_digest is not None:
                        content_digest.update(chunk)
            digest.update(b"\0")
            if shared_digest is not None:
                shared_digest.update(entry.encode("utf-8") + b"\0")
                shared_digest.update(content_digest.digest() + b"\0")
    # Bazel has emitted both legacy raw-byte and shared per-file digests. Retain
    # its format only after validating it against current source bytes; a stale
    # or unknown digest falls back to the freshly computed legacy identity.
    if shared_digest is not None and expected_digest == shared_digest.hexdigest():
        return expected_digest
    return digest.hexdigest()


def _compile_inputs_manifest_digest(compile_inputs_path):
    digest = hashlib.sha256()
    with open(compile_inputs_path, "r", encoding="utf-8") as filep:
        for line in filep:
            entry = line.rstrip("\n")
            if "\t" not in entry:
                raise RuntimeError("Malformed compile input inventory entry: {!r}".format(entry))
            digest.update(entry.encode("utf-8"))
            digest.update(b"\0")
    return digest.hexdigest()


def _read_compile_inputs_digest(path):
    try:
        with open(path, "r", encoding="ascii") as filep:
            digest = filep.read().strip()
    except OSError as exc:
        raise RuntimeError("Cannot read Bazel compile input digest '{}': {}".format(path, exc)) from exc
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise RuntimeError("Malformed Bazel compile input digest '{}': {!r}".format(path, digest))
    return digest


def _extra_input_digests(paths):
    path_digest = hashlib.sha256()
    content_digests = []
    for path in sorted(os.path.abspath(os.fspath(path)) for path in paths if path):
        path_digest.update(path.encode("utf-8"))
        path_digest.update(b"\0")
        before_content = path_digest.copy()
        content_digest = hashlib.sha256()
        try:
            with open(path, "rb") as filep:
                for chunk in iter(lambda: filep.read(1024 * 1024), b""):
                    path_digest.update(chunk)
                    content_digest.update(chunk)
        except OSError:
            # Preserve the previous identity for absent/unreadable inputs.
            path_digest = before_content
            content_digest = hashlib.sha256()
            path_digest.update(b"<missing>")
            content_digest.update(b"<missing>")
        path_digest.update(b"\0")
        content_digest.update(b"\0")
        content_digests.append(content_digest.hexdigest())
    content_digest = _digest_bytes(*(digest.encode("ascii") for digest in sorted(content_digests)))
    return path_digest.hexdigest(), content_digest


def _directory_inputs(path):
    for root, dirs, files in os.walk(path):
        dirs.sort()
        for filename in sorted(files):
            yield os.path.join(root, filename)


def discover_filelist_inputs(filelist_path, working_directory):
    """Return existing files and include/library directory contents referenced by a simulator filelist."""
    if not filelist_path:
        return []

    working_directory = os.path.abspath(working_directory)
    root_filelist = os.path.abspath(filelist_path)
    discovered = set()
    parsed_filelists = set()
    pending = [(root_filelist, working_directory)]
    source_paths = set()
    include_directories = set()
    compiler_include_directories = set()
    directory_contents = {}

    def directory_inputs(path):
        # Cache only this discovery: the next invocation must see edits and
        # newly created headers, including files with arbitrary extensions.
        key = os.path.abspath(path)
        if key not in directory_contents:
            directory_contents[key] = tuple(_directory_inputs(path))
        return directory_contents[key]

    def unquote(value):
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            return value[1:-1]
        return value

    def resolve(path, base_directory):
        expanded = os.path.expanduser(os.path.expandvars(unquote(path)))
        return os.path.abspath(expanded if os.path.isabs(expanded) else os.path.join(base_directory, expanded))

    def add_path(path, base_directory, include_directory=False):
        resolved = resolve(path, base_directory)
        if os.path.isfile(resolved):
            discovered.add(resolved)
        elif include_directory and os.path.isdir(resolved):
            discovered.update(directory_inputs(resolved))
        return resolved

    def tokenize(text):
        lexer = shlex.shlex(text, posix=True)
        lexer.whitespace_split = True
        if os.name == "nt":
            lexer.escape = ""
        return list(lexer)

    def add_compiler_include_directories(flags, relative_base):
        try:
            arguments = tokenize(flags)
        except ValueError:
            return
        index = 0
        while index < len(arguments):
            argument = arguments[index]
            if argument == "-I" and index + 1 < len(arguments):
                index += 1
                compiler_include_directories.add(resolve(arguments[index], relative_base))
            elif argument.startswith("-I") and len(argument) > 2:
                compiler_include_directories.add(resolve(argument[2:], relative_base))
            index += 1

    while pending:
        current_filelist, relative_base = pending.pop()
        context = (current_filelist, relative_base)
        if context in parsed_filelists:
            continue
        parsed_filelists.add(context)
        if not os.path.isfile(current_filelist):
            continue
        discovered.add(current_filelist)
        try:
            with open(current_filelist, "r", encoding="utf-8", errors="surrogateescape") as filep:
                # Simulator filelists are usually POSIX shell syntax, but the
                # library is also exercised on Windows where drive-letter
                # paths contain backslashes. Default POSIX escaping turns e.g.
                # ``C:\\work\\dut.sv`` into ``C:workdut.sv``.  Preserve
                # native Windows paths without losing quotes inside attached
                # options; retain POSIX escaping on licensed Linux hosts.
                tokens = tokenize(filep.read())
        except ValueError:
            continue

        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token in ("-o", "-l") and index + 1 < len(tokens):
                index += 2
                continue
            if token in ("-f", "-file", "-F") and index + 1 < len(tokens):
                nested = add_path(tokens[index + 1], relative_base)
                contents_base = os.path.dirname(nested) if token == "-F" else relative_base
                pending.append((nested, contents_base))
                index += 2
                continue
            option, separator, value = token.partition("=")
            if token == "-CFLAGS" and index + 1 < len(tokens):
                add_compiler_include_directories(tokens[index + 1], relative_base)
                index += 2
                continue
            if separator and option == "-CFLAGS":
                add_compiler_include_directories(value, relative_base)
                index += 1
                continue
            if separator and option in ("-f", "-file", "-F"):
                nested = add_path(value, relative_base)
                contents_base = os.path.dirname(nested) if option == "-F" else relative_base
                pending.append((nested, contents_base))
                index += 1
                continue
            # Only input-file switches: output options such as -o=simv must
            # never make the previous build part of its own fingerprint.
            if separator and option in ("-xprop", "-gfile", "-cm_hier", "-libmap"):
                add_path(value, relative_base)
                index += 1
                continue
            if token.startswith("+optconfigfile+"):
                add_path(token[len("+optconfigfile+"):], relative_base)
                index += 1
                continue
            if token.startswith("+incdir+"):
                for directory in token[len("+incdir+"):].split("+"):
                    if directory:
                        include_directories.add(add_path(directory, relative_base, include_directory=True))
                index += 1
                continue
            if token == "-incdir" and index + 1 < len(tokens):
                include_directories.add(add_path(tokens[index + 1], relative_base, include_directory=True))
                index += 2
                continue
            if token in ("-v", "-y") and index + 1 < len(tokens):
                path = add_path(tokens[index + 1], relative_base, include_directory=(token == "-y"))
                if token == "-v":
                    source_paths.add(path)
                elif os.path.isdir(path):
                    source_paths.update(directory_inputs(path))
                index += 2
                continue
            if not token.startswith(("-", "+")):
                source_paths.add(add_path(token, relative_base))
            index += 1

    # Follow literal includes even when a custom source/header lives outside
    # every +incdir. Keep all existing candidates conservatively: simulator
    # search ordering may vary, but changing any candidate must not allow stale
    # reuse. Macro-generated include names still require declared input files
    # or explicit include-directory inventories.
    include_tokens = re.compile(
        r'//[^\r\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|(?:`include|\#\s*include)(?:\s|/\*.*?\*/)*"([^"\r\n]+)"'
        r'|\#\s*include(?:\s|/\*.*?\*/)*<([^>\r\n]+)>', re.DOTALL)
    pending_sources = list(source_paths)
    parsed_sources = set()
    while pending_sources:
        source_path = pending_sources.pop()
        if source_path in parsed_sources or not os.path.isfile(source_path):
            continue
        parsed_sources.add(source_path)
        with open(source_path, "r", encoding="utf-8", errors="surrogateescape") as source_file:
            text = source_file.read()
        for match in include_tokens.finditer(text):
            quoted_header, angle_header = match.groups()
            if quoted_header is None and angle_header is None:
                continue
            # Compiler include paths resolve named dependencies only. Walking
            # them recursively would inventory unrelated SDK/system headers.
            bases = compiler_include_directories
            if quoted_header is not None:
                bases = bases | include_directories | {os.path.dirname(source_path), working_directory}
            for base in sorted(bases):
                header = add_path(quoted_header or angle_header, base)
                if os.path.isfile(header):
                    pending_sources.append(header)

    return sorted(discovered)


def normalize_compile_script_paths(compile_script, path_replacements):
    """Replace host-specific absolute paths with stable fingerprint tokens."""
    normalized = compile_script
    replacements = ((os.path.abspath(os.fspath(path)), "<{}>".format(name)) for name, path in path_replacements.items()
                    if path)
    for path, token in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        normalized = normalized.replace(path, token)
    return normalized


def compile_fingerprint(project_dir,
                        compile_script,
                        compile_args_path,
                        compile_inputs_path=None,
                        runfiles_root=None,
                        compile_inputs_digest_path=None,
                        extra_input_paths=(),
                        environment=None,
                        verify_compile_inputs_digest=False):
    """Return the source, generated filelist and compile-mode identity."""
    fingerprint = {
        "schema_version": 7,
        "compile_script_sha256": _digest_bytes(compile_script.encode("utf-8")),
        "compile_args_sha256": _digest_bytes(_file_bytes(compile_args_path)),
        "environment": dict(sorted((environment or {}).items())),
    }
    if compile_inputs_path:
        digest = _read_compile_inputs_digest(compile_inputs_digest_path) if compile_inputs_digest_path else None
        if verify_compile_inputs_digest or digest is None:
            digest = _compile_inputs_digest(compile_inputs_path, runfiles_root, expected_digest=digest)
        fingerprint["compile_inputs_sha256"] = digest
        fingerprint["compile_inputs_manifest_sha256"] = _compile_inputs_manifest_digest(compile_inputs_path)
    if extra_input_paths:
        extra_inputs_digest, extra_inputs_content_digest = _extra_input_digests(extra_input_paths)
        fingerprint["extra_inputs_sha256"] = extra_inputs_digest
        fingerprint["extra_inputs_content_sha256"] = extra_inputs_content_digest
    return fingerprint


def _fingerprint_path(job_dir):
    return os.path.join(job_dir, FINGERPRINT_FILE)


def write_compile_fingerprint(job_dir, fingerprint):
    os.makedirs(job_dir, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(prefix=".compile-fingerprint-", dir=job_dir, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as filep:
            json.dump(fingerprint, filep, indent=2, sort_keys=True)
            filep.write("\n")
        os.replace(temporary_path, _fingerprint_path(job_dir))
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)


def invalidate_compile_fingerprint(job_dir):
    try:
        os.remove(_fingerprint_path(job_dir))
    except FileNotFoundError:
        pass


def _changed_fingerprint_fields(actual, expected, prefix=""):
    changed = []
    for key in sorted(set(actual) | set(expected)):
        field = "{}.{}".format(prefix, key) if prefix else key
        actual_value = actual.get(key)
        expected_value = expected.get(key)
        if isinstance(actual_value, dict) and isinstance(expected_value, dict):
            changed.extend(_changed_fingerprint_fields(actual_value, expected_value, field))
        elif actual_value != expected_value:
            changed.append(field)
    return changed


def validate_compile_fingerprint(job_dir, expected):
    path = _fingerprint_path(job_dir)
    if not os.path.isfile(path):
        raise RuntimeError("--no-compile requires {}. Recompile this testbench first.".format(path))
    with open(path, "r", encoding="utf-8") as filep:
        actual = json.load(filep)
    if actual != expected:
        changed = ", ".join(_changed_fingerprint_fields(actual, expected))
        raise RuntimeError("Compile build fingerprint mismatch in {} (changed: {}). Recompile this testbench.".format(
            job_dir, changed))


def can_reuse_compile(job_dir, expected, validate_artifacts):
    """Return an automatic cache decision without turning a miss into an error."""
    try:
        validate_artifacts()
        validate_compile_fingerprint(job_dir, expected)
    except (OSError, RuntimeError, ValueError) as exc:
        return False, str(exc)
    return True, None
