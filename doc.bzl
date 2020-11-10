"""Rules to create exportable documentation."""

def _view_html_impl(ctx):
    content = [
        "#!/usr/bin/env bash",
        "# Convert path from relative bazel runfiles to absolute",
        "html_src=`pwd`/{}".format(ctx.files.srcs[0].short_path),
        #"echo $html_src",
        # "html_src={}".format(ctx.files.srcs[0].short_path),
        "# Firefox will follow symlinks and change directories which breaks linking images.",
        "# Cheap hack by just copying the src file to here",
        "cd $(dirname $html_src)",
        # "echo `pwd`",
        "cp {} view.html".format(ctx.files.srcs[0].basename),
        "chmod u+w view.html",
        # "ls -la",
        "firefox view.html &",
    ]
    ctx.actions.write(
        output = ctx.outputs.executable,
        content = "\n".join(content),
    )
    runfiles = ctx.runfiles(files = ctx.files.srcs + ctx.files.imgs)
    return DefaultInfo(runfiles = runfiles)

view_html = rule(
    doc = "Run firefox to view httml",
    implementation = _view_html_impl,
    attrs = {
        "srcs": attr.label(mandatory = True, allow_files = True),
        "imgs": attr.label_list(allow_files = True),
        "out": attr.output(),
    },
    executable = True,
)

# def markdown_to_html(name, srcs, imgs, hdr=None):
#     """Convert a markdown file to html for documentation export."""
#     if not name.endswith("_html"):
#         fail("markdown_to_html rules must have names ending in '_html'")
#     if len(srcs) != 1:
#         fail("markdown_to_html rules must have srcs as a singleton list")
#     if not srcs[0].endswith(".md"):
#         fail("markdown_to_html rules must have src with .md extension")

#     html_file = srcs[0].replace(".md", ".html")

#     native.genrule(
#         name = name,
#         srcs = srcs,
#         outs = [html_file],
#         cmd = "pandoc -f markdown -t html5 -o $@ -s -N $(SRCS) --toc",
#         visibility = ["//visibility:public"],
#         tags = ["doc_export"],
#     )

#     native.filegroup(
#         name = name + "_imgs",
#         srcs = imgs,
#         visibility = ["//visibility:public"],
#         tags = ["doc_export"],
#     )

#     view_html(
#         name = "view_{}".format(name),
#         srcs = ":{}".format(html_file),
#         imgs = imgs,
#     )

def markdown_to_html(name, srcs, imgs, html_file):
    """Convert a markdown file to html for documentation export."""
    # if not name.endswith("_html"):
    #     fail("markdown_to_html rules must have names ending in '_html'")
    # if len(srcs) != 1:
    #     fail("markdown_to_html rules must have srcs as a singleton list")
    # if not srcs[0].endswith(".md"):
    #     fail("markdown_to_html rules must have src with .md extension")

    # html_file = srcs[0].replace(".md", ".html")

    style = "{name}_style".format(name = name)

    native.filegroup(
        name = style,
        srcs = [],#"//env:style.html"],
        visibility = ["//visibility:public"],
        tags = ["doc_export"],
    )

    cmd = "pandoc -f markdown -t html5 -o $@ -s -N $(SRCS) --toc --section-divs"

    native.genrule(
        name = name,
        srcs = srcs + [style],
        outs = [html_file],
        cmd = cmd,
        visibility = ["//visibility:public"],
        tags = ["doc_export"],
    )

    native.filegroup(
        name = name + "_imgs",
        srcs = imgs,
        visibility = ["//visibility:public"],
        tags = ["doc_export"],
    )

    view_html(
        name = "view_{}".format(name),
        srcs = ":{}".format(html_file),
        imgs = imgs,
    )
