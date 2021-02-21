#!/usr/bin/env bash
# Check that the documentation has been regenerated
# This must be executed from the top of the project

do_regenerate=0

while (( $# ))
do
    case $1 in
        "--regenerate" )
            do_regenerate=1
            ;;
        *)
            echo $arg
            echo "Unexpected Command Line Input - Exiting"
            exit 1
            ;;    
    esac
    shift
done

declare -i result=0

# Regenerate documentation
bazel build //docs/...
result=$(($? | $result))

# Compare each .md file generated in bazel-bin
for bazel_bin_file in bazel-bin/docs/*.md
do
    static_file=`echo "$bazel_bin_file" | sed -e "s/^bazel-bin\///"`
    if [ $do_regenerate -eq 1 ]
    then
        cp $bazel_bin_file $static_file
        chmod +w $static_file
    else
        echo "diff $bazel_bin_file $static_file"
        diff $bazel_bin_file $static_file
        result=$(($? | $result))
    fi
done

exit $result
