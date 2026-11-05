# vim: set ft=bzl :
"""Repository setup for Cadence Xcelium/XRUN."""

load("//simulators:common.bzl", "dpi_headers_build", "simulator_include_path")

XRUN_DPI_HEADERS = ["svdpi.h", "svdpi_compatibility.h"]

def _xcelium_setup_impl(repository_ctx):
    if repository_ctx.attr.name.upper() != "XCELIUM":
        fail("Name xcelium_setup rule: 'XCELIUM'!")
    include = simulator_include_path(repository_ctx, "XCELIUMHOME", "tools.lnx86/include", XRUN_DPI_HEADERS)
    for hdr in XRUN_DPI_HEADERS:
        hdr_path = "{}/{}".format(include, hdr)
        repository_ctx.symlink(hdr_path, hdr)
    repository_ctx.file("BUILD", dpi_headers_build(XRUN_DPI_HEADERS))

xcelium_setup = repository_rule(
    implementation = _xcelium_setup_impl,
    local = True,
)
