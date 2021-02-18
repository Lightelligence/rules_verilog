<!-- Generated with Stardoc: http://skydoc.bazel.build -->

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


<a name="#ShellInfo"></a>

## ShellInfo

<pre>
ShellInfo(<a href="#ShellInfo-is_pkg">is_pkg</a>, <a href="#ShellInfo-is_shell_of">is_shell_of</a>, <a href="#ShellInfo-gumi_path">gumi_path</a>)
</pre>



**FIELDS**


| Name  | Description |
| :-------------: | :-------------: |
| is_pkg |  Indicates if this rtl_lib used the rtl_pkg rule    |
| is_shell_of |  Indicates if this rtl_lib represents a shell module    |
| gumi_path |  Short path to gumi file    |


<a name="#VerilogInfo"></a>

## VerilogInfo

<pre>
VerilogInfo(<a href="#VerilogInfo-transitive_sources">transitive_sources</a>, <a href="#VerilogInfo-transitive_flists">transitive_flists</a>, <a href="#VerilogInfo-transitive_dpi">transitive_dpi</a>, <a href="#VerilogInfo-last_module">last_module</a>)
</pre>



**FIELDS**


| Name  | Description |
| :-------------: | :-------------: |
| transitive_sources |  Source files    |
| transitive_flists |  Generated or built flists    |
| transitive_dpi |  Shared libraries to link in via dpi    |
| last_module |  Last module specified is assumed top    |


<a name="#flists_to_arguments"></a>

## flists_to_arguments

<pre>
flists_to_arguments(<a href="#flists_to_arguments-deps">deps</a>, <a href="#flists_to_arguments-provider">provider</a>, <a href="#flists_to_arguments-field">field</a>, <a href="#flists_to_arguments-prefix">prefix</a>, <a href="#flists_to_arguments-separator">separator</a>)
</pre>



**PARAMETERS**


| Name  | Description | Default Value |
| :-------------: | :-------------: | :-------------: |
| deps |  <p align="center"> - </p>   |  none |
| provider |  <p align="center"> - </p>   |  none |
| field |  <p align="center"> - </p>   |  none |
| prefix |  <p align="center"> - </p>   |  none |
| separator |  <p align="center"> - </p>   |  <code>""</code> |


<a name="#gather_shell_defines"></a>

## gather_shell_defines

<pre>
gather_shell_defines(<a href="#gather_shell_defines-shells">shells</a>)
</pre>



**PARAMETERS**


| Name  | Description | Default Value |
| :-------------: | :-------------: | :-------------: |
| shells |  <p align="center"> - </p>   |  none |


<a name="#get_transitive_srcs"></a>

## get_transitive_srcs

<pre>
get_transitive_srcs(<a href="#get_transitive_srcs-srcs">srcs</a>, <a href="#get_transitive_srcs-deps">deps</a>, <a href="#get_transitive_srcs-provider">provider</a>, <a href="#get_transitive_srcs-attr_name">attr_name</a>, <a href="#get_transitive_srcs-allow_other_outputs">allow_other_outputs</a>)
</pre>

Obtain the source files for a target and its transitive dependencies.

**PARAMETERS**


| Name  | Description | Default Value |
| :-------------: | :-------------: | :-------------: |
| srcs |  a list of source files   |  none |
| deps |  a list of targets that are direct dependencies   |  none |
| provider |  <p align="center"> - </p>   |  none |
| attr_name |  <p align="center"> - </p>   |  none |
| allow_other_outputs |  <p align="center"> - </p>   |  <code>False</code> |


