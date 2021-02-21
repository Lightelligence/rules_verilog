<!-- Generated with Stardoc: http://skydoc.bazel.build -->

<a name="#verilog_rtl_cdc_test"></a>

## verilog_rtl_cdc_test

<pre>
verilog_rtl_cdc_test(<a href="#verilog_rtl_cdc_test-name">name</a>, <a href="#verilog_rtl_cdc_test-bash_template">bash_template</a>, <a href="#verilog_rtl_cdc_test-bbox">bbox</a>, <a href="#verilog_rtl_cdc_test-cmd_file">cmd_file</a>, <a href="#verilog_rtl_cdc_test-defines">defines</a>, <a href="#verilog_rtl_cdc_test-deps">deps</a>, <a href="#verilog_rtl_cdc_test-shells">shells</a>, <a href="#verilog_rtl_cdc_test-top">top</a>)
</pre>

Run CDC

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :-------------: | :-------------: | :-------------: | :-------------: | :-------------: |
| name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| bash_template |  -   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | //vendors/cadence:verilog_rtl_cdc_test.sh.template |
| bbox |  List of modules to black box   | List of strings | optional | [] |
| cmd_file |  tcl commands to run in JG   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | required |  |
| defines |  List of <code>defines for this cdc run   | List of strings | optional | [] |
| deps |  -   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | required |  |
| shells |  -   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| top |  The name of the top module   | String | required |  |


<a name="#verilog_rtl_flist"></a>

## verilog_rtl_flist

<pre>
verilog_rtl_flist(<a href="#verilog_rtl_flist-name">name</a>, <a href="#verilog_rtl_flist-srcs">srcs</a>)
</pre>

Create an RTL Library from an existing flist file. Recommended only for vendor supplied IP. In general, use the verilog_rtl_library rule.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :-------------: | :-------------: | :-------------: | :-------------: | :-------------: |
| name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| srcs |  -   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | required |  |


<a name="#verilog_rtl_library"></a>

## verilog_rtl_library

<pre>
verilog_rtl_library(<a href="#verilog_rtl_library-name">name</a>, <a href="#verilog_rtl_library-deps">deps</a>, <a href="#verilog_rtl_library-direct">direct</a>, <a href="#verilog_rtl_library-enable_gumi">enable_gumi</a>, <a href="#verilog_rtl_library-gumi_file_override">gumi_file_override</a>, <a href="#verilog_rtl_library-gumi_override">gumi_override</a>, <a href="#verilog_rtl_library-headers">headers</a>,
                    <a href="#verilog_rtl_library-is_pkg">is_pkg</a>, <a href="#verilog_rtl_library-is_shell_of">is_shell_of</a>, <a href="#verilog_rtl_library-lib_files">lib_files</a>, <a href="#verilog_rtl_library-modules">modules</a>, <a href="#verilog_rtl_library-no_synth">no_synth</a>)
</pre>

An RTL Library. Creates a generated flist file from a list of source files.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :-------------: | :-------------: | :-------------: | :-------------: | :-------------: |
| name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| deps |  Other verilog libraries this target is dependent upon.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| direct |  Verilog files that must be put directly onto the command line.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| enable_gumi |  Do not set directly in rule instances. Used for internal bookkeeping.   | Boolean | optional | True |
| gumi_file_override |  Should only be set if enable_gumi=False   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | None |
| gumi_override |  A list of string of module names to create gumi defines. If empty, the modules variable is used instead.   | List of strings | optional | [] |
| headers |  Files that should nomally be <code>included into other files. (i.e. covered by +incdir)   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| is_pkg |  Do not set directly in rule instances. Used for internal bookkeeping.   | Boolean | optional | False |
| is_shell_of |  Do not set directly in rule instances. Used for internal bookkeeping. If set, this library is a shell of another module.   | String | optional | "" |
| lib_files |  Verilog library files containing multiple modules (i.e. covered by -v)   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| modules |  Files containing single modules that may be found via library (i.e. covered by -y)   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| no_synth |  When True, do not allow the content of this library to be exposed to synthesis   | Boolean | optional | False |


<a name="#verilog_rtl_lint_test"></a>

## verilog_rtl_lint_test

<pre>
verilog_rtl_lint_test(<a href="#verilog_rtl_lint_test-name">name</a>, <a href="#verilog_rtl_lint_test-defines">defines</a>, <a href="#verilog_rtl_lint_test-deps">deps</a>, <a href="#verilog_rtl_lint_test-design_info">design_info</a>, <a href="#verilog_rtl_lint_test-lint_parser">lint_parser</a>, <a href="#verilog_rtl_lint_test-rulefile">rulefile</a>, <a href="#verilog_rtl_lint_test-shells">shells</a>, <a href="#verilog_rtl_lint_test-top">top</a>,
                      <a href="#verilog_rtl_lint_test-waiver_hack">waiver_hack</a>)
</pre>

Run lint on target

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :-------------: | :-------------: | :-------------: | :-------------: | :-------------: |
| name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| defines |  List of <code>defines for this lint run   | <a href="https://bazel.build/docs/skylark/lib/dict.html">Dictionary: String -> String</a> | optional | {} |
| deps |  -   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | required |  |
| design_info |  A design info file to add additional lint rule/waivers   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| lint_parser |  -   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | @verilog_tools//:lint_parser_hal |
| rulefile |  -   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | required |  |
| shells |  -   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| top |  The name of the top module   | String | required |  |
| waiver_hack |  Lint waiver regex to hack around cases when HAL has formatting errors in xrun.log.xml that cause problems for our lint parser   | String | optional | "" |


<a name="#verilog_rtl_unit_test"></a>

## verilog_rtl_unit_test

<pre>
verilog_rtl_unit_test(<a href="#verilog_rtl_unit_test-name">name</a>, <a href="#verilog_rtl_unit_test-data">data</a>, <a href="#verilog_rtl_unit_test-deps">deps</a>, <a href="#verilog_rtl_unit_test-out">out</a>, <a href="#verilog_rtl_unit_test-post_flist_args">post_flist_args</a>, <a href="#verilog_rtl_unit_test-pre_flist_args">pre_flist_args</a>, <a href="#verilog_rtl_unit_test-shells">shells</a>,
                      <a href="#verilog_rtl_unit_test-ut_sim_template">ut_sim_template</a>)
</pre>

Compiles and runs a small RTL library. Additional sim options may be passed after --

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :-------------: | :-------------: | :-------------: | :-------------: | :-------------: |
| name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| data |  Non-verilog dependencies   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| deps |  -   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | required |  |
| out |  -   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | None |
| post_flist_args |  commands and arguments after flist arguments   | List of strings | optional | [] |
| pre_flist_args |  commands and arguments before flist arguments   | List of strings | optional | [] |
| shells |  -   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| ut_sim_template |  The template to generate the script to run the test. Also available is a [SVUnit](http://agilesoc.com/open-source-projects/svunit/) test template: @verilog_tools//vendors/cadence:verilog_rtl_unit_test_svunit.sh.template If using the SVUnit template, you may also want to throw: <pre><code>    post_flist_args = [     "--directory &lt;path_to_test_directory_from_workspace&gt;",  ],</code></pre>   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | @verilog_tools//vendors/cadence:verilog_rtl_unit_test.sh.template |


<a name="#create_flist_content"></a>

## create_flist_content

<pre>
create_flist_content(<a href="#create_flist_content-ctx">ctx</a>, <a href="#create_flist_content-gumi_path">gumi_path</a>, <a href="#create_flist_content-allow_library_discovery">allow_library_discovery</a>, <a href="#create_flist_content-no_synth">no_synth</a>)
</pre>



**PARAMETERS**


| Name  | Description | Default Value |
| :-------------: | :-------------: | :-------------: |
| ctx |  <p align="center"> - </p>   |  none |
| gumi_path |  <p align="center"> - </p>   |  none |
| allow_library_discovery |  <p align="center"> - </p>   |  none |
| no_synth |  <p align="center"> - </p>   |  <code>False</code> |


<a name="#verilog_rtl_pkg"></a>

## verilog_rtl_pkg

<pre>
verilog_rtl_pkg(<a href="#verilog_rtl_pkg-name">name</a>, <a href="#verilog_rtl_pkg-direct">direct</a>, <a href="#verilog_rtl_pkg-no_synth">no_synth</a>, <a href="#verilog_rtl_pkg-deps">deps</a>)
</pre>

A single rtl pkg file.

**PARAMETERS**


| Name  | Description | Default Value |
| :-------------: | :-------------: | :-------------: |
| name |  <p align="center"> - </p>   |  none |
| direct |  <p align="center"> - </p>   |  none |
| no_synth |  <p align="center"> - </p>   |  <code>False</code> |
| deps |  <p align="center"> - </p>   |  <code>[]</code> |


<a name="#verilog_rtl_shell_dynamic"></a>

## verilog_rtl_shell_dynamic

<pre>
verilog_rtl_shell_dynamic(<a href="#verilog_rtl_shell_dynamic-name">name</a>, <a href="#verilog_rtl_shell_dynamic-module_to_shell_name">module_to_shell_name</a>, <a href="#verilog_rtl_shell_dynamic-shell_suffix">shell_suffix</a>, <a href="#verilog_rtl_shell_dynamic-deps">deps</a>)
</pre>

Create a shell on the fly.

**PARAMETERS**


| Name  | Description | Default Value |
| :-------------: | :-------------: | :-------------: |
| name |  <p align="center"> - </p>   |  none |
| module_to_shell_name |  <p align="center"> - </p>   |  none |
| shell_suffix |  <p align="center"> - </p>   |  <code>""</code> |
| deps |  <p align="center"> - </p>   |  <code>[]</code> |


<a name="#verilog_rtl_shell_static"></a>

## verilog_rtl_shell_static

<pre>
verilog_rtl_shell_static(<a href="#verilog_rtl_shell_static-name">name</a>, <a href="#verilog_rtl_shell_static-module_to_shell_name">module_to_shell_name</a>, <a href="#verilog_rtl_shell_static-shell_module_label">shell_module_label</a>, <a href="#verilog_rtl_shell_static-deps">deps</a>)
</pre>

A prevously created RTL shell that is version controlled.

Use when a shell needs to be hand-edited after generation If
module_to_shell_name == 'custom', then all rules regarding shells are
ignored and gumi shell defines are not thrown, allowing the user great
power.


**PARAMETERS**


| Name  | Description | Default Value |
| :-------------: | :-------------: | :-------------: |
| name |  <p align="center"> - </p>   |  none |
| module_to_shell_name |  <p align="center"> - </p>   |  none |
| shell_module_label |  <p align="center"> - </p>   |  none |
| deps |  <p align="center"> - </p>   |  <code>[]</code> |


