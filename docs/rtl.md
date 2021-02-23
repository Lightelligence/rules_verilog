<!-- Generated with Stardoc: http://skydoc.bazel.build -->

<a name="#verilog_rtl_cdc_test"></a>

## verilog_rtl_cdc_test

<pre>
verilog_rtl_cdc_test(<a href="#verilog_rtl_cdc_test-name">name</a>, <a href="#verilog_rtl_cdc_test-bash_template">bash_template</a>, <a href="#verilog_rtl_cdc_test-bbox">bbox</a>, <a href="#verilog_rtl_cdc_test-cmd_file">cmd_file</a>, <a href="#verilog_rtl_cdc_test-defines">defines</a>, <a href="#verilog_rtl_cdc_test-deps">deps</a>, <a href="#verilog_rtl_cdc_test-shells">shells</a>, <a href="#verilog_rtl_cdc_test-top">top</a>)
</pre>

Run Jaspergold CDC on a verilog_rtl_library.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :-------------: | :-------------: | :-------------: | :-------------: | :-------------: |
| name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| bash_template |  The template for the generated bash script which will run the case.   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | //vendors/cadence:verilog_rtl_cdc_test.sh.template |
| bbox |  List of modules to black box   | List of strings | optional | [] |
| cmd_file |  A tcl file containing commands to run in JG   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | required |  |
| defines |  List of additional <code>defines for this cdc run   | List of strings | optional | [] |
| deps |  Other verilog libraries this target is dependent upon. All Labels specified here must provide a VerilogInfo provider.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | required |  |
| shells |  List of verilog_rtl_shell Labels. For each Label, a gumi define will be placed on the command line to use this shell instead of the original module. This requires that the original module was instantiated using <code>gumi_&lt;module_name&gt; instead of just &lt;module_name&gt;.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| top |  The name of the top module   | String | required |  |


<a name="#verilog_rtl_library"></a>

## verilog_rtl_library

<pre>
verilog_rtl_library(<a href="#verilog_rtl_library-name">name</a>, <a href="#verilog_rtl_library-deps">deps</a>, <a href="#verilog_rtl_library-direct">direct</a>, <a href="#verilog_rtl_library-enable_gumi">enable_gumi</a>, <a href="#verilog_rtl_library-gumi_file_override">gumi_file_override</a>, <a href="#verilog_rtl_library-gumi_override">gumi_override</a>, <a href="#verilog_rtl_library-headers">headers</a>,
                    <a href="#verilog_rtl_library-is_pkg">is_pkg</a>, <a href="#verilog_rtl_library-is_shell_of">is_shell_of</a>, <a href="#verilog_rtl_library-lib_files">lib_files</a>, <a href="#verilog_rtl_library-modules">modules</a>, <a href="#verilog_rtl_library-no_synth">no_synth</a>)
</pre>

A collection of RTL design files. Creates a generated flist file to be included later in a compile.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :-------------: | :-------------: | :-------------: | :-------------: | :-------------: |
| name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| deps |  Other verilog libraries this target is dependent upon. All Labels specified here must provide a VerilogInfo provider.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| direct |  Verilog files that must be put directly onto the command line. Avoid using 'direct' with preference towards 'modules'.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| enable_gumi |  When set, create an additional file creating default preprocessor values for the gumi system.   | Boolean | optional | True |
| gumi_file_override |  Allow a more elaborate default set of gumi defines by pointing to another Label or file. Useful for creating a per-instance instead of per-type modules which require additional information.   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | None |
| gumi_override |  A list of strings of module names to create gumi defines. If empty (default), the modules variable is used instead. Useful when using 'direct' or 'lib_files' or to limit the defines created when using a glob in 'modules'   | List of strings | optional | [] |
| headers |  Files that will be included into other files. A '+incdir' flag will be added for each source file's directory.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| is_pkg |  INTERNAL: Do not set in verilog_rtl_library instances. Used for internal bookkeeping for macros derived from verilog_rtl_library. Used to enforce naming conventions related to packages to encourage simple dependency graphs   | Boolean | optional | False |
| is_shell_of |  INTERNAL: Do not set in verilog_rtl_library instances. Used for internal bookkeeping for macros derived from verilog_rtl_library. If set, this library is represents a 'shell' of another module. Allows downstream test rules to specify this Label as a 'shell' to override another instance via the gumi system.   | String | optional | "" |
| lib_files |  Verilog library files containing multiple modules. A '-v' flag will be added for each file in this attribute. It is preferable to used the 'modules' attribute when possible because library files require reading in entirely to discover all modules.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| modules |  Files containing a single module which matches the filename may be found via library. A '-y' flag will be added for each source file's directory. This is the preferred mechanism for specifying RTL modules.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| no_synth |  When True, do not allow the content of this library to be exposed to synthesis. TODO: This currently enforced via an Aspect which is not included in this repository. The aspect creates a parallel set of 'synth__*.f' which have the filtered views which are passed to the synthesis tool.   | Boolean | optional | False |


<a name="#verilog_rtl_lint_test"></a>

## verilog_rtl_lint_test

<pre>
verilog_rtl_lint_test(<a href="#verilog_rtl_lint_test-name">name</a>, <a href="#verilog_rtl_lint_test-defines">defines</a>, <a href="#verilog_rtl_lint_test-deps">deps</a>, <a href="#verilog_rtl_lint_test-design_info">design_info</a>, <a href="#verilog_rtl_lint_test-lint_parser">lint_parser</a>, <a href="#verilog_rtl_lint_test-rulefile">rulefile</a>, <a href="#verilog_rtl_lint_test-shells">shells</a>, <a href="#verilog_rtl_lint_test-top">top</a>,
                      <a href="#verilog_rtl_lint_test-waiver_hack">waiver_hack</a>)
</pre>

Compile and run lint on target

    This rule was written for Cadence HAL to be run under xcelium. As such, it
    is not entirely generic. It also uses a log post-processor
    (lint_parser_hal.py) to allow for easier waiving of warnings.

    The DUT must have no unwaived warning/errors in order for this rule to
    pass. The intended philosophy is for blocks to maintain a clean lint status
    throughout the lifecycle of the project, not to run lint as a checklist
    item towards the end of the project.

    

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :-------------: | :-------------: | :-------------: | :-------------: | :-------------: |
| name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| defines |  List of additional <code>defines for this lint run   | <a href="https://bazel.build/docs/skylark/lib/dict.html">Dictionary: String -> String</a> | optional | {} |
| deps |  Other verilog libraries this target is dependent upon. All Labels specified here must provide a VerilogInfo provider.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | required |  |
| design_info |  A Cadence design info file to add additional lint rule/waivers   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| lint_parser |  Post processor for lint logs allowing for easier waiving of warnings.   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | @verilog_tools//:lint_parser_hal |
| rulefile |  The Cadence rulefile for HAL. Suggested one per project. Example: https://github.com/freecores/t6507lp/blob/ca7d7ea779082900699310db459a544133fe258a/lint/run/hal.def   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | required |  |
| shells |  List of verilog_rtl_shell Labels. For each Label, a gumi define will be placed on the command line to use this shell instead of the original module. This requires that the original module was instantiated using <code>gumi_&lt;module_name&gt; instead of just &lt;module_name&gt;.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| top |  The name of the top module.   | String | required |  |
| waiver_hack |  Lint waiver python regex to hack around cases when HAL has formatting errors in xrun.log.xml that cause problems for our lint parser   | String | optional | "" |


<a name="#verilog_rtl_unit_test"></a>

## verilog_rtl_unit_test

<pre>
verilog_rtl_unit_test(<a href="#verilog_rtl_unit_test-name">name</a>, <a href="#verilog_rtl_unit_test-data">data</a>, <a href="#verilog_rtl_unit_test-deps">deps</a>, <a href="#verilog_rtl_unit_test-post_flist_args">post_flist_args</a>, <a href="#verilog_rtl_unit_test-pre_flist_args">pre_flist_args</a>, <a href="#verilog_rtl_unit_test-shells">shells</a>, <a href="#verilog_rtl_unit_test-ut_sim_template">ut_sim_template</a>)
</pre>

Compile and simulate a verilog_rtl_library.

    Allows a designer to write small unit/directed tests which can be included in regression.

    This rule is capable of running SVUnit regressions as well. See ut_sim_template attribute.

    Additional sim options may be passed after --.

    Typically, an additional verilog_rtl_library containing 'unit_test_top.sv'
    is created. This unit_test_top will be dependent on the DUT top, and will
    be the only dep provided to verilog_rtl_unit_test.
    

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :-------------: | :-------------: | :-------------: | :-------------: | :-------------: |
| name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| data |  Non-verilog dependencies. Useful when reading in data files as stimulus/prediction.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| deps |  Other verilog libraries this target is dependent upon. All Labels specified here must provide a VerilogInfo provider.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | required |  |
| post_flist_args |  Additional command line arguments to be placed after the flist arguments See ut_sim_template attribute for exact layout.   | List of strings | optional | [] |
| pre_flist_args |  Additional command line arguments to be placed after the simulator binary but before the flist arguments. See ut_sim_template attribute for exact layout.For defines to have effect, they must be declared in pre_flist_args not post_flist_args.   | List of strings | optional | [] |
| shells |  List of verilog_rtl_shell Labels. For each Label, a gumi define will be placed on the command line to use this shell instead of the original module. This requires that the original module was instantiated using <code>gumi_&lt;module_name&gt; instead of just &lt;module_name&gt;.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| ut_sim_template |  The template to generate the script to run the test. Also available is a [SVUnit](http://agilesoc.com/open-source-projects/svunit/) test template: @verilog_tools//vendors/cadence:verilog_rtl_unit_test_svunit.sh.template If using the SVUnit template, you may also want to throw: <pre><code>    post_flist_args = [     "--directory &lt;path_to_test_directory_from_workspace&gt;",  ],</code></pre>   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | @verilog_tools//vendors/cadence:verilog_rtl_unit_test.sh.template |


<a name="#verilog_rtl_pkg"></a>

## verilog_rtl_pkg

<pre>
verilog_rtl_pkg(<a href="#verilog_rtl_pkg-name">name</a>, <a href="#verilog_rtl_pkg-direct">direct</a>, <a href="#verilog_rtl_pkg-no_synth">no_synth</a>, <a href="#verilog_rtl_pkg-deps">deps</a>)
</pre>

A single Systemverilog package.

This rule is a specialized case of verilog_rtl_library. Systemverilog
packages should be placed into their own rule instance to limit cross
dependencies. In general, a block may depend on another block's package but
should not need to depend on all the modules in the block.


**PARAMETERS**


| Name  | Description | Default Value |
| :-------------: | :-------------: | :-------------: |
| name |  A unique name for this target.   |  none |
| direct |  The Systemverilog file containing the package.<br><br>  See verilog_rtl_library::direct.   |  none |
| no_synth |  Default False.<br><br>  See verilog_rtl_library::no_synth.   |  <code>False</code> |
| deps |  Other packages this target is dependent on.<br><br>  See verilog_rtl_library::deps.   |  <code>[]</code> |


<a name="#verilog_rtl_shell"></a>

## verilog_rtl_shell

<pre>
verilog_rtl_shell(<a href="#verilog_rtl_shell-name">name</a>, <a href="#verilog_rtl_shell-module_to_shell_name">module_to_shell_name</a>, <a href="#verilog_rtl_shell-shell_module_label">shell_module_label</a>, <a href="#verilog_rtl_shell-deps">deps</a>)
</pre>

A RTL shell has the same ports as another module.

This rule is a specialized case of verilog_rtl_library.
A 'shell' is similar to a 'stub' (empty module), but a shell may contain
limited functionality. Frequent uses include:
  * Blackboxing hierarchy that will not be the target of testing
  * Replacing functionality with a simpler model (simulation-only memory models)


**PARAMETERS**


| Name  | Description | Default Value |
| :-------------: | :-------------: | :-------------: |
| name |  A unique name for this target.   |  none |
| module_to_shell_name |  The name of the module that will be replaced.<br><br>  When a downstream test uses this 'shell', a gumi define will be created using this name.<br><br>  When a shell needs to be hand-edited after generation If   module_to_shell_name == 'custom', then all rules regarding shells are   ignored and gumi shell defines are not thrown, allowing the user great   power.   |  none |
| shell_module_label |  The Label or file containing the shell.<br><br>  See verilog_rtl_library::no_synth.   |  none |
| deps |  Other packages this target is dependent on.<br><br>  In general. shells should avoid having dependencies. Exceptions include   necessary packages and possible a DV model to implement functional   behavior.<br><br>  See verilog_rtl_library::deps.   |  <code>[]</code> |

