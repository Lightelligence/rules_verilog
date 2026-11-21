"""Palladium compatibility output helpers for DV rules."""

load("//verilog/private:verilog.bzl", "VerilogInfo", "expand_runfiles_locations", "flists_to_arguments")

def _materialize_declared_outputs(ctx, defines, selected_compile_args):
    compile_args = expand_runfiles_locations(ctx, "\n".join(selected_compile_args), targets = ctx.attr.extra_runfiles)
    flists = flists_to_arguments(ctx.attr.shells + ctx.attr.deps, VerilogInfo, "transitive_flists", "\n-f")
    ctx.actions.expand_template(
        template = ctx.file._compile_args_template_pldm_ice,
        output = ctx.outputs.compile_args_pldm_ice,
        substitutions = {
            "{COMPILE_ARGS}": compile_args,
            "{DEFINES}": "\n".join(["+define+{}{}".format(key, value) for key, value in defines.items()]),
            "{FLISTS}": flists,
        },
    )
    ctx.actions.expand_template(
        template = ctx.file._compile_args_template_pldm_sa,
        output = ctx.outputs.compile_args_pldm_sa,
        substitutions = {
            "{COMPILE_ARGS}": compile_args,
            "{DEFINES}": "\n".join(["-define {}{}".format(key, value) for key, value in defines.items()]),
            "{FLISTS}": flists,
        },
    )

pldm_dv_backend = struct(
    materialize_declared_outputs = _materialize_declared_outputs,
)
