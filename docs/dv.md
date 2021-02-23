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

    A verilog_dv_tb describes how to compile a testbench.
    

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
| shells |  List of shells to use. Each label must be a verilog_rtl_shell instance. Each shell thrown will create two defines:  <code>define gumi_&lt;module&gt; &lt;module&gt;_shell  </code>define gumi_use_&lt;module&gt;_shell The shell module declaration must be guarded by the gumi_use_&lt;module&gt;_shell define:  <code>ifdef gumi_use_&lt;module&gt;_shell     module &lt;module&gt;_shell(/*AUTOARGS*/);       ...     endmodule  </code>endif   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| warning_waivers |  Waive warnings in the compile. By default, simmer promotes all compile warnings to errors. This list is converted to python regular expressions which are imported by simmer to waive warning. All warnings may be waived by using '\*W'   | List of strings | optional | [] |


<a name="#verilog_dv_test_cfg"></a>

## verilog_dv_test_cfg

<pre>
verilog_dv_test_cfg(<a href="#verilog_dv_test_cfg-name">name</a>, <a href="#verilog_dv_test_cfg-abstract">abstract</a>, <a href="#verilog_dv_test_cfg-inherits">inherits</a>, <a href="#verilog_dv_test_cfg-no_run">no_run</a>, <a href="#verilog_dv_test_cfg-sim_opts">sim_opts</a>, <a href="#verilog_dv_test_cfg-sockets">sockets</a>, <a href="#verilog_dv_test_cfg-uvm_testname">uvm_testname</a>, <a href="#verilog_dv_test_cfg-vcomp">vcomp</a>)
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
| uvm_testname |  UVM testname eventually passed to simulator via plusarg +UVM_TESTNAME. This attribute is inheritable. See 'inherits' attribute.   | String | optional | "" |
| vcomp |  The testbench to run this test on. This label must be a 'verilog_dv_tb' target.This attribute is inheritable. See 'inherits' attribute. Future: Allow vcomp to be a list of labels to allow a test to run on multiple verilog_dv_tb   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | None |


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


<a name="#DVTBInfo"></a>

## DVTBInfo

<pre>
DVTBInfo(<a href="#DVTBInfo-ccf">ccf</a>)
</pre>



**FIELDS**


| Name  | Description |
| :-------------: | :-------------: |
| ccf |  Coverage config file.    |


<a name="#DVTestInfo"></a>

## DVTestInfo

<pre>
DVTestInfo(<a href="#DVTestInfo-sim_opts">sim_opts</a>, <a href="#DVTestInfo-uvm_testname">uvm_testname</a>, <a href="#DVTestInfo-vcomp">vcomp</a>, <a href="#DVTestInfo-tags">tags</a>)
</pre>



**FIELDS**


| Name  | Description |
| :-------------: | :-------------: |
| sim_opts |  Simulation options to carry forward.    |
| uvm_testname |  UVM Test Name; passed to simulator via plusarg +UVM_TESTNAME.    |
| vcomp |  The verilog compile associated with this test. Must be a Label of type verilog_dv_tb.    |
| tags |  Additional tags to be able to filter in simmer.    |


<a name="#test_to_vcomp_aspect"></a>

## test_to_vcomp_aspect

<pre>
test_to_vcomp_aspect(<a href="#test_to_vcomp_aspect-name">name</a>)
</pre>

Find test to tb/vcomp and tag mappings in simmer.

**ASPECT ATTRIBUTES**


| Name | Type |
| :-------------: | :-------------: |
| deps| String |
| tags| String |


**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :-------------: | :-------------: | :-------------: | :-------------: | :-------------: |
| name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |   |


<a name="#verilog_dv_tb_ccf_aspect"></a>

## verilog_dv_tb_ccf_aspect

<pre>
verilog_dv_tb_ccf_aspect(<a href="#verilog_dv_tb_ccf_aspect-name">name</a>)
</pre>

Find test to find ccf file mappings simmer.

**ASPECT ATTRIBUTES**


| Name | Type |
| :-------------: | :-------------: |
| ccf| String |


**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :-------------: | :-------------: | :-------------: | :-------------: | :-------------: |
| name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |   |


