# vim: set ft=bzl :
"""Common helpers for simulator repository setup rules."""

def simulator_include_path(repository_ctx, home_variable, include_subdir, headers):
    home = repository_ctx.getenv(home_variable, "").strip()
    if not home:
        fail("{} must be exported by the tool environment before starting Bazel".format(home_variable))
    include = "{}/{}".format(home, include_subdir)
    for header in headers:
        path = repository_ctx.path("{}/{}".format(include, header))
        if not path.exists:
            fail("{}={} does not provide required DPI header {}".format(home_variable, home, path))
    return include

def dpi_headers_build(headers):
    return """
filegroup(
    name = "dpi_headers",
    srcs = {headers},
    visibility = ["//visibility:public"],
)
""".format(headers = headers)
