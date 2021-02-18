#!/usr/bin/env bash
# Check that the documentation has been regenerated
# This must be executed from the top of the project

declare -i result=0

# Regenerate documentation
bazel build //doc/...
result+=$?

# Compare each .md file generated in bazel-bin
for bazel_bin_file in bazel-bin/doc/*.md
do
    static_file=`echo "$bazel_bin_file" | sed -e "s/^bazel-bin\///"`
    echo "diff $bazel_bin_file $static_file"
    diff $bazel_bin_file $static_file
    result+=$?
done

exit $result
