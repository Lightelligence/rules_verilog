CUSTOM_SHELL = "custom"

VerilogLibFiles = provider(fields = {
    "transitive_sources": "Source files",
    "transitive_flists": "Generated or built flists",
    "transitive_dpi": "Shared libraries to link in via dpi",
    "last_module" : "Last module specified is assumed top",
})

RTLLibProvider = provider(fields = {
    "is_pkg" : "Indicates if this rtl_lib used the rtl_pkg rule",
    "is_shell_of" : "Indicates if this rtl_lib represents a shell module",
    "gumi_path" : "Short path to gumi file",
})

def gather_shell_defines(shells):
    defines = {}
    for shell in shells:
        if RTLLibProvider not in shell:
            fail("Not a shell: {}".format(shell))
        if not shell[RTLLibProvider].is_shell_of:
            fail("Not a shell: {}".format(shell))
        if shell[RTLLibProvider].is_shell_of == CUSTOM_SHELL:
            # Don't create a shell define for this shell because it has custom setup
            # Usually used when control over per instance shells is desired
            continue
        # implied from label name. this could be more explicit
        defines["gumi_" + shell[RTLLibProvider].is_shell_of] = "={}".format(shell.label.name)
        defines["gumi_use_{}".format(shell.label.name)] = ""
    return defines


def get_transitive_srcs(srcs, deps, provider, attr_name, allow_other_outputs = False):
    """Obtain the source files for a target and its transitive dependencies.

    Args:
      srcs: a list of source files
      deps: a list of targets that are direct dependencies
    Returns:
      a collection of the transitive sources
    """
    trans = []
    for dep in deps:
        if provider in dep:
            trans.append(getattr(dep[provider], attr_name))
        elif allow_other_outputs:
            trans.append(dep[DefaultInfo].files)

    return depset(
        srcs,
        transitive = trans,
    )

def flists_to_arguments(deps, provider, field, prefix, separator = ""):
    trans = []
    for dep in deps:
        if provider in dep:
            trans.extend(getattr(dep[provider], field).to_list())

        # else:
        #     trans.extend(dep[DefaultInfo].files.to_list())

    #return "".join([" -f {}".format(flist.path) for flist in trans])
    trans_depset = depset(trans)
    trans = trans_depset.to_list()

    return separator.join([" {} {}".format(prefix, flist.short_path) for flist in trans])


def _verilog_test_impl(ctx):
    trans_srcs = get_transitive_srcs([], ctx.attr.shells + ctx.attr.deps, VerilogLibFiles, "transitive_sources")
    srcs_list = trans_srcs.to_list()
    flists = get_transitive_srcs([], ctx.attr.shells + ctx.attr.deps, VerilogLibFiles, "transitive_flists")
    flists_list = flists.to_list()

    content = []

    if ctx.attr.tool:
        content.append(ctx.attr.tool[DefaultInfo].files_to_run.executable.short_path)
    
    flists_args = ["-f {}".format(f.short_path) for f in flists_list]
    content += ctx.attr.pre_flist_args

    for key, value in gather_shell_defines(ctx.attr.shells).items():
        content.append("  +define+{}{}".format(key, value))

    content += flists_args
    for dep in ctx.attr.deps:
        if VerilogLibFiles in dep and dep[VerilogLibFiles].last_module:
            content.append(dep[VerilogLibFiles].last_module.short_path)
    content += ctx.attr.post_flist_args

    content = ctx.expand_location(" ".join(content), targets=ctx.attr.data)

    ctx.actions.write(
        output = ctx.outputs.out,
        content = content,
        is_executable = True,
    )
    
    if ctx.attr.tool:
        tool_runfiles = ctx.attr.tool[DefaultInfo].data_runfiles.files
    else:
        tool_runfiles = depset([])

    runfiles = ctx.runfiles(files = flists_list + srcs_list + ctx.files.data, transitive_files=tool_runfiles)
    # runfiles = ctx.runfiles(files = flists_list + srcs_list)
    return [DefaultInfo(
        runfiles = runfiles,
        executable = ctx.outputs.out,
    )]

verilog_test = rule(
    doc = """Provides a way to run a test against a set of libs.""",
    implementation = _verilog_test_impl,
    attrs = {
        "deps": attr.label_list(mandatory = True),
        "pre_flist_args" : attr.string_list(doc = "commands and arguments before flist arguments"),
        "post_flist_args" : attr.string_list(doc = "commands and arguments after flist arguments"),
        "shells" : attr.label_list(),
        "data" : attr.label_list(
            allow_files = True,
            doc = "None-verilog dependencies"
        ),
        "tool" : attr.label(doc = "Label to a single tool to run. Inserted at before pre_flist_args if set. Do not duplicate in pre_flist_args"),
    },
    outputs = {"out": "%{name}_run.sh"},
    test = True,
)
