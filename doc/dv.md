<!-- Generated with Stardoc: http://skydoc.bazel.build -->

<a name="#dv_lib"></a>

## dv_lib

<pre>
dv_lib(<a href="#dv_lib-name">name</a>, <a href="#dv_lib-deps">deps</a>, <a href="#dv_lib-dpi">dpi</a>, <a href="#dv_lib-in_flist">in_flist</a>, <a href="#dv_lib-incdir">incdir</a>, <a href="#dv_lib-srcs">srcs</a>)
</pre>

An DV Library. Creates a generated flist file from a list of source files.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :-------------: | :-------------: | :-------------: | :-------------: | :-------------: |
| name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| deps |  -   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| dpi |  cc_libraries to link in through dpi   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| in_flist |  Files to be places in generated flist. Generally only the 'pkg' file and interfaces. If left blank, all srcs will be used.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| incdir |  Include an incdir to src file directories in generated flist.   | Boolean | optional | True |
| srcs |  -   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | required |  |


<a name="#dv_tb"></a>

## dv_tb

<pre>
dv_tb(<a href="#dv_tb-name">name</a>, <a href="#dv_tb-ccf">ccf</a>, <a href="#dv_tb-defines">defines</a>, <a href="#dv_tb-deps">deps</a>, <a href="#dv_tb-extra_compile_args">extra_compile_args</a>, <a href="#dv_tb-extra_runfiles">extra_runfiles</a>, <a href="#dv_tb-extra_runtime_args">extra_runtime_args</a>, <a href="#dv_tb-shells">shells</a>,
      <a href="#dv_tb-warning_waivers">warning_waivers</a>)
</pre>

A DV Testbench.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :-------------: | :-------------: | :-------------: | :-------------: | :-------------: |
| name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| ccf |  Coverage configuration file   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| defines |  Additional defines to throw for this testbench compile.   | <a href="https://bazel.build/docs/skylark/lib/dict.html">Dictionary: String -> String</a> | optional | {} |
| deps |  -   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | required |  |
| extra_compile_args |  Additional flags to throw to compile   | List of strings | optional | [] |
| extra_runfiles |  Additional files that need to be passed as runfiles to bazel. The generally should only be things referred to by extra_compile_args or extra_runtime_args   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| extra_runtime_args |  Additional flags to throw to simultation run   | List of strings | optional | [] |
| shells |  List of shells to use. Each shell thrown will create two defines:  <code>define gumi_&lt;module&gt; &lt;module&gt;_shell  </code>define gumi_use_&lt;module&gt;_shell The shell module declaration must be guarded by the gumi_use_&lt;module&gt;_shell define:  <code>ifdef gumi_use_&lt;module&gt;_shell     module &lt;module&gt;_shell(/*AUTOARGS*/);       ...     endmodule  </code>endif   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| warning_waivers |  Waive warnings in the compile. Converted to python regular expressions   | List of strings | optional | [] |


<a name="#dv_test_cfg"></a>

## dv_test_cfg

<pre>
dv_test_cfg(<a href="#dv_test_cfg-name">name</a>, <a href="#dv_test_cfg-abstract">abstract</a>, <a href="#dv_test_cfg-inherits">inherits</a>, <a href="#dv_test_cfg-no_run">no_run</a>, <a href="#dv_test_cfg-sim_opts">sim_opts</a>, <a href="#dv_test_cfg-sockets">sockets</a>, <a href="#dv_test_cfg-uvm_testname">uvm_testname</a>, <a href="#dv_test_cfg-vcomp">vcomp</a>)
</pre>

A DV test configuration. This is not a executable target.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :-------------: | :-------------: | :-------------: | :-------------: | :-------------: |
| name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| abstract |  This configuration is abstract. It is not intended to be excuted, but only to be used as a base for other test configurations.   | Boolean | optional | False |
| inherits |  Inherit configurations from dv_test_cfg targets. Entries later in the list will override arguements set by previous inherits entries. Any field explicily set in this rule will override values set through inheritance.   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | optional | [] |
| no_run |  Set to True to skip running this test.   | Boolean | optional | False |
| sim_opts |  Additional simopts flags to throw   | <a href="https://bazel.build/docs/skylark/lib/dict.html">Dictionary: String -> String</a> | optional | {} |
| sockets |  Dictionary mapping of socket_name to socket_command. For each entry in the list, simmer will create a separate process and pass a unique temporary file path to both the simulator and the socket_command. The socket name is a short identifier that will be passed as "+SOCKET__&lt;socket_name&gt;=&lt;socket_file&gt;" to the simulator. The socket_file is just a filepath to a temporary file in the simulation results directory (for uniqueness) The socket_command is a bash command that must use a python string formatter of "{socket_file}" somewhere in the command. The socket_command will be run from the root of the project tree.   | <a href="https://bazel.build/docs/skylark/lib/dict.html">Dictionary: String -> String</a> | optional | {} |
| uvm_testname |  UVM testname. If not set, finds from deps.   | String | optional | "" |
| vcomp |  Must point to a 'dv_tb' target for how to build this testbench.   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | None |


<a name="#dv_unit_test"></a>

## dv_unit_test

<pre>
dv_unit_test(<a href="#dv_unit_test-name">name</a>, <a href="#dv_unit_test-default_sim_opts">default_sim_opts</a>, <a href="#dv_unit_test-deps">deps</a>, <a href="#dv_unit_test-sim_args">sim_args</a>, <a href="#dv_unit_test-ut_sim_template">ut_sim_template</a>)
</pre>

Compiles and runs a small DV library. Additional sim options may be passed after --
    Interactive example:
      bazel run //digital/dv/interfaces/apb_pkg:test -- -gui
    For ci testing purposes:
      bazel test //digital/dv/interfaces/apb_pkg:test
    

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :-------------: | :-------------: | :-------------: | :-------------: | :-------------: |
| name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |  |
| default_sim_opts |  -   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | //:default_sim_opts.f |
| deps |  -   | <a href="https://bazel.build/docs/build-ref.html#labels">List of labels</a> | required |  |
| sim_args |  Additional simulation arguments to passed to command line   | List of strings | optional | [] |
| ut_sim_template |  -   | <a href="https://bazel.build/docs/build-ref.html#labels">Label</a> | optional | @verilog_tools//vendors/cadence:dv_unit_test_sim_template.sh |


<a name="#DVTBInfo"></a>

## DVTBInfo

<pre>
DVTBInfo(<a href="#DVTBInfo-ccf">ccf</a>)
</pre>



**FIELDS**


| Name  | Description |
| :-------------: | :-------------: |
| ccf |  Coverage config file    |


<a name="#DVTestInfo"></a>

## DVTestInfo

<pre>
DVTestInfo(<a href="#DVTestInfo-sim_opts">sim_opts</a>, <a href="#DVTestInfo-uvm_testname">uvm_testname</a>, <a href="#DVTestInfo-vcomp">vcomp</a>, <a href="#DVTestInfo-tags">tags</a>)
</pre>



**FIELDS**


| Name  | Description |
| :-------------: | :-------------: |
| sim_opts |  Simulation options    |
| uvm_testname |  UVM Test Name    |
| vcomp |  Label of type dv_tb    |
| tags |  Tags    |


<a name="#dv_tb_ccf_aspect"></a>

## dv_tb_ccf_aspect

<pre>
dv_tb_ccf_aspect(<a href="#dv_tb_ccf_aspect-name">name</a>)
</pre>



**ASPECT ATTRIBUTES**


| Name | Type |
| :-------------: | :-------------: |
| ccf| String |


**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :-------------: | :-------------: | :-------------: | :-------------: | :-------------: |
| name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |   |


<a name="#test_to_vcomp_aspect"></a>

## test_to_vcomp_aspect

<pre>
test_to_vcomp_aspect(<a href="#test_to_vcomp_aspect-name">name</a>)
</pre>



**ASPECT ATTRIBUTES**


| Name | Type |
| :-------------: | :-------------: |
| deps| String |
| tags| String |


**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :-------------: | :-------------: | :-------------: | :-------------: | :-------------: |
| name |  A unique name for this target.   | <a href="https://bazel.build/docs/build-ref.html#name">Name</a> | required |   |


