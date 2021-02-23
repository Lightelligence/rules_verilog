# Verilog rules for Bazel

## Setup
                                                                                                  
Add the following to you `WORKSPACE`:

```skylark                                                                                                                                             |      #     source env/env.sh                  
FIXME implement after first release using https://docs.bazel.build/versions/master/skylark/deploying.html#readme as template.
```

** Note**: Update commit and sha256 as needed.

## Rules

### RTL
Load rules into your `BUILD` files from [@verilog_tools//verilog:rtl.bzl](verilog/rtl.bzl)

- [verilog_rtl_library](docs/rtl.md#verilog_rtl_library)
- [verilog_rtl_pkg](docs/rtl.md#verilog_rtl_pkg)
- [verilog_rtl_shel](docs/rtl.md#verilog_rtl_shell)
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
