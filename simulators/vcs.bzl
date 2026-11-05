# vim: set ft=bzl :
"""Repository setup for Synopsys VCS."""

load("//simulators:common.bzl", "dpi_headers_build", "simulator_include_path")

VCS_DPI_HEADERS = ["svdpi.h", "svdpi_src.h"]

def _vcs_setup_impl(repository_ctx):
    if repository_ctx.attr.name.upper() != "VCS":
        fail("Name vcs_setup rule: 'VCS'!")
    include = simulator_include_path(repository_ctx, "VCS_HOME", "include", VCS_DPI_HEADERS)
    for hdr in VCS_DPI_HEADERS:
        hdr_path = "{}/{}".format(include, hdr)
        repository_ctx.symlink(hdr_path, hdr)
    repository_ctx.file("BUILD", dpi_headers_build(VCS_DPI_HEADERS))

vcs_setup = repository_rule(
    implementation = _vcs_setup_impl,
    local = True,
)
