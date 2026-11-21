"""Shared VCS dependency content indices; actions are requested only by VCS TBs."""

load(":verilog.bzl", "VerilogInfo", "runfiles_relative_short_path", "verilog_input_manifest")

VcsInputIndexInfo = provider("Shared VCS compile input hashes.", fields = {
    "index": "Content hashes keyed by execution path for this target.",
    "indices": "Depset of content hash index files covering this target and its transitive dependencies.",
})

def _source_manifest_entry(file):
    return "source\t{}\t{}".format(runfiles_relative_short_path(file), file.path)

def _filelist_manifest_entry(file):
    return "filelist\t{}\t{}".format(runfiles_relative_short_path(file), file.path)

def _vcs_input_index_impl(target, ctx):
    child_index_depsets = []
    for name in ["deps", "shells"]:
        if ctx.rule and hasattr(ctx.rule.attr, name):
            deps = getattr(ctx.rule.attr, name)
            if type(deps) != "list":
                deps = [deps]
            for dep in deps:
                if type(dep) == "Target" and VcsInputIndexInfo in dep:
                    child_index_depsets.append(dep[VcsInputIndexInfo].indices)

    manifest_file = ctx.actions.declare_file(ctx.label.name + "_vcs_input_index_manifest.txt")
    index = ctx.actions.declare_file(ctx.label.name + "_vcs_input_index.json")

    if (VerilogInfo in target and
        hasattr(target[VerilogInfo], "direct_sources") and
        hasattr(target[VerilogInfo], "direct_vcs_flists") and
        target[VerilogInfo].direct_sources != None and
        target[VerilogInfo].direct_vcs_flists != None):
        # Hash only this target's direct files so leaf edits never invalidate
        # ancestor library index actions or copy transitive JSON up the DAG.
        direct_sources = target[VerilogInfo].direct_sources
        direct_flists = target[VerilogInfo].direct_vcs_flists
        args = ctx.actions.args()
        args.set_param_file_format("multiline")
        args.add_all(direct_sources, map_each = _source_manifest_entry, expand_directories = False)
        args.add_all(direct_flists, map_each = _filelist_manifest_entry, expand_directories = False)
        ctx.actions.write(output = manifest_file, content = args)
        ctx.actions.run(
            executable = ctx.executable._compile_input_digest,
            arguments = ["--index", manifest_file.path, index.path],
            inputs = depset([manifest_file], transitive = [direct_sources, direct_flists]),
            outputs = [index],
            mnemonic = "VerilogInputIndex",
            progress_message = "Indexing shared VCS inputs for %{label}",
            use_default_shell_env = True,
        )
        return [VcsInputIndexInfo(index = index, indices = depset([index], transitive = child_index_depsets))]

    if VerilogInfo in target:
        manifest = verilog_input_manifest(
            ctx,
            [target],
            [],
            flist_field = "transitive_vcs_flists",
            fallback_field = "transitive_flists",
        )
    else:
        # Match allow_other_outputs source semantics for filegroups and custom
        # providers, without requiring VerilogInfo or inventing filelists.
        args = ctx.actions.args()
        args.set_param_file_format("multiline")
        args.add_all(target[DefaultInfo].files, map_each = _source_manifest_entry, expand_directories = False)
        manifest = struct(args = args, files = target[DefaultInfo].files)
    indices = depset(transitive = child_index_depsets)
    index_list = ctx.actions.declare_file(ctx.label.name + "_vcs_child_input_indices.txt")
    index_args = ctx.actions.args()
    index_args.set_param_file_format("multiline")
    index_args.add_all(indices)
    ctx.actions.write(output = index_list, content = index_args)
    ctx.actions.write(output = manifest_file, content = manifest.args)
    ctx.actions.run(
        executable = ctx.executable._compile_input_digest,
        arguments = ["--index", manifest_file.path, index.path, index_list.path],
        inputs = depset([manifest_file, index_list], transitive = [manifest.files, indices]),
        outputs = [index],
        mnemonic = "VerilogInputIndex",
        progress_message = "Indexing shared VCS inputs for %{label}",
        use_default_shell_env = True,
    )
    return [VcsInputIndexInfo(index = index, indices = depset([index], transitive = child_index_depsets))]

vcs_input_index = aspect(
    implementation = _vcs_input_index_impl,
    attr_aspects = ["deps", "shells"],
    attrs = {
        "_compile_input_digest": attr.label(
            default = Label("@rules_verilog//verilog/private:compile_input_digest"),
            executable = True,
            cfg = "exec",
        ),
    },
)
