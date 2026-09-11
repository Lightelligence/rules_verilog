"""Shared VCS dependency content indices; actions are requested only by VCS TBs."""

load(":verilog.bzl", "verilog_input_manifest")

VcsInputIndexInfo = provider("Shared VCS compile input hashes.", fields = {"index": "Content hashes keyed by execution path."})

def _vcs_input_index_impl(target, ctx):
    manifest = verilog_input_manifest(
        ctx,
        [target],
        [],
        flist_field = "transitive_vcs_flists",
        fallback_field = "transitive_flists",
    )
    manifest_file = ctx.actions.declare_file(ctx.label.name + "_vcs_input_index_manifest.txt")
    index = ctx.actions.declare_file(ctx.label.name + "_vcs_input_index.json")
    ctx.actions.write(output = manifest_file, content = manifest.args)
    ctx.actions.run(
        executable = ctx.executable._compile_input_digest,
        arguments = ["--index", manifest_file.path, index.path],
        inputs = depset([manifest_file], transitive = [manifest.files]),
        outputs = [index],
        mnemonic = "VerilogInputIndex",
        progress_message = "Indexing shared VCS inputs for %{label}",
        use_default_shell_env = True,
    )
    return [VcsInputIndexInfo(index = index)]

vcs_input_index = aspect(
    implementation = _vcs_input_index_impl,
    attrs = {
        "_compile_input_digest": attr.label(
            default = Label("@rules_verilog//verilog/private:compile_input_digest"),
            executable = True,
            cfg = "exec",
        ),
    },
)
