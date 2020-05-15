load("//:verilog.bzl", "VerilogLibFiles", "RTLLibProvider", "flists_to_arguments", "get_transitive_srcs", "gather_shell_defines")


def create_flist_content(ctx, gumi_path, allow_library_discovery, no_synth=False):
    flist_content = []
    # Using dirname may result in bazel-out included in path 
    incdir = depset([f.short_path[:-len(f.basename)-1] for f in ctx.files.headers]).to_list()
    for d in incdir:
        flist_content.append("+incdir+{}".format(d))

    # Using dirname may result in bazel-out included in path
    libdir = depset([f.short_path[:-len(f.basename)-1] for f in ctx.files.modules]).to_list()
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


def _rtl_lib_impl(ctx):
    srcs = ctx.files.headers + ctx.files.modules + ctx.files.lib_files + ctx.files.direct
    
    if ctx.attr.is_pkg:
        # FIXME opu_tx_rx is failing this check
        # for dep in ctx.attr.deps:
        #     if RTLLibProvider in dep and not dep[RTLLibProvider].is_pkg:
        #         fail("rtl_pkg may only depend on other rtl_pkgs")
        pass
    else:
        for src in srcs:
            if "_pkg" in src.basename:
                fail("Package files should not declared in a rtl_lib. Use a rtl_pkg instead. {} is declared in {}".format(src, ctx.label))

    if ctx.attr.is_shell_of:
        if len(ctx.attr.modules) != 1:
            fail("Shells must specify exactly one module")
        # if len(ctx.attr.deps) != 0:
        #     fail("Shells may not specify deps")
    else:
        for dep in ctx.attr.deps:
            if RTLLibProvider in dep and dep[RTLLibProvider].is_shell_of:
                fail("rtl_lib may not depend on shells. Shells should only be included at top-level builds")
        for src in srcs:
            if "_shell" in src.basename:
                fail("Shell files should not be declared in an rtl_lib. Use a rtl_shell_static or rtl_shell_dynamic instead. {} is declared in {}".format(src, ctx.label))
        
    gumi_path = ""
    if ctx.attr.enable_gumi:
        gumi = ctx.actions.declare_file("gumi_{name}.vh".format(name = ctx.attr.name))
        gumi_content = []
        # Making this more unique than just gumi.basename.upper()
        # To avoid case where multiple directories define the same name for a rtl_lib
        gumi_guard_value = gumi.short_path.replace("/", "_").replace(".", "_")
        gumi_guard = "__{}__".format(gumi_guard_value.upper())
        gumi_content.append("`ifndef {}".format(gumi_guard))
        gumi_content.append("  `define {}".format(gumi_guard))
        gumi_content.append("")
        gumi_content.append("")
        if ctx.attr.gumi_override:
            gumi_modules = ctx.attr.gumi_override
        else:
            gumi_modules = [module.basename[:-len(module.extension)-1] for module in ctx.files.modules]
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
    else:
        if not (ctx.attr.gumi_file_override == None):
            gumi_path = ctx.file.gumi_file_override.short_path

    flist_content = create_flist_content(ctx, gumi_path=gumi_path, allow_library_discovery=True)

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

    trans_srcs   = get_transitive_srcs(srcs,  ctx.attr.deps, VerilogLibFiles, "transitive_sources", allow_other_outputs = True)
    trans_flists = get_transitive_srcs([ctx.outputs.flist], ctx.attr.deps, VerilogLibFiles, "transitive_flists" , allow_other_outputs = False)

    trans_dpi = get_transitive_srcs([], ctx.attr.deps, VerilogLibFiles, "transitive_dpi" , allow_other_outputs = False)

    runfiles_list = trans_srcs.to_list() + trans_flists.to_list() + trans_dpi.to_list()
    runfiles = ctx.runfiles(files = runfiles_list)

    all_files = depset(trans_srcs.to_list() + trans_flists.to_list())

    return [
        RTLLibProvider(
            is_pkg=ctx.attr.is_pkg,
            is_shell_of=ctx.attr.is_shell_of,
            gumi_path = gumi_path,
        ),
        VerilogLibFiles(
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

rtl_lib = rule(
    doc = "An RTL Library. Creates a generated flist file from a list of source files.",
    implementation = _rtl_lib_impl,
    attrs = {
        "headers" : attr.label_list(
            allow_files = True,
            doc = "Files that should nomally be `included into other files. (i.e. covered by +incdir)",
        ),
        "modules" : attr.label_list(
            allow_files = True,
            doc = "Files containing single modules that may be found via library (i.e. covered by -y)",
        ),
        "lib_files" : attr.label_list(
            allow_files = True,
            doc = "Verilog library files containing multiple modules (i.e. covered by -v)",
        ),
        "direct" : attr.label_list(
            allow_files = True,
            doc = "Verilog files that must be put directly onto the command line."
        ),
        "deps": attr.label_list(
            doc = "Other verilog libraries this target is dependent upon."
        ),
        "no_synth": attr.bool(
            default = False,
            doc = "When True, do not allow the content of this library to be exposed to synthesis",
        ),
        "is_pkg": attr.bool(
            default = False,
            doc = "Do not set directly in rule instances. Used for internal bookkeeping.",
        ),
        "is_shell_of" : attr.string(
            default = "",
            doc = "Do not set directly in rule instances. Used for internal bookkeeping. If set, this library is a shell of another module.",
        ),
        "enable_gumi" : attr.bool(
            default = True,
            doc = "Do not set directly in rule instances. Used for internal bookkeeping.",
        ),
        "gumi_file_override" : attr.label(
            default = None,
            allow_single_file = True,
            doc = "Should only be set if enable_gumi=False",
        ),
        "gumi_override" : attr.string_list(
            doc = "A list of string of module names to create gumi defines. If empty, the modules variable is used instead.",
        ),
    },
    outputs = {
        "flist" : "%{name}.f",
    },
)

def rtl_pkg(name,
            direct,
            no_synth=False,
            deps=[]):
    """A single rtl pkg file."""
    rtl_lib(name = name,
            direct = direct,
            deps = deps,
            is_pkg = True,
            no_synth=no_synth,
            enable_gumi = False,
    )

def rtl_shell_static(name,
                     module_to_shell_name,
                     shell_module_label,
                     deps = []):
    """A prevously created RTL shell that is version controlled. Use when a shell needs to be hand-edited after generation"""
    if not name.startswith(module_to_shell_name):
        fail("Shell name should start with the original module name: shell name='{}' original module='{}'".format(name, module_to_shell_name))
    rtl_lib(
        name = name,
        modules = [shell_module_label],
        # Intentionally do not set deps here
        is_shell_of = module_to_shell_name,
        no_synth = True,
        enable_gumi = False,
        deps = deps,
    )
    
def rtl_shell_dynamic(name,
                      module_to_shell_name,
                      shell_suffix="",
                      deps=[]):
    """Create a shell on the fly."""
    # if module_to_shell_name + "_shell" + shell_suffix != name:
    #     fail("Shell name should be original module name plus shell and suffix")

    template_path = "$$PROJ_DIR/digital/rtl/shells/template" + shell_suffix
    native.genrule(
        name = "{}_gen".format(name),
        outs = ["{}.sv".format(name)],
        srcs = deps,
        cmd = "cd $(@D); export LC_ALL=en_US.utf-8; export LANG=en_US.utf-8; cookiecutter --no-input {} module_to_shell={} shell_suffix={}".format(template_path, module_to_shell_name, shell_suffix),
        output_to_bindir = True,
    )
    rtl_lib(
        name = name,
        modules = [":{}_gen".format(name)],
        is_shell_of = module_to_shell_name,
        no_synth = True,
        enable_gumi = False,
    )


def _rtl_bin_impl(ctx):
    out = ctx.outputs.out
    trans_flists = get_transitive_srcs([], ctx.attr.deps, VerilogLibFiles, "transitive_flists", allow_other_outputs = False)

    ctx.actions.write(
        output = out,
        content = "\n".join([" -f {}".format(f.short_path) for f in trans_flists]),
    )

    trans_flists = get_transitive_srcs([out], ctx.attr.deps, VerilogLibFiles, "transitive_flists", allow_other_outputs = False)
    trans_srcs = get_transitive_srcs([], ctx.attr.deps, VerilogLibFiles, "transitive_sources", allow_other_outputs = True)

    second_out = ctx.outputs.executable
    script = "\n".join(
        ["echo `pwd`"],
    )

    ctx.actions.write(
        output = second_out,
        content = script,
    )

    runfiles = ctx.runfiles(files = trans_srcs.to_list() + trans_flists.to_list())

    return [
        DefaultInfo(runfiles = runfiles),
    ]

rtl_bin = rule(
    doc = "Merge all flists into a single top-level flist.",
    implementation = _rtl_bin_impl,
    attrs = {
        "deps": attr.label_list(),
    },
    outputs = {"out": "%{name}.f"},
    executable = True,
    #output_to_genfiles = True,
)

def _rtl_flist_impl(ctx):
    num_srcs = len(ctx.files.srcs)
    if num_srcs != 1:
        fail("rtl_flist rule may only have single source file: {}".format(ctx))

    # Ideally it would be nice to grab all the files inside an flist, but this could be recursive, so skipping this for now.
    trans_srcs = depset([])
    trans_flists = depset(ctx.files.srcs)

    return [
        VerilogLibFiles(transitive_sources = trans_srcs, transitive_flists = trans_flists, transitive_dpi=depset()),
        DefaultInfo(files = trans_srcs + trans_flists),
    ]

rtl_flist = rule(
    doc = "Create an RTL Library from an existing flist file. Recommended only for vendor supplied IP. In general, use the rtl_lib rule.",
    implementation = _rtl_flist_impl,
    attrs = {
        "srcs": attr.label_list(
            allow_files = True,
            mandatory = True,
        ),
    },
    #output_to_genfiles = True,
)

def _rtl_unit_test_impl(ctx):
    # out = ctx.outputs.executable
    trans_srcs = get_transitive_srcs([], ctx.attr.deps, VerilogLibFiles, "transitive_sources")
    srcs_list = trans_srcs.to_list()
    flists = get_transitive_srcs([], ctx.attr.deps, VerilogLibFiles, "transitive_flists")
    flists_list = flists.to_list()

    top = ""
    for dep in ctx.attr.deps:
        if VerilogLibFiles in dep and dep[VerilogLibFiles].last_module:
            top = dep[VerilogLibFiles].last_module.short_path

    ctx.actions.expand_template(
        template = ctx.file.ut_sim_template,
        output = ctx.outputs.executable,
        substitutions = {
            "{FLISTS}": " ".join(["-f {}".format(f.short_path) for f in flists_list]),
            "{TOP}": top,
        },
    )

    runfiles = ctx.runfiles(files = flists_list + srcs_list)
    return [DefaultInfo(
        runfiles = runfiles,
    )]

rtl_unit_test = rule(
    # FIXME, this should eventually just be a specific use case of verilog_test
    doc = "Compiles and runs a small RTL library. Additional sim options may be passed after --",
    implementation = _rtl_unit_test_impl,
    attrs = {
        "deps": attr.label_list(mandatory = True),
        "out": attr.output(),
        "ut_sim_template": attr.label(
            allow_single_file = True,
            default = Label("//:rtl_unit_test_sim_template.sh"),
        ),
    },
    test = True,
)


def _rtl_lint_impl(ctx):
    trans_flists = get_transitive_srcs([], ctx.attr.shells + ctx.attr.deps, VerilogLibFiles, "transitive_flists", allow_other_outputs = False)

    content = ["#!/usr/bin/bash",
               "runmod -t xrun -- \\",
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

    for f in trans_flists.to_list():
        content.append("  -f {} \\".format(f.short_path))
    for dep in ctx.attr.deps:
        if VerilogLibFiles in dep and dep[VerilogLibFiles].last_module:
            content.append("  {} \\".format(dep[VerilogLibFiles].last_module.short_path))

    design_info_arg = ""
    # design_info_arg = " -design_info {}".format(ctx.files._design_info_common.short_path)
    for design_info in ctx.files.design_info:
        design_info_arg += " -design_info {}".format(design_info.short_path)

    if len(ctx.files.rulefile) > 1:
        fail("Only one rulefile allowed")
    rulefile = "".join([f.short_path for f in ctx.files.rulefile])

    content.append("  -halargs '\"-RULEFILE {rulefile} -inst_top {top} {design_info_arg}\"' \\".format(rulefile = rulefile,
                                                                                                     top = ctx.attr.top,
                                                                                                     design_info_arg = design_info_arg,
                                                                                                 ))
    content.append("  $@")
    content.append("")

    ctx.actions.write(
        output = ctx.outputs.run_lint,
        content = "\n".join(content),
    )

    # Dummy executable to create rundir
    ctx.actions.write(
        output = ctx.outputs.executable,
        content = "echo `pwd`",
    )

    trans_flists = get_transitive_srcs([], ctx.attr.shells + ctx.attr.deps, VerilogLibFiles, "transitive_flists", allow_other_outputs = False)
    trans_srcs = get_transitive_srcs([], ctx.attr.shells + ctx.attr.deps, VerilogLibFiles, "transitive_sources", allow_other_outputs = True)

    runfiles = ctx.runfiles(files = trans_srcs.to_list() + trans_flists.to_list() + [ctx.outputs.run_lint] + ctx.files.design_info + ctx.files.rulefile)

    return [
        DefaultInfo(runfiles = runfiles),
    ]

rtl_lint = rule(
    doc = "Create the lint script executable",
    implementation = _rtl_lint_impl,
    attrs = {
        "deps": attr.label_list(mandatory = True),
        "rulefile" : attr.label(allow_single_file = True,
                                mandatory = True,
                            ),
        "shells" : attr.label_list(),
        "top" : attr.string(doc = "The name of the top module",
                            mandatory = True,
                        ),
        "design_info" : attr.label_list(allow_files = True,
                                        doc = "A design info file to add additional lint rule/waivers",
                                    ),
        "defines" : attr.string_list(allow_empty = True,
                                     default = [],
                                     doc = "List of `defines for this lint run",
                                     ),
    },
    outputs = {"run_lint": "run_%{name}.sh"},
    executable = True,
)

def _rtl_cdc_test_impl(ctx):

    trans_flists = get_transitive_srcs([], ctx.attr.shells + ctx.attr.deps, VerilogLibFiles, "transitive_flists", allow_other_outputs = False)
    trans_srcs = get_transitive_srcs([], ctx.attr.shells + ctx.attr.deps, VerilogLibFiles, "transitive_sources", allow_other_outputs = True)

    # The run script is pretty dumb, the tcl command file has the interesting stuff
    executable_content = [
        "#!/usr/bin/bash",
        "set -e",
        "runmod -t jg -- \\",
        "  -cdc \\",
        "  -no_gui \\",
        "  -proj `calc_simresults_location.py`/jg_cdc_{}\\".format(ctx.attr.top),
        "  {} \\".format(ctx.outputs.cdc_preamble_cmds.short_path),
        "  {} \\".format(ctx.files.cmd_file[0].short_path),
        "  {} \\".format(ctx.outputs.cdc_epilogue_cmds.short_path),
        "  $@",
        "! grep \"^\\[*ERROR\" `calc_simresults_location.py`/jg_cdc_{}/jg.log".format(ctx.attr.top),
        "",
    ]

    executable_content.append("  $@")
    executable_content.append("")

    flists = " ".join(["-f {}".format(f.short_path) for f in trans_flists.to_list()])
    defines = ["+{}".format(define) for define in ctx.attr.defines]
    for key, value in gather_shell_defines(ctx.attr.shells).items():
        defines.append("+{}{}".format(key, value))

    bbox_cmd = ""
    if ctx.attr.bbox:
        bbox_cmd = "-bbox_m {" + "{}".format(" ".join(ctx.attr.bbox)) + "}"

    for dep in ctx.attr.deps:
        if VerilogLibFiles in dep and dep[VerilogLibFiles].last_module:
            top_mod = "  {}".format(dep[VerilogLibFiles].last_module.short_path)

    bbox_a_cmd = "-bbox_a 4096"

    premable_cmds_content = [
        "clear -all",
        "set elaborate_single_run_mode True",
        "analyze -sv09 +libext+.v+.sv {} +define+LINT+CDC+SKIP_PWR_GND{} {} {}".format(bbox_cmd, "".join(defines), flists, top_mod),
        "elaborate {} -top alpha_mosaic_ams_top {}".format(bbox_cmd, bbox_a_cmd),
        "check_cdc -check -rule -set {{treat_boundaries_as_unclocked true}}",
    ]

    epilogue_cmds_content = [
        "set all_violas [check_cdc -list violations]",
        "set num_violas [llength $all_violas]",
        "for {set viola_idx 0} {$viola_idx < $num_violas} {incr viola_idx} {",
        "puts \"[lindex $all_violas $viola_idx]\n\"",
        "}",
        "set return_value [expr {$num_violas > 0}]",
        "if {$return_value} {",
        "puts \"$num_violas errors\"",
        "}",
        "exit $return_value",
    ]

    ctx.actions.write(
        output = ctx.outputs.executable,
        content = "\n".join(executable_content),
    )

    runfiles = ctx.runfiles(files = [ctx.outputs.cdc_preamble_cmds, ctx.outputs.cdc_epilogue_cmds] + trans_srcs.to_list() + trans_flists.to_list() + ctx.files.cmd_file)

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

rtl_cdc_test = rule(
    doc = "Run CDC",
    implementation = _rtl_cdc_test_impl,
    attrs = {
        "deps": attr.label_list(mandatory = True),
        "shells" : attr.label_list(),
        "top" : attr.string(doc = "The name of the top module",
                            mandatory = True,
                        ),
        "defines" : attr.string_list(allow_empty = True,
                                     default = [],
                                     doc = "List of `defines for this cdc run",
                                     ),
        "bbox" : attr.string_list(allow_empty = True,
                                  default = [],
                                  doc = "List of modules to black box",
                              ),
        "cmd_file" : attr.label(allow_files = True,
                                doc = "tcl commands to run in JG",
                                 mandatory = True,
                             ),
    },
    outputs = {
        "cdc_preamble_cmds": "%{name}_cdc_preamble_cmds.tcl",
        "cdc_epilogue_cmds": "%{name}_cdc_epilogue_cmds.tcl",
    },
    test = True,
)
def _rtl_cdc_gui_impl(ctx):

    trans_flists = get_transitive_srcs([], ctx.attr.shells + ctx.attr.deps, VerilogLibFiles, "transitive_flists", allow_other_outputs = False)
    trans_srcs = get_transitive_srcs([], ctx.attr.shells + ctx.attr.deps, VerilogLibFiles, "transitive_sources", allow_other_outputs = True)

    # The run script is pretty dumb, the tcl command file has the interesting stuff
    executable_content = [
        "#!/usr/bin/bash",
        "runmod -t jg -- \\",
        "  -cdc \\",
        "  -proj `calc_simresults_location.py`/jg_cdc_{}\\".format(ctx.attr.top),
        "  {} \\".format(ctx.outputs.cdc_preamble_cmds.short_path),
        "  {} \\".format(ctx.files.cmd_file[0].short_path),
        "  {} \\".format(ctx.outputs.cdc_epilogue_cmds.short_path),
    ]

    executable_content.append("  $@")
    executable_content.append("")

    flists = " ".join(["-f {}".format(f.short_path) for f in trans_flists])
    defines = ["+{}".format(define) for define in ctx.attr.defines]
    for key, value in gather_shell_defines(ctx.attr.shells).items():
        defines.append("+{}{}".format(key, value))

    bbox_cmd = ""
    if ctx.attr.bbox:
        bbox_cmd = "-bbox_m {" + "{}".format(" ".join(ctx.attr.bbox)) + "}"

    for dep in ctx.attr.deps:
        if VerilogLibFiles in dep and dep[VerilogLibFiles].last_module:
            top_mod = "  {}".format(dep[VerilogLibFiles].last_module.short_path)

    bbox_a_cmd = "-bbox_a 4096"

    premable_cmds_content = [
        "clear -all",
        "set elaborate_single_run_mode True",
        "analyze -sv09 +libext+.v+.sv {} +define+LINT+CDC+SKIP_PWR_GND{} {} {}".format(bbox_cmd, "".join(defines), flists, top_mod),
        "elaborate {} -top alpha_mosaic_ams_top {}".format(bbox_cmd, bbox_a_cmd),
        "check_cdc -check -rule -set {{treat_boundaries_as_unclocked true}}",
    ]

    epilogue_cmds_content = [
        "set all_violas [check_cdc -list violations]",
        "set num_violas [llength $all_violas]",
        "for {set viola_idx 0} {$viola_idx < $num_violas} {incr viola_idx} {",
        "puts \"[lindex $all_violas $viola_idx]\n\"",
        "}",
        "set return_value [expr {$num_violas > 0}]",
    ]

    ctx.actions.write(
        output = ctx.outputs.executable,
        content = "\n".join(executable_content),
    )

    runfiles = ctx.runfiles(files = [ctx.outputs.cdc_preamble_cmds, ctx.outputs.cdc_epilogue_cmds] + trans_srcs.to_list() + trans_flists.to_list() + ctx.files.cmd_file)

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

rtl_cdc_gui = rule(
    doc = "Run CDC",
    implementation = _rtl_cdc_gui_impl,
    attrs = {
        "deps": attr.label_list(mandatory = True),
        "shells" : attr.label_list(),
        "top" : attr.string(doc = "The name of the top module",
                            mandatory = True,
                        ),
        "defines" : attr.string_list(allow_empty = True,
                                     default = [],
                                     doc = "List of `defines for this cdc run",
                                     ),
        "bbox" : attr.string_list(allow_empty = True,
                                  default = [],
                                  doc = "List of modules to black box",
                              ),
        "cmd_file" : attr.label(allow_files = True,
                                doc = "tcl commands to run in JG",
                                 mandatory = True,
                             ),
    },
    outputs = {
        "cdc_preamble_cmds": "%{name}_cdc_preamble_cmds.tcl",
        "cdc_epilogue_cmds": "%{name}_cdc_epilogue_cmds.tcl",
    },
    executable = True,
)

def rtl_cdc(name,
            deps,
            top,
            cmd_file,
            shells,
            bbox,
            defines,
            tags=[]):
    """Create rules to run standard CDC test and to run in GUI mode"""
    rtl_cdc_test(
        name = name,
        deps = deps,
        top = top,
        cmd_file = cmd_file,
        shells = shells,
        bbox = bbox,
        defines = defines,
        tags = tags,
    )

    rtl_cdc_gui(
        name = "{}_gui".format(name),
        deps = deps,
        top = top,
        cmd_file = cmd_file,
        shells = shells,
        bbox = bbox,
        defines = defines,
    )
