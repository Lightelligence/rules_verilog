<!-- Generated with Stardoc: http://skydoc.bazel.build -->

<a name="#verilog_dv_library"></a>

## verilog_dv_library

<pre>
verilog_dv_library(<a href="#verilog_dv_library-name">name</a>, <a href="#verilog_dv_library-deps">deps</a>, <a href="#verilog_dv_library-dpi">dpi</a>, <a href="#verilog_dv_library-in_flist">in_flist</a>, <a href="#verilog_dv_library-incdir">incdir</a>, <a href="#verilog_dv_library-srcs">srcs</a>)
</pre>

A DV Library.
    
    Creates a generated flist file from a list of source files.
    

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :-------------: | :-------------: | :-------------: | :-------------: | :-------------: |
| name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| deps |  verilog_dv_library targets that this target is dependent on.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| dpi |  cc_libraries to link in through the DPI. Currently, cc_import is not support for precompiled shared libraries.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| in_flist |  Files to be placed directly in the generated flist. Best practice recommends 'pkg' and 'interface' files be declared here. If this entry is empty (default), all srcs will put into the flist instead.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| incdir |  Generate a +incdir in generated flist for every file's directory declared in 'srcs' attribute.   | Boolean | optional | True |
| srcs |  Systemverilog source files. Files are assumed to be <code>included inside another file (i.e. the package file) and will not be placed on directly in the flist unless declared in the 'in_flist' attribute.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | required |  |


<a name="#verilog_dv_tb"></a>

## verilog_dv_tb

<pre>
verilog_dv_tb(<a href="#verilog_dv_tb-name">name</a>, <a href="#verilog_dv_tb-ccf">ccf</a>, <a href="#verilog_dv_tb-defines">defines</a>, <a href="#verilog_dv_tb-deps">deps</a>, <a href="#verilog_dv_tb-extra_compile_args">extra_compile_args</a>, <a href="#verilog_dv_tb-extra_runfiles">extra_runfiles</a>, <a href="#verilog_dv_tb-extra_runtime_args">extra_runtime_args</a>,
              <a href="#verilog_dv_tb-shells">shells</a>, <a href="#verilog_dv_tb-warning_waivers">warning_waivers</a>)
</pre>

A DV Testbench.
    
    To strongly differentiate between a compilation and a simulation, there
    exist separate rules: verilog_dv_tb and verilog_dv_test_cg respectively.

    A verilog_dv_tb describes how to compile a testbench. It is not a
    standalone executable rule by bazel. It is intended to provide simmer (a
    higher level simulation spawning tool) hooks to execute the compile and
    subsequent simulations.
    

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :-------------: | :-------------: | :-------------: | :-------------: | :-------------: |
| name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| ccf |  Coverage configuration file to provider to simmer.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| defines |  Additional preprocessor defines to throw for this testbench compile. Key, value pairs are joined without additional characters. If it is a unary flag, set the value portion to be the empty string. For binary flags, add an '=' as a suffix to the key.   | <a href="https://bazel.build/docs/skylark/lib/dict.html">Dictionary: String -> String</a> | optional | {} |
| deps |  verilog_dv_library or verilog_rtl_library labels that the testbench is dependent on. Ordering should not matter here if dependencies are consistently declared in all other rules.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | required |  |
| extra_compile_args |  Additional flags to throw to pass to the compile.   | List of strings | optional | [] |
| extra_runfiles |  Additional files that need to be passed as runfiles to bazel. Most commonly it is used for files referred to by extra_compile_args or extra_runtime_args.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| extra_runtime_args |  Additional flags to throw to simulation run. These flags will not be provided to the compilation, but only to subsequent simulation invocations.   | List of strings | optional | [] |
| shells |  List of shells to use. Each label must be a verilog_rtl_shell instance. Each shell thrown will create two defines:  <code>define gumi_{module} {module}_shell  </code>define gumi_use_{module}_shell The shell module declaration must be guarded by the gumi_use_{module}_shell define:  <code>ifdef gumi_use_{module}_shell     module {module}_shell(/*AUTOARGS*/);       ...     endmodule  </code>endif   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| warning_waivers |  Waive warnings in the compile. By default, simmer promotes all compile warnings to errors. This list is converted to python regular expressions which are imported by simmer to waive warning. All warnings may be waived by using '\*W'   | List of strings | optional | [] |


<a name="#verilog_dv_test_cfg"></a>

## verilog_dv_test_cfg

<pre>
verilog_dv_test_cfg(<a href="#verilog_dv_test_cfg-name">name</a>, <a href="#verilog_dv_test_cfg-abstract">abstract</a>, <a href="#verilog_dv_test_cfg-inherits">inherits</a>, <a href="#verilog_dv_test_cfg-no_run">no_run</a>, <a href="#verilog_dv_test_cfg-sim_opts">sim_opts</a>, <a href="#verilog_dv_test_cfg-sockets">sockets</a>, <a href="#verilog_dv_test_cfg-tb">tb</a>, <a href="#verilog_dv_test_cfg-uvm_testname">uvm_testname</a>)
</pre>

A DV test configuration.

    This is not a executable target. It generates multiple files which may then
    be used by simmer (the wrapping tool to invoke the simulator).
    

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :-------------: | :-------------: | :-------------: | :-------------: | :-------------: |
| name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| abstract |  When True, this configuration is abstract and does not represent a complete configuration. It is not intended to be executed, but only to be used as a base for other test configurations to inherit from. See inherits attribute.   | Boolean | optional | False |
| inherits |  Inherit configurations from other verilog_dv_test_cfg targets. Entries later in the list will override arguments set by previous inherits entries. Only attributes noted as inheritable in documentation may be inherited. Any field explicitly set in this rule will override values set via inheritance.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| no_run |  Set to True to skip running this test. This flag is not used by bazel but is used as a query filter by simmer.TODO: Deprecate this flag in favor of using built-in tags.   | Boolean | optional | False |
| sim_opts |  Additional simulation options. These are 'runtime' arguments. Preprocessor or compiler directives will not take effect. The key, value pairs are joined without additional characters. If it is a unary flag, set the value portion to be the empty string. For binary flags, add an '=' as a suffix to the key. This attribute is inheritable. See 'inherits' attribute. Unlike other inheritable attributes, simopts are not entirely overridden. Instead, the dictionary is 'updated' with new values at each successive level. This allows for the override of individual simopts for finer grain control.   | <a href="https://bazel.build/docs/skylark/lib/dict.html">Dictionary: String -> String</a> | optional | {} |
| sockets |  Dictionary mapping of socket_name to socket_command. Simmer has the ability to spawn parallel processes to the primary simulation that are connected via sockets. For each entry in the list, simmer will create a separate process and pass a unique temporary file path to both the simulator and the socket_command. The socket name is a short identifier that will be passed as "+SOCKET__&lt;socket_name&gt;=&lt;socket_file&gt;" to the simulator. The socket_file is just a file path to a temporary file in the simulation results directory (for uniqueness) .The socket_command is a bash command that must use a python string formatter of "{socket_file}" somewhere in the command. The socket_command will be run from the root of the project tree.   | <a href="https://bazel.build/docs/skylark/lib/dict.html">Dictionary: String -> String</a> | optional | {} |
| tb |  The testbench to run this test on. This label must be a 'verilog_dv_tb' target.This attribute is inheritable. See 'inherits' attribute. Future: Allow tb to be a list of labels to allow a test to run on multiple verilog_dv_tb   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | None |
| uvm_testname |  UVM testname eventually passed to simulator via plusarg +UVM_TESTNAME. This attribute is inheritable. See 'inherits' attribute.   | String | optional | "" |


<a name="#verilog_dv_unit_test"></a>

## verilog_dv_unit_test

<pre>
verilog_dv_unit_test(<a href="#verilog_dv_unit_test-name">name</a>, <a href="#verilog_dv_unit_test-default_sim_opts">default_sim_opts</a>, <a href="#verilog_dv_unit_test-deps">deps</a>, <a href="#verilog_dv_unit_test-sim_args">sim_args</a>, <a href="#verilog_dv_unit_test-ut_sim_template">ut_sim_template</a>)
</pre>

Compiles and runs a small unit test for DV.
    
    Typically a single verilog_dv_library (and its dependencies).
    Additional sim options may be passed after --
    Interactive example:
      bazel run //digital/dv/interfaces/apb_pkg:test -- -gui
    For ci testing purposes:
      bazel test //digital/dv/interfaces/apb_pkg:test
    

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :-------------: | :-------------: | :-------------: | :-------------: | :-------------: |
| name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| default_sim_opts |  Default simulator options to be passed in to the simulation.   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | @verilog_tools//vendors/cadence:verilog_dv_default_sim_opts.f |
| deps |  verilog_dv_library or verilog_rtl_library labels that the testbench is dependent on. Ordering should not matter here if dependencies are consistently declared in all other rules.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | required |  |
| sim_args |  Additional arguments to passed to command line to the simulator. Both compile and runtime arguments are allowed (single step flow).   | List of strings | optional | [] |
| ut_sim_template |  The template to generate the bash script to run the simulation.   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | @verilog_tools//vendors/cadence:verilog_dv_unit_test.sh.template |


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


<a name="#verilog_test"></a>

## verilog_test

<pre>
verilog_test(<a href="#verilog_test-name">name</a>, <a href="#verilog_test-data">data</a>, <a href="#verilog_test-deps">deps</a>, <a href="#verilog_test-post_flist_args">post_flist_args</a>, <a href="#verilog_test-pre_flist_args">pre_flist_args</a>, <a href="#verilog_test-shells">shells</a>, <a href="#verilog_test-tool">tool</a>)
</pre>

Provides a way to run a test against a set of libs.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :-------------: | :-------------: | :-------------: | :-------------: | :-------------: |
| name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| data |  None-verilog dependencies   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| deps |  -   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | required |  |
| post_flist_args |  commands and arguments after flist arguments   | List of strings | optional | [] |
| pre_flist_args |  commands and arguments before flist arguments   | List of strings | optional | [] |
| shells |  -   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| tool |  Label to a single tool to run. Inserted at before pre_flist_args if set. Do not duplicate in pre_flist_args   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | None |


<a name="#verilog_tool_encapsulation"></a>

## verilog_tool_encapsulation

<pre>
verilog_tool_encapsulation(<a href="#verilog_tool_encapsulation-name">name</a>)
</pre>



**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :-------------: | :-------------: | :-------------: | :-------------: | :-------------: |
| name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |


