"""Analysis tests for legacy VCS unit-test option normalization."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts", "unittest")

# Internal helper tests intentionally exercise the private implementation.
# buildifier: disable=bzl-visibility
load("//verilog/private:verilog.bzl", "normalize_vcs_unit_test_compile_args", "partition_vcs_unit_test_args")

def _normalization_test_impl(ctx):
    env = unittest.begin(ctx)
    args = partition_vcs_unit_test_args([
        "-64bit -sv -mess -disable_sem2009 -ALLOWREDEFINITION -allowredefinition",
        "-input 'waves with spaces.tcl' -access +rw -debug_opts=verisium_pp",
        "-define FOO=1 -define=BAR +define+NATIVE +warn=all",
        "+ntb_random_seed=7 +UVM_TESTNAME=smoke '+message=hello world'",
    ])
    asserts.equals(env, ["+define+FOO=1", "+define+BAR", "+define+NATIVE", "+warn=all"], args.compile_args)
    asserts.equals(env, ["+ntb_random_seed=7", "+UVM_TESTNAME=smoke", "'+message=hello world'"], args.runtime_args)
    asserts.equals(env, ["-licqueue", "-no_save", "-tf_sv_string", "+test=1"], normalize_vcs_unit_test_compile_args([
        "-input=waves.tcl -access +rw -debug_opts verisium_pp",
        "-licqueue -no_save -tf_sv_string +test=1",
    ], runtime = True))
    return unittest.end(env)

_normalization_test = unittest.make(_normalization_test_impl)

def _invalid_args_impl(ctx):
    normalize_vcs_unit_test_compile_args(ctx.attr.options, runtime = ctx.attr.runtime)
    return []

_invalid_args = rule(
    implementation = _invalid_args_impl,
    attrs = {"options": attr.string_list(), "runtime": attr.bool()},
)

def _failure_test_impl(ctx):
    env = analysistest.begin(ctx)
    asserts.expect_failure(env, ctx.attr.message)
    return analysistest.end(env)

_failure_test = analysistest.make(
    _failure_test_impl,
    expect_failure = True,
    attrs = {"message": attr.string()},
)

def vcs_unit_args_test_suite(name):
    """Create normalization tests, including malformed option rejection."""
    _normalization_test(name = name + "_normalization")
    cases = [
        (["-define"], False, "requires a value"),
        (["-define="], False, "requires a non-empty value"),
        (["-define -sv"], False, "requires a non-empty value"),
        (["-access -sv"], False, "requires a value before"),
        (["-input="], False, "requires a value"),
        (["-input +UVM_TESTNAME=smoke"], False, "requires a value before"),
        (["-debug_opts"], False, "requires a value"),
        (["-input 'unterminated"], False, "Unterminated quote"),
        (["-define FOO"], True, "is a compile option"),
        (["-define=FOO"], True, "is a compile option"),
        (["+define+FOO"], True, "is a compile option"),
    ]
    tests = [":" + name + "_normalization"]
    for index, (options, runtime, message) in enumerate(cases):
        target = "{}_invalid_{}".format(name, index)
        _invalid_args(name = target, options = options, runtime = runtime, tags = ["manual"])
        _failure_test(name = target + "_test", target_under_test = ":" + target, message = message)
        tests.append(":" + target + "_test")
    native.test_suite(name = name, tests = tests)
