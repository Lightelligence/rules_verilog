# Verilog rules for Bazel

## Setup
                                                                                                  
Add the following to your `WORKSPACE` file:

```skylark                                                                                                                                             |      #     source env/env.sh                  
FIXME implement after first release using https://docs.bazel.build/versions/master/skylark/deploying.html#readme as template.

load("@verilog_tools//:deps.bzl", "verilog_dependencies")

verilog_dependencies()
```
**Note**: Update commit and sha256 as needed.


Cadence Xcelium needs both HOME and LM_LICENESE_FILE environment variables, add them to your `.bazelrc` file:

```
test --action_env=HOME
test --action_env=LM_LICENSE_FILE
```

### Python Dependencies
verilog_tools is also dependent on several python libraries. These are defined in requirements.txt and maybe installed in the package manager of your choice. The recommended flow is to install them via the pip_install rule in your `WORKSPACE` file:

```skylark
load("@rules_python//python:pip.bzl", "pip_install")

pip_install(
    name = "pip_deps",
    requirements = "@verilog_tools//:requirements.txt",
)
```

## Rules

### RTL
Load rules into your `BUILD` files from [@verilog_tools//verilog:rtl.bzl](verilog/rtl.bzl)

- [verilog_rtl_library](docs/rtl.md#verilog_rtl_library)
- [verilog_rtl_pkg](docs/rtl.md#verilog_rtl_pkg)
- [verilog_rtl_shell](docs/rtl.md#verilog_rtl_shell)
- [verilog_rtl_unit_test](docs/rtl.md#verilog_rtl_unit_test)
- [verilog_rtl_lint_test](docs/rtl.md#verilog_rtl_lint_test)
- [verilog_rtl_cdc_test](docs/rtl.md#verilog_rtl_cdc_test)


### DV
Load rules into your `BUILD` files from [@verilog_tools//:dv.bzl](dv.bzl)

- [verilog_dv_library](docs/dv.md#verilog_dv_library)
- [verilog_dv_unit_test](docs/dv.md#verilog_dv_unit_test)
- [verilog_dv_tb](docs/dv.md#verilog_dv_tb)
- [verilog_dv_test_cfg](docs/dv.md#verilog_dv_test_cfg)


### Generic Verilog
Load rules into your `BUILD` files from [@verilog_tools//:verilog.bzl](verilog.bzl)

- [verilog_test](docs/verilog.md#verilog_test)
