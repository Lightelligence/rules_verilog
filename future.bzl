"""This functions are works in progress and not yet ready for use"""

def _verilator_lint_impl(ctx):
    out = ctx.outputs.executable
    trans_srcs = get_transitive_srcs([], ctx.attr.deps, RTLLibFiles, "transitive_sources")
    srcs_list = trans_srcs.to_list()
    flists = get_transitive_srcs([], ctx.attr.deps, RTLLibFiles, "transitive_flists")
    flists_list = flists.to_list()

    script = "\n".join(
        ["verilator --lint-only --top-module {} {}".format(ctx.attr.top, " ".join(["-f {}".format(f.short_path) for f in flists_list]))],
    )

    ctx.actions.write(
        output = out,
        content = script,
    )

    runfiles = ctx.runfiles(files = flists_list + srcs_list)
    return [DefaultInfo(runfiles = runfiles)]

verilator_lint = rule(
    implementation = _verilator_lint_impl,
    attrs = {
        "deps": attr.label_list(),
        "top": attr.string(mandatory = True),
    },
    executable = True,
    doc = "Run verilator on an RTL library.",
)
