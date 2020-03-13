
def xcelium_setup():
    native.new_local_repository(
    name = "xcelium",
    path = "/tools/cadence/XCELIUM1909/tools.lnx86/include/",
    build_file_content = """
filegroup(
    name = "vpi_headers",
    srcs = glob(["vpi_*.h"]),
    visibility = ["//visibility:public"],
)
filegroup(
    name = "dpi_headers",
    srcs = ["svdpi.h", "svdpi_compatibility.h"],
    visibility = ["//visibility:public"],
)
""",
    )


