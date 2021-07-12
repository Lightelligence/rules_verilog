"""Rules to gather and compile RTL."""

load(":verilog.bzl", "CUSTOM_SHELL", "ShellInfo", "ToolEncapsulationInfo", "VerilogInfo", "gather_shell_defines", "get_transitive_srcs")

_SHELLS_DOC = """List of verilog_rtl_shell Labels.
For each Label, a gumi define will be placed on the command line to use this shell instead of the original module.
This requires that the original module was instantiated using \\`gumi_<module_name> instead of just <module_name>."""

def create_flist_content(ctx, gumi_path, allow_library_discovery, no_synth = False):
    """Create the content of a '.f' file.

    Args:
      gumi_path: The path to the dynamically created gumi file to include.

        The gumi file is put directly on the command line to ensure that the
        defines are always used.
      allow_library_discovery: When false, modules are placed directly on the command line.

        Preference is to use the -y (modules in this directory can be found by
        searching for a file with the same name) and -v (file is a library file
        containing multiple modules) flags. Some tools, e.g. Genus, do not
        handle -y correctly when invoked many times. As a workaround for these
        tools, setting allow_library_discovery to false will put all module
        files and library files directly onto the command line.
      no_synth: When true, filter any target that sets no_synth=True

        This is an extra precaution to ensure that nonsynthesizable libraries
        are not passed to the synthesis tool.

    Returns:
      List of strings representing flist content.
    """
    flist_content = []

    # Using dirname may result in bazel-out included in path
    incdir = depset([f.short_path[:-len(f.basename) - 1] for f in ctx.files.headers]).to_list()
    for d in incdir:
        flist_content.append("+incdir+{}".format(d))

    # Using dirname may result in bazel-out included in path
    libdir = depset([f.short_path[:-len(f.basename) - 1] for f in ctx.files.modules]).to_list()

    #if len(libdir):
    flist_content.append(gumi_path)

    if not no_synth:
        if allow_library_discovery:
            for d in libdir:
                if d == "":
                    d = "."
                flist_content.append("-y {}".format(d))
        else:
            flist_content += [f.short_path for f in ctx.files.modules]

        for f in ctx.files.lib_files:
            if allow_library_discovery:
                flist_content.append("-v {}".format(f.short_path))
            else:
                flist_content.append(f.short_path)

        for f in ctx.files.direct:
            flist_content.append(f.short_path)

    flist_content.append("")
    return flist_content

def _verilog_rtl_library_impl(ctx):
    srcs = ctx.files.headers + ctx.files.modules + ctx.files.lib_files + ctx.files.direct

    if ctx.attr.is_pkg:
        # FIXME opu_tx_rx is failing this check
        # for dep in ctx.attr.deps:
        #     if ShellInfo in dep and not dep[ShellInfo].is_pkg:
        #         fail("verilog_rtl_pkg may only depend on other verilog_rtl_pkg instances")
        pass
    else:
        for src in srcs:
            if "_pkg" in src.basename:
                fail("Package files should not declared in a verilog_rtl_library. Use a verilog_rtl_pkg instead. {} is declared in {}".format(src, ctx.label))

    if ctx.attr.is_shell_of:
        if len(ctx.attr.modules) != 1 and not ctx.attr.is_shell_of == CUSTOM_SHELL:
            fail("Shells must specify exactly one module")

        # if len(ctx.attr.deps) != 0:
        #     fail("Shells may not specify deps")

    else:
        for dep in ctx.attr.deps:
            if ShellInfo in dep and dep[ShellInfo].is_shell_of and not dep[ShellInfo].is_shell_of == CUSTOM_SHELL:
                fail("verilog_rtl_library may not depend on shells. Shells should only be included at top-level builds")
        for src in srcs:
            if "_shell" in src.basename:
                fail("Shell files should not be declared in an verilog_rtl_library. Use a verilog_rtl_shell instead. {} is declared in {}".format(src, ctx.label))

    gumi_path = ""
    if ctx.attr.enable_gumi:
        gumi = ctx.actions.declare_file("gumi_{name}.vh".format(name = ctx.attr.name))
        gumi_content = []

        # Making this more unique than just gumi.basename.upper()
        # To avoid case where multiple directories define the same name for a verilog_rtl_library
        gumi_guard_value = gumi.short_path.replace("/", "_").replace(".", "_")
        gumi_guard = "__{}__".format(gumi_guard_value.upper())
        gumi_content.append("`ifndef {}".format(gumi_guard))
        gumi_content.append("  `define {}".format(gumi_guard))
        gumi_content.append("")
        gumi_content.append("")
        if ctx.attr.gumi_override:
            gumi_modules = ctx.attr.gumi_override
        else:
            gumi_modules = [module.basename[:-len(module.extension) - 1] for module in ctx.files.modules]
        for module_name in gumi_modules:
            gumi_name = "gumi_{}".format(module_name)
            gumi_content.append("  `ifndef {}".format(gumi_name))
            gumi_content.append("    `define {} {}".format(gumi_name, module_name))
            gumi_content.append("  `endif")
            gumi_content.append("")
        gumi_content.append("")
        gumi_content.append("")
        gumi_content.append("`endif // guard")

        ctx.actions.write(
            output = gumi,
            content = "\n".join(gumi_content),
        )

        srcs = [gumi] + srcs
        gumi_path = gumi.short_path
    elif not (ctx.attr.gumi_file_override == None):
        gumi_path = ctx.file.gumi_file_override.short_path

    flist_content = create_flist_content(ctx, gumi_path = gumi_path, allow_library_discovery = True)

    last_module = None
    for m in ctx.files.modules:
        last_module = m
    for m in ctx.files.lib_files:
        last_module = m
    for m in ctx.files.direct:
        last_module = m

    ctx.actions.write(
        output = ctx.outputs.flist,
        content = "\n".join(flist_content),
    )

    trans_srcs = get_transitive_srcs(srcs, ctx.attr.deps, VerilogInfo, "transitive_sources", allow_other_outputs = True)
    trans_flists = get_transitive_srcs([ctx.outputs.flist], ctx.attr.deps, VerilogInfo, "transitive_flists", allow_other_outputs = False)

    trans_dpi = get_transitive_srcs([], ctx.attr.deps, VerilogInfo, "transitive_dpi", allow_other_outputs = False)

    runfiles_list = trans_srcs.to_list() + trans_flists.to_list() + trans_dpi.to_list()
    runfiles = ctx.runfiles(files = runfiles_list)

    all_files = depset(trans_srcs.to_list() + trans_flists.to_list())

    return [
        ShellInfo(
            is_pkg = ctx.attr.is_pkg,
            is_shell_of = ctx.attr.is_shell_of,
            gumi_path = gumi_path,
        ),
        VerilogInfo(
            transitive_sources = trans_srcs,
            transitive_flists = trans_flists,
            transitive_dpi = trans_dpi,
            last_module = last_module,
        ),
        DefaultInfo(
            files = all_files,
            runfiles = runfiles,
        ),
    ]

verilog_rtl_library = rule(
    doc = "A collection of RTL design files. Creates a generated flist file to be included later in a compile.",
    implementation = _verilog_rtl_library_impl,
    attrs = {
        "headers": attr.label_list(
            allow_files = True,
            doc = "Files that will be included into other files.\n" +
                  "A '+incdir' flag will be added for each source file's directory.",
        ),
        "modules": attr.label_list(
            allow_files = True,
            doc = "Verilog files containing a single module where the module name matches the file name.\n" +
                  "A '-y' flag will be added for each source file's directory.\n" +
                  "This is the preferred mechanism for specifying RTL modules.",
        ),
        "lib_files": attr.label_list(
            allow_files = True,
            doc = "Verilog library files containing multiple modules.\n" +
                  "A '-v' flag will be added for each file in this attribute.\n" +
                  "It is preferable to used the 'modules' attribute when possible because library files require parsing entire files to discover all modules.",
        ),
        "direct": attr.label_list(
            allow_files = True,
            doc = "Verilog files that must be put directly onto the command line.\n" +
                  "'modules' should be used instead of 'direct' wherever possible",
        ),
        "deps": attr.label_list(
            doc = "Other verilog libraries this target is dependent upon.\n" +
                  "All Labels specified here must provide a VerilogInfo provider.",
        ),
        "no_synth": attr.bool(
            default = False,
            doc = "When True, do not allow the contents of this library to be exposed to synthesis.\n" +
                  "TODO: This currently enforced via an Aspect which is not included in this repository.\n" +
                  "The aspect creates a parallel set of 'synth__*.f' which have the filtered views which are passed to the synthesis tool.",
        ),
        "is_pkg": attr.bool(
            default = False,
            doc = "INTERNAL: Do not set in verilog_rtl_library instances.\n" +
                  "Used for internal bookkeeping for macros derived from verilog_rtl_library.\n" +
                  "Used to enforce naming conventions related to packages to encourage simple dependency graphs",
        ),
        "is_shell_of": attr.string(
            default = "",
            doc = "INTERNAL: Do not set in verilog_rtl_library instances.\n" +
                  "Used for internal bookkeeping for macros derived from verilog_rtl_library.\n" +
                  "If set, this library is represents a 'shell' of another module.\n" +
                  "Allows downstream test rules to specify this Label as a 'shell' to override another instance via the gumi system.",
        ),
        "enable_gumi": attr.bool(
            default = True,
            doc = "When set, create an additional file creating default preprocessor values for the gumi system.",
        ),
        "gumi_file_override": attr.label(
            default = None,
            allow_single_file = True,
            doc = "Allow a more elaborate default set of gumi defines by pointing to another Label or file.\n" +
                  "Useful for creating a per-instance instead of per-type modules which require additional information.",
        ),
        "gumi_override": attr.string_list(
            doc = "A list of strings of module names to create gumi defines.\n" +
                  "If empty (default), the modules variable is used instead.\n" +
                  "Useful when using 'direct' or 'lib_files' or to limit the defines created when using a glob in 'modules'",
        ),
    },
    outputs = {
        "flist": "%{name}.f",
    },
)

def verilog_rtl_pkg(
        name,
        direct,
        no_synth = False,
        deps = []):
    """A single Systemverilog package.

    This rule is a specialized case of verilog_rtl_library. Systemverilog
    packages should be placed into their own rule instance to limit cross
    dependencies. In general, a block may depend on another block's package but
    should not need to depend on all the modules in the block.

    Args:
      name: A unique name for this target.
      direct: The Systemverilog file containing the package.

        See verilog_rtl_library::direct.
      no_synth: Default False.

        See verilog_rtl_library::no_synth.
      deps: Other packages this target is dependent on.

        See verilog_rtl_library::deps.
    """
    verilog_rtl_library(
        name = name,
        direct = direct,
        deps = deps,
        is_pkg = True,
        no_synth = no_synth,
        enable_gumi = False,
    )

def verilog_rtl_shell(
        name,
        module_to_shell_name,
        shell_module_label,
        deps = []):
    """An RTL shell has the same ports as another module.

    This rule is a specialized case of verilog_rtl_library.
    A 'shell' is similar to a 'stub' (empty module), but a shell may contain
    limited functionality. Frequent uses include:
      * Blackboxing hierarchy that will not be the target of testing
      * Replacing functionality with a simpler model (e.g. simulation-only memory models)

    Args:
      name: A unique name for this target.
      module_to_shell_name: The name of the module that will be replaced.

        When a downstream test uses this 'shell', a gumi define will be created using this name.

        When a shell needs to be hand-edited after generation If
        module_to_shell_name == 'custom', then all rules regarding shells are
        ignored and gumi shell defines are not thrown, allowing the user great
        power.
      shell_module_label: The Label or file containing the shell.

        See verilog_rtl_library::no_synth.
      deps: Other packages this target is dependent on.

        In general. shells should avoid having dependencies. Exceptions include
        necessary packages and possible a DV model to implement functional
        behavior.

        See verilog_rtl_library::deps.
    """
    if not name.startswith(module_to_shell_name) and module_to_shell_name != CUSTOM_SHELL:
        fail("Shell name should start with the original module name: shell name='{}' original module='{}'".format(name, module_to_shell_name))
    verilog_rtl_library(
        name = name,
        modules = [shell_module_label],
        # Intentionally do not set deps here
        is_shell_of = module_to_shell_name,
        no_synth = True,
        enable_gumi = False,
        deps = deps,
    )

def _verilog_rtl_unit_test_impl(ctx):
    trans_srcs = get_transitive_srcs([], ctx.attr.shells + ctx.attr.deps, VerilogInfo, "transitive_sources")
    srcs_list = trans_srcs.to_list()
    flists = get_transitive_srcs([], ctx.attr.shells + ctx.attr.deps, VerilogInfo, "transitive_flists")
    flists_list = flists.to_list()

    top = ""
    for dep in ctx.attr.deps:
        if VerilogInfo in dep and dep[VerilogInfo].last_module:
            top = dep[VerilogInfo].last_module.short_path

    pre_fa = ["    \\"]
    for key, value in gather_shell_defines(ctx.attr.shells).items():
        pre_fa.append("  -define {}{} \\".format(key, value))

    if len(ctx.attr.pre_flist_args):
        pre_fa.extend(["{} \\".format(pfa) for pfa in ctx.attr.pre_flist_args])
    pre_fa.append("   \\")

    if len(ctx.attr.post_flist_args):
        post_fa = "\n".join(["{} \\".format(pfa) for pfa in ctx.attr.post_flist_args]) + "\n"
    else:
        post_fa = " \\"

    ctx.actions.expand_template(
        template = ctx.file.ut_sim_template,
        output = ctx.outputs.executable,
        substitutions = {
            "{SIMULATOR_COMMAND}": ctx.attr._command_override[ToolEncapsulationInfo].command,
            "{FLISTS}": " ".join(["-f {}".format(f.short_path) for f in flists_list]),
            "{TOP}": top,
            "{PRE_FLIST_ARGS}": "\n".join(pre_fa),
            "{POST_FLIST_ARGS}": post_fa,
        },
    )

    runfiles = ctx.runfiles(files = flists_list + srcs_list + ctx.files.data + ctx.files.shells)
    return [DefaultInfo(
        runfiles = runfiles,
    )]

verilog_rtl_unit_test = rule(
    # TODO: this could eventually be a specific use case of verilog_test
    doc = """Compile and simulate a verilog_rtl_library.

    Allows a designer to write small unit/directed tests which can be included in regression.

    This rule is capable of running SVUnit regressions as well. See ut_sim_template attribute.

    Additional sim options may be passed after --.

    Typically, an additional verilog_rtl_library containing 'unit_test_top.sv'
    is created. This unit_test_top will be dependent on the DUT top, and will
    be the only dep provided to verilog_rtl_unit_test.
    """,
    implementation = _verilog_rtl_unit_test_impl,
    attrs = {
        "deps": attr.label_list(
            mandatory = True,
            doc = "Other verilog libraries this target is dependent upon.\n" +
                  "All Labels specified here must provide a VerilogInfo provider.",
        ),
        "ut_sim_template": attr.label(
            allow_single_file = True,
            default = Label("@rules_verilog//vendors/cadence:verilog_rtl_unit_test.sh.template"),
            doc = "The template to generate the script to run the test.\n" +
                  "Also available is a [SVUnit](http://agilesoc.com/open-source-projects/svunit/) test template: @rules_verilog//vendors/cadence:verilog_rtl_unit_test_svunit.sh.template\n" +
                  "If using the SVUnit template, you may also want to throw:\n" +
                  "```" +
                  "    post_flist_args = [\n" +
                  "    \"--directory <path_to_test_directory_from_workspace>\",\n" +
                  " ]," +
                  "```",
        ),
        "_command_override": attr.label(
            default = Label("@rules_verilog//:verilog_rtl_unit_test_command"),
            doc = "Allows custom override of simulator command in the event of wrapping via modulefiles.\n" +
                  "Example override in project's .bazelrc:\n" +
                  '  build --@rules_verilog//:verilog_rtl_unit_test_command="runmod -t xrun --"',
        ),
        "data": attr.label_list(
            allow_files = True,
            doc = "Non-verilog dependencies. Useful when reading in data files as stimulus/prediction.",
        ),
        "shells": attr.label_list(
            doc = _SHELLS_DOC,
        ),
        "pre_flist_args": attr.string_list(
            doc = "Additional command line arguments to be placed after the simulator binary but before the flist arguments.\n" +
                  "See ut_sim_template attribute for exact layout." +
                  "For defines to have effect, they must be declared in pre_flist_args not post_flist_args.",
        ),
        "post_flist_args": attr.string_list(
            doc = "Additional command line arguments to be placed after the flist arguments\n" +
                  "See ut_sim_template attribute for exact layout.",
        ),
    },
    test = True,
)

def _verilog_rtl_lint_test_impl(ctx):
    trans_flists = get_transitive_srcs([], ctx.attr.shells + ctx.attr.deps, VerilogInfo, "transitive_flists", allow_other_outputs = False)

    # Move the previous .log and .log.xml to .bak files
    # If the lint run doesn't produce a logfile, the lint parser script will try to parse the old log files instead of failing out
    # Moving the previous logs prevents the parser script from parsing stale files and giving incorrect results
    content = [
        "#!/usr/bin/bash",
        "mv xrun.log xrun.log.bak 2> /dev/null",
        "mv xrun.log.xml xrun.log.xml.bak 2> /dev/null",
        "{} \\".format(ctx.attr._command_override[ToolEncapsulationInfo].command),
        "  -define LINT \\",
        "  -sv \\",
        "  -hal  \\",
        "  -sv \\",
        "  -licqueue \\",
        "  -libext .v \\",
        "  -libext .sv \\",
        "  -enable_single_yvlib \\",
        # "  -nowarn SPDUSD \\",
        # "  -nowarn LIBNOU \\",
        "  -timescale 100fs/100fs \\",
    ]

    for key, value in gather_shell_defines(ctx.attr.shells).items():
        content.append("  -define {}{} \\".format(key, value))

    for key, value in ctx.attr.defines.items():
        content.append("  -define {}{} \\".format(key, value))

    for f in trans_flists.to_list():
        content.append("  -f {} \\".format(f.short_path))
    for dep in ctx.attr.deps:
        if VerilogInfo in dep and dep[VerilogInfo].last_module:
            content.append("  {} \\".format(dep[VerilogInfo].last_module.short_path))

    design_info_arg = ""

    # design_info_arg = " -design_info {}".format(ctx.files._design_info_common.short_path)
    for design_info in ctx.files.design_info:
        design_info_arg += " -design_info {}".format(design_info.short_path)

    if len(ctx.files.rulefile) > 1:
        fail("Only one rulefile allowed")
    rulefile = "".join([f.short_path for f in ctx.files.rulefile])

    content.append("  -halargs '\"-RULEFILE {rulefile} -inst_top {top} {design_info_arg} -XML xrun.log.xml\"' \\".format(
        rulefile = rulefile,
        top = ctx.attr.top,
        design_info_arg = design_info_arg,
    ))
    content.append("  -logfile xrun.log")
    parser_location = ctx.files.lint_parser[0].short_path

    content.append("")
    content.append("python {} $@ --waiver-hack \"{}\"".format(parser_location, ctx.attr.waiver_hack))

    ctx.actions.write(
        output = ctx.outputs.executable,
        content = "\n".join(content),
    )

    trans_flists = get_transitive_srcs([], ctx.attr.shells + ctx.attr.deps, VerilogInfo, "transitive_flists", allow_other_outputs = False)
    trans_srcs = get_transitive_srcs([], ctx.attr.shells + ctx.attr.deps, VerilogInfo, "transitive_sources", allow_other_outputs = True)

    runfiles = ctx.runfiles(files = trans_srcs.to_list() + trans_flists.to_list() + ctx.files.design_info + ctx.files.rulefile + ctx.files.lint_parser)

    return [
        DefaultInfo(runfiles = runfiles),
    ]

verilog_rtl_lint_test = rule(
    doc = """Compile and run lint on target

    This rule was written for Cadence HAL to be run under xcelium. As such, it
    is not entirely generic. It also uses a log post-processor
    (lint_parser_hal.py) to allow for easier waiving of warnings.

    The DUT must have no unwaived warning/errors in order for this rule to
    pass. The intended philosophy is for blocks to maintain a clean lint status
    throughout the lifecycle of the project, not to run lint as a checklist
    item towards the end of the project.

    """,
    implementation = _verilog_rtl_lint_test_impl,
    attrs = {
        "deps": attr.label_list(
            mandatory = True,
            doc = "Other verilog libraries this target is dependent upon.\n" +
                  "All Labels specified here must provide a VerilogInfo provider.",
        ),
        "rulefile": attr.label(
            allow_single_file = True,
            mandatory = True,
            doc = "The Cadence rulefile for HAL.\n" +
                  "Suggested one per project.\n" +
                  "Example: https://github.com/freecores/t6507lp/blob/ca7d7ea779082900699310db459a544133fe258a/lint/run/hal.def",
        ),
        "shells": attr.label_list(
            doc = _SHELLS_DOC,
        ),
        "top": attr.string(
            doc = "The name of the top-level module for this lint run",
            mandatory = True,
        ),
        "design_info": attr.label_list(
            allow_files = True,
            doc = "A Cadence design_info file to add additional lint rule/waivers",
        ),
        "defines": attr.string_dict(
            allow_empty = True,
            doc = "List of additional \\`defines for this lint run",
        ),
        "lint_parser": attr.label(
            allow_files = True,
            default = "@rules_verilog//:lint_parser_hal",
            doc = "Post processor for lint logs allowing for easier waiving of warnings.",
        ),
        "waiver_hack": attr.string(
            doc = "Lint waiver python regex to hack around cases when HAL has formatting errors in xrun.log.xml that cause problems for the lint parser",
        ),
        "_command_override": attr.label(
            default = Label("@rules_verilog//:verilog_rtl_lint_test_command"),
            doc = "Allows custom override of simulator command in the event of wrapping via modulefiles\n" +
                  "Example override in project's .bazelrc:\n" +
                  '  build --@rules_verilog//:verilog_rtl_lint_test_command="runmod -t xrun --"',
        ),
    },
    test = True,
)

def _verilog_rtl_cdc_test_impl(ctx):
    trans_flists = get_transitive_srcs([], ctx.attr.shells + ctx.attr.deps, VerilogInfo, "transitive_flists", allow_other_outputs = False)
    trans_srcs = get_transitive_srcs([], ctx.attr.shells + ctx.attr.deps, VerilogInfo, "transitive_sources", allow_other_outputs = True)

    # The run script is simple, the tcl command file has the interesting stuff
    ctx.actions.expand_template(
        template = ctx.file.bash_template,
        output = ctx.outputs.executable,
        substitutions = {
            "{CDC_COMMAND}": ctx.attr._command_override[ToolEncapsulationInfo].command,
            "{PREAMBLE_CMDS}": ctx.outputs.cdc_preamble_cmds.short_path,
            "{CMD_FILES}": " ".join([cmd_file.short_path for cmd_file in ctx.files.cmd_files]),
            "{EPILOGUE_CMDS}": ctx.outputs.cdc_epilogue_cmds.short_path,
        },
    )

    flists = " ".join(["-f {}".format(f.short_path) for f in trans_flists.to_list()])
    defines = ["+{}".format(define) for define in ctx.attr.defines]
    for key, value in gather_shell_defines(ctx.attr.shells).items():
        defines.append("+{}{}".format(key, value))

    bbox_modules_cmd = ""
    if ctx.attr.bbox_modules:
        bbox_modules_cmd = "-bbox_m {" + "{}".format(" ".join(ctx.attr.bbox_modules)) + "}"

    top_mod = ""
    for dep in ctx.attr.deps:
        if VerilogInfo in dep and dep[VerilogInfo].last_module:
            top_mod = "  {}".format(dep[VerilogInfo].last_module.short_path)

    if top_mod == "":
        fail("verilog_rtl_cdc_test could not determine top_module from last_module variable")

    bbox_size_cmd = ""
    if ctx.attr.bbox_size < 0:
        fail("verilog_rtl_cdc_test was specified with a negative bbox_size")
    elif ctx.attr.bbox_size > 0:
        bbox_size_cmd = "-bbox_a {}".format(ctx.attr.bbox_size)

    premable_cmds_content = [
        "clear -all",
        "set elaborate_single_run_mode True",
        "analyze -sv09 +libext+.v+.sv {} +define+LINT+CDC{} {} {}".format(bbox_modules_cmd, "".join(defines), flists, top_mod),
        "elaborate {} -top {} {}".format(bbox_modules_cmd, ctx.attr.top, bbox_size_cmd),
    ]

    epilogue_cmds_content = [
        "check_cdc -init",
        "check_cdc -clock_domain -find",
        "check_cdc -pair -find",
        "check_cdc -scheme -find",
        "check_cdc -group -find",
        "check_cdc -reset -find",
        "set all_violas [check_cdc -list violations]",
        "set num_violas [llength $all_violas]",
        "for {set viola_idx 0} {$viola_idx < $num_violas} {incr viola_idx} {",
        "puts \"[lindex $all_violas $viola_idx]\n\"",
        "}",
        "set return_value [expr {$num_violas > 0}]",
        "if {$return_value} {",
        "puts \"$num_violas errors\"",
        "}",
        "if { $::RULES_VERILOG_GUI == 0 } {",
        "exit $return_value",
        "}",
    ]

    runfiles = ctx.runfiles(files = [ctx.outputs.cdc_preamble_cmds, ctx.outputs.cdc_epilogue_cmds] + trans_srcs.to_list() + trans_flists.to_list() + ctx.files.cmd_files)

    ctx.actions.write(
        output = ctx.outputs.cdc_preamble_cmds,
        content = "\n".join(premable_cmds_content),
    )

    ctx.actions.write(
        output = ctx.outputs.cdc_epilogue_cmds,
        content = "\n".join(epilogue_cmds_content),
    )

    return [
        DefaultInfo(runfiles = runfiles),
    ]

verilog_rtl_cdc_test = rule(
    doc = "Run Jaspergold CDC on a verilog_rtl_library.",
    implementation = _verilog_rtl_cdc_test_impl,
    attrs = {
        "deps": attr.label_list(
            mandatory = True,
            doc = "Other verilog libraries this target is dependent upon.\n" +
                  "All Labels specified here must provide a VerilogInfo provider.",
        ),
        "shells": attr.label_list(
            doc = _SHELLS_DOC,
        ),
        "top": attr.string(
            doc = "The name of the top-level module for this cdc run",
            mandatory = True,
        ),
        "defines": attr.string_list(
            allow_empty = True,
            default = [],
            doc = "List of additional \\`defines for this cdc run",
        ),
        "bbox_modules": attr.string_list(
            allow_empty = True,
            default = [],
            doc = "List of modules to black box",
        ),
        "bbox_size": attr.int(
            default = 0,
            doc = "Black box any RTL array greater than the specified size. If this attribute is not set, the CDC tool will use the default size",
        ),
        "cmd_files": attr.label_list(
            allow_files = True,
            doc = "A list of tcl files containing commands to run. Multiple files are allowed to facilitate separating common project commands and block-specific commands.",
            mandatory = True,
        ),
        "bash_template": attr.label(
            allow_single_file = True,
            default = Label("//vendors/cadence:verilog_rtl_cdc_test.sh.template"),
            doc = "The template for the generated bash script which will run the case.",
        ),
        "_command_override": attr.label(
            default = Label("@rules_verilog//:verilog_rtl_cdc_test_command"),
            doc = "Allows custom override of simulator command in the event of wrapping via modulefiles\n" +
                  "Example override in project's .bazelrc:\n" +
                  '  build --@rules_verilog//:rtl_cdc_test_command="runmod -t jg --"',
        ),
    },
    outputs = {
        "cdc_preamble_cmds": "%{name}_cdc_preamble_cmds.tcl",
        "cdc_epilogue_cmds": "%{name}_cdc_epilogue_cmds.tcl",
    },
    test = True,
)
