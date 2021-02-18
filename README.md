# Verilog rules for Bazel

## Setup
                                                                                                  
Add the following to you `WORKSPACE`:

```skylark                                                                                                                                             |      #     source env/env.sh                  
FIXME implement after first release using https://docs.bazel.build/versions/master/skylark/deploying.html#readme as template.
```

** Note**: Update commit and sha256 as needed.

## Rules

### RTL
Load rules into your `BUILD` files from [@verilog_tools//:rtl.bzl](rtl.bzl)

- [verilog_rtl_library](docs/rtl.md#verilog_rtl_library)
FIXME add more to list


### DV
Load rules into your `BUILD` files from [@verilog_tools//:dv.bzl](dv.bzl)

- [verilog_dv_library](docs/dv.md#verilog_dv_library)
FIXME add more to list


### Generic Verilog
Load rules into your `BUILD` files from [@verilog_tools//:verilog.bzl](verilog.bzl)

- [verilog_test](docs/verilog.md#verilog_test)
