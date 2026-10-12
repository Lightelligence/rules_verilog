"""Coverage lineage and recoverable publication for incremental URG merges."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import uuid
from contextlib import contextmanager


def _digest_files(files):
    digest = hashlib.sha256()
    found = False
    for name, path in sorted(files):
        found = True
        digest.update(os.fsencode(name) + b"\0")
        with path.open("rb") as stream:
            digest.update(hashlib.file_digest(stream, "sha256").digest())
    return digest.hexdigest() if found else None


def _walk(root, ancestors=frozenset(), metadata=None):
    # Reuse the directory entry's followed stat result. Resolving every path
    # and calling both is_dir/is_file repeats metadata requests on EDA storage.
    metadata = metadata if metadata is not None else root.stat()
    if not metadata.st_ino:
        # Windows DirEntry.stat may omit inode numbers; os.stat supplies them.
        metadata = root.stat()
    identity = ((metadata.st_dev,
                 metadata.st_ino) if metadata.st_ino else os.path.normcase(str(root.resolve(strict=True))))
    if identity in ancestors:
        raise OSError("Cyclic coverage directory: {}".format(root))
    ancestors = ancestors | {identity}
    with os.scandir(root) as entries:
        children = sorted(entries, key=lambda entry: entry.name)
    for entry in children:
        path = root / entry.name
        metadata = entry.stat(follow_symlinks=True)
        if stat.S_ISDIR(metadata.st_mode):
            yield path, None
            if path.parts[-4:] != ("snps", "coverage", "db", "testdata"):
                yield from _walk(path, ancestors, metadata)
        elif stat.S_ISREG(metadata.st_mode):
            yield None, path
        else:
            raise OSError("Unreadable coverage entry: {}".format(path))


def model_digest(database):
    """Fingerprint static design/shape files, including partition models.

    URG adds design.cv.xml to merged databases. Common/testdata files contain
    runtime information and are not static compilation-model identities.
    """
    root = Path(database)
    if not root.is_dir():
        return None
    files = []
    for _directory, path in _walk(root):
        if path is None or path.name == "design.cv.xml":
            continue
        parts = path.relative_to(root).parts
        if any(parts[index:index + 4] in (("snps", "coverage", "db", "design"), ("snps", "coverage", "db", "shape"))
               for index in range(len(parts) - 3)):
            files.append((str(path.relative_to(root)), path))
    return _digest_files(files)


def datasets(database):
    """Hash current input datasets only; never reopen historical case VDBs."""
    root = Path(database)
    main = root / "snps/coverage/db/testdata"
    if not main.is_dir():
        return None
    names = sorted(entry.name for entry in main.iterdir() if entry.is_dir())
    files = {name: [] for name in names}
    for directory, _path in _walk(root):
        if directory is None or directory.parts[-4:] != ("snps", "coverage", "db", "testdata"):
            continue
        for name in names:
            case = directory / name
            if not case.is_dir():
                continue
            for _subdir, path in _walk(case):
                if path is not None:
                    files[name].append((str(path.relative_to(root)), path))
    result = {name: _digest_files(entries) for name, entries in files.items()}
    if any(value is None for value in result.values()):
        raise OSError("Coverage input contains an empty test dataset")
    return result


def history_path(job):
    return getattr(job, "coverage_history_path", job.merged_coverage_dir + ".simmer.json")


def write_json(path, value):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = stream.name
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.lexists(temporary):
            os.unlink(temporary)


def make_history(job, signature):
    if not (Path(job.cov_work_dir) / "snps/coverage/db/design").is_dir():
        return None
    records = datasets(job.cov_work_dir)
    if records is None:
        return None
    model = model_digest(job.cov_work_dir)
    if model is None:
        return None
    return {
        "schema_version": 1,
        "bench": job.name,
        "generation": uuid.uuid4().hex,
        "previous_generation": None,
        "model_sha256": model,
        "coverage_options": signature,
        "datasets": records,
        "added_tests": sorted(records),
        "merge_mode": "full",
    }


@contextmanager
def merge_lock(directory, name):
    identity = hashlib.sha256(name.encode()).hexdigest()[:24]
    with open(Path(directory) / (".vcs-coverage-" + identity + ".lock"), "a+b") as stream:
        if os.name == "nt":
            import msvcrt
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise OSError("Coverage update is already active for {}".format(name)) from exc
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise OSError("Coverage update is already active for {}".format(name)) from exc
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def _remove(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _filtered_view(source, destination, selected, ancestors=frozenset()):
    resolved = source.resolve(strict=True)
    if resolved in ancestors:
        raise OSError("Cyclic coverage directory: {}".format(source))
    destination.mkdir()
    ancestors = ancestors | {resolved}
    testdata = source.parts[-4:] == ("snps", "coverage", "db", "testdata")
    for entry in sorted(source.iterdir()):
        if testdata and entry.name not in selected:
            continue
        target = destination / entry.name
        if entry.is_dir() and not testdata:
            _filtered_view(entry, target, selected, ancestors)
        else:
            # Absolute links also keep partition links valid after relocation.
            target.symlink_to(entry.resolve(strict=True), target_is_directory=entry.is_dir())


def _relocate_links(source, destination):
    """Preserve URG partition links when the validated staging VDB moves."""
    source = source.resolve()
    replacements = []
    for directory, subdirs, filenames in os.walk(source, followlinks=False):
        for name in subdirs + filenames:
            link = Path(directory) / name
            if not link.is_symlink():
                continue
            resolved = link.resolve(strict=True)
            target = destination / resolved.relative_to(source) if resolved.is_relative_to(source) else resolved
            is_directory = resolved.is_dir()
            replacements.append((link, target, is_directory))
    for link, target, is_directory in replacements:
        link.unlink()
        link.symlink_to(target, target_is_directory=is_directory)


class CoverageUpdate:
    """Keep the previous generation until all new outputs have validated.

    Call under merge_lock. The journal lets the next invocation roll back a
    process termination between individual directory/file renames.
    """

    def __init__(self, job, directory, signature):
        self.original = job
        self.directory = Path(directory).resolve()
        self.signature = signature
        self.job = copy.copy(job)
        self.stage = None
        self.reuse = False
        self.targets = [
            Path(job.merged_coverage_dir),
            Path(job.coverage_report_dir), self.directory / (job.name + "__run_coverage.sh"),
            Path(history_path(job))
        ]
        if any(target.parent.resolve() != self.directory for target in self.targets):
            raise OSError("Incremental coverage outputs must belong to the regression directory")
        self.prefix = ".vcs-coverage-" + hashlib.sha256(job.name.encode()).hexdigest()[:24] + "-"

    def _journal(self, stage):
        path = stage / "transaction.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        if (value.get("schema_version") != 1 or value.get("bench") != self.original.name
                or value.get("targets") != [str(target) for target in self.targets]
                or value.get("phase") not in ("staging", "publishing", "committed", "rolled_back")
                or not isinstance(value.get("had_original"), list) or len(value["had_original"]) != 4
                or not all(type(item) is bool for item in value["had_original"])):
            raise OSError("Invalid coverage publication journal: {}".format(path))
        return value

    def _rollback(self, stage, journal):
        sources = [stage / name for name in ("merged.vdb", "report", "run_coverage.sh", "history.json")]
        for index in reversed(range(4)):
            backup = stage / ("backup-" + str(index))
            target = self.targets[index]
            if os.path.lexists(backup):
                _remove(target)
                os.replace(backup, target)
            elif not journal["had_original"][index] and not os.path.lexists(sources[index]):
                _remove(target)
        journal["phase"] = "rolled_back"
        write_json(stage / "transaction.json", journal)

    def _read_baseline(self, current):
        database, report, _viewer, history = self.targets
        if not database.is_dir():
            if any(os.path.lexists(path) for path in self.targets):
                raise OSError("Incomplete previous coverage generation; establish a full baseline")
            return None
        if model_digest(database) != current["model_sha256"]:
            raise OSError(
                "Coverage design/shape model changed; establish a full baseline instead of incrementally merging")
        if history.is_file():
            baseline = json.loads(history.read_text(encoding="utf-8"))
        else:
            # Upgrade the earlier compact-report format without remerging its
            # original VDBs. Unknown old hashes cannot authorize duplicate data.
            try:
                summary = json.loads((report / "summary.json").read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise OSError(
                    "Legacy coverage baseline needs valid summary.json provenance; establish a full baseline") from exc
            names = summary.get("input_tests")
            if (not isinstance(names, list) or not all(isinstance(name, str) for name in names)
                    or len(set(names)) != len(names)):
                raise OSError("Legacy coverage baseline lacks contributing-test provenance")
            baseline = dict(current,
                            bench=summary.get("bench"),
                            generation="legacy",
                            datasets={name: None
                                      for name in names})
        records = baseline.get("datasets")
        if (baseline.get("schema_version") != 1 or baseline.get("bench") != self.original.name
                or baseline.get("model_sha256") != current["model_sha256"]
                or baseline.get("coverage_options") != self.signature or not isinstance(records, dict)
                or not isinstance(baseline.get("generation"), str)
                or any(not isinstance(name, str) or not name or name in (".", "..") or any(
                    character in name for character in ("/", "\\", "\n", "\r", "\0")) or (digest is not None and (
                        not isinstance(digest, str) or len(digest) != 64 or any(character not in "0123456789abcdef"
                                                                                for character in digest)))
                       for name, digest in records.items())):
            raise OSError("Invalid or incompatible coverage history manifest")
        return baseline

    def __enter__(self):
        # Recover only journals for this exact bench and these fixed outputs.
        for stage in sorted(self.directory.glob(self.prefix + "*")):
            if stage.is_symlink() or not stage.is_dir():
                raise OSError("Unexpected coverage staging path: {}".format(stage))
            journal = self._journal(stage)
            if journal["phase"] == "publishing":
                self._rollback(stage, journal)
            shutil.rmtree(stage)
        current = make_history(self.original, self.signature)
        if current is None:
            raise OSError("Incremental coverage requires static models and named test datasets")
        self.current = current
        baseline = self._read_baseline(current)
        old = baseline["datasets"] if baseline else {}
        selected = {}
        for name, digest in current["datasets"].items():
            if name in old:
                if old[name] is None or old[name] != digest:
                    raise OSError(
                        "Coverage dataset {} is already merged and cannot be replaced incrementally".format(name))
            else:
                selected[name] = digest
        self.job.coverage_merge_metrics = {
            "added_dataset_count": len(selected),
            "duplicate_dataset_count": len(current["datasets"]) - len(selected)
        }
        if baseline and not selected:
            self.reuse = True
            return self
        self.stage = Path(tempfile.mkdtemp(prefix=self.prefix, dir=self.directory))
        journal = {
            "schema_version": 1,
            "bench": self.original.name,
            "targets": [str(target) for target in self.targets],
            "phase": "staging",
            "had_original": [os.path.lexists(target) for target in self.targets]
        }
        try:
            write_json(self.stage / "transaction.json", journal)
            input_database = Path(self.original.cov_work_dir)
            if selected and len(selected) != len(current["datasets"]):
                view = self.stage / "new-input.vdb"
                _filtered_view(input_database, view, set(selected))
                input_database = view
            self.job.coverage_input_vdbs = ([str(self.targets[0])] if baseline else []) + [str(input_database)]
            self.job.coverage_merge_script = str(self.stage / "merge.sh")
            self.job.coverage_merge_log = getattr(self.original, "coverage_merge_log",
                                                  os.path.splitext(self.original.coverage_merge_script)[0] + ".log")
            self.job.merged_coverage_dir = str(self.stage / "merged.vdb")
            self.job.coverage_report_dir = str(self.stage / "report")
            self.job.coverage_view_script_output_path = str(self.stage / "run_coverage.sh")
            self.job.coverage_history_path = str(self.stage / "history.json")
            self.job.coverage_published_merged_dir = str(self.targets[0])
            self.job.coverage_published_report_dir = str(self.targets[1])
            self.job.coverage_published_viewer_path = str(self.targets[2])
            self.job.coverage_history_data = dict(current,
                                                  datasets=dict(old, **selected),
                                                  added_tests=sorted(selected),
                                                  previous_generation=baseline["generation"] if baseline else None,
                                                  merge_mode="incremental" if baseline else "full")
            self.job.coverage_input_tests = sorted(self.job.coverage_history_data["datasets"])
            return self
        except BaseException:
            shutil.rmtree(self.stage)
            self.stage = None
            raise

    def publish(self):
        if (model_digest(self.original.cov_work_dir) != self.current["model_sha256"]
                or datasets(self.original.cov_work_dir) != self.current["datasets"]):
            raise OSError("Coverage input changed during the incremental merge")
        if model_digest(self.job.merged_coverage_dir) != self.current["model_sha256"]:
            raise OSError("URG changed the static coverage model during incremental merging")
        # Merge-only mode has no report; publish an empty report directory so a
        # previous generation's report cannot be mistaken for the new result.
        Path(self.job.coverage_report_dir).mkdir(exist_ok=True)
        _relocate_links(Path(self.job.merged_coverage_dir), self.targets[0])
        journal = self._journal(self.stage)
        journal["phase"] = "publishing"
        write_json(self.stage / "transaction.json", journal)
        sources = [self.stage / name for name in ("merged.vdb", "report", "run_coverage.sh", "history.json")]
        try:
            for index, (source, target) in enumerate(zip(sources, self.targets)):
                if os.path.lexists(target):
                    os.replace(target, self.stage / ("backup-" + str(index)))
                os.replace(source, target)
            journal["phase"] = "committed"
            write_json(self.stage / "transaction.json", journal)
        except BaseException:
            self._rollback(self.stage, journal)
            raise

    def __exit__(self, *_exception):
        if self.stage is not None:
            # Never delete the last valid outputs if rollback itself failed.
            journal = self._journal(self.stage)
            if journal["phase"] != "publishing":
                shutil.rmtree(self.stage)
