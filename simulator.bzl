# -*- mode: python -*-
"""Provides access to the DPI headers in an xcelium installation.

This allows bazel to precompile DPI code to be able to pass shared
objects to xrun via the -sv_lib flag.

It is currently dependent on our environement setup and should be made more
generic if possible. Bazel makes this extremely tedious to get this information
dynamically.

Example usage in another WORKSPACE file:

load("@verilog_tools//:simulator.bzl", "xcelium_setup")
xcelium_setup(name="xcelium")
"""

XCELIUM_BUILD = """
# filegroup(
#     name = "vpi_headers",
#     srcs = glob(["vpi_*.h"]),
#     visibility = ["//visibility:public"],
# )
filegroup(
    name = "dpi_headers",
    srcs = ["svdpi.h", "svdpi_compatibility.h"],
    visibility = ["//visibility:public"],
)

"""

DPI_HEADERS = ["svdpi.h", "svdpi_compatibility.h"]


VARS = ["PROJ_DIR", "MODULEPATH"]
def _xcelium_setup_impl(repository_ctx):
    if repository_ctx.attr.name != "xcelium":
        fail("Name xcelium_setup rule: 'xcelium'!")
    # Not thrilled about how specific this is to our project
    # Ideally this would be a generic command to be run
    # result = repository_ctx.execute(["runmod", "xrun", "--", "printenv", "XCELIUMHOME"],
    #                                 environment = repository_ctx.os.environ,
    #                                 # working_directory="..",
    # )
    # if result.return_code:
    #     print(result.stdout)
    #     print(result.stderr)
    #     fail("Failed running xcelium command")
    # xcelium_home = result.stdout.strip()
    # FIXME remove hard coding once modulefiles are in place
    xcelium_home = "/tools/cadence/XCELIUM1909"
    include = "{}/tools.lnx86/include".format(xcelium_home)
    for hdr in  DPI_HEADERS:
        hdr_path = "{}/{}".format(include, hdr)
        repository_ctx.symlink(hdr_path, hdr)
    repository_ctx.file("BUILD", XCELIUM_BUILD)
  
xcelium_setup = repository_rule(
    implementation=_xcelium_setup_impl,
    local = True,
    environ = VARS,
)
