#!/usr/bin/env python3

"""
GUI for managing Camoufox patches.
"""

import os
import contextlib

import easygui
from patch import list_files, patch, run


def into_camoufox_dir():
    """Find and cd to the camoufox-* folder (this is located ..)"""
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    folders = os.listdir('.')
    for folder in folders:
        if os.path.isdir(folder) and folder.startswith('camoufox-'):
            os.chdir(folder)
            break
    else:
        raise FileNotFoundError('No camoufox-* folder found')


@contextlib.contextmanager
def temp_cd(path):
    # Temporarily change to a different working directory
    _old_cwd = os.getcwd()
    os.chdir(os.path.abspath(path))

    try:
        yield
    finally:
        os.chdir(_old_cwd)


def reset_camoufox():
    with temp_cd('..'):
        run('make clean')


def run_patches(reverse=False):
    patch_files = list(list_files('../patches', suffix='*.patch'))
    if reverse:
        title = "Unpatch files"
    else:
        title = "Patch files"
    selected_patches = easygui.multchoicebox(title, "Patches", patch_files)
    if not selected_patches:
        exit()

    for patch_file in selected_patches:
        patch(patch_file, reverse=reverse)


# GUI Choicebox with options
choices = [
    "Reset workspace",
    "Select patches",
    "Reverse patches",
    "Find broken patches",
    "See current workspace",
    "Write workspace to patch",
]

"""
GUI Choicebox with the following options:
- Reset:
    `make clean`
- Patch all BUT:
    Checklist of *.patch files in ../patches to exclude. The rest gets patched.
- Find broken:
    Resets, runs patches, then finds broken patches.
    If all show good error code, show at the top of the message box "All patches applied successfully"
    If any show bad error code, show at the top of the message box "Some patches failed to apply", then the rej output
"""


def handle_choice(choice):
    match choice:
        case "Reset workspace":
            reset_camoufox()
            easygui.msgbox("Reset completed and bootstrap patches applied.", "Reset Complete")

        case "Select patches":
            run_patches(reverse=False)
            easygui.msgbox("Patching completed.", "Patching Complete")

        case "Reverse patches":
            run_patches(reverse=True)
            easygui.msgbox("Unpatching completed.", "Unpatching Complete")

        case "Find broken patches":
            reset_camoufox()

            broken_patches = []
            for patch_file in list_files('../patches', suffix='*.patch'):
                cmd = rf'patch -p1 -i "{patch_file}" | tee /dev/stderr | sed -r --quiet \'s/^.*saving rejects to file (.*\.rej)$/\\1/p\''
                result = os.popen(cmd).read().strip()
                print(result)
                if result:
                    broken_patches.append((patch_file, result))

            if not broken_patches:
                easygui.msgbox("All patches applied successfully", "Patching Result")
            else:
                message = "Some patches failed to apply:\n\n"
                for patch_file, rejects in broken_patches:
                    message += f"Patch: {patch_file}\nRejects: {rejects}\n\n"
                easygui.textbox("Patching Result", "Failed Patches", message)

        case "See current workspace":
            result = os.popen('git diff').read()
            easygui.textbox("Diff", "Diff", result)

        case "Write workspace to patch":
            # Open a file dialog to select a file to write the diff to
            file_path = easygui.filesavebox(
                "Select a file to write the diff to", "Write Diff", filetypes="*.patch"
            )
            if not file_path:
                exit()
            run(f'git diff > {file_path}')
            easygui.msgbox("Diff written to file", "Diff Written")

        case _:
            print('No choice selected')


if __name__ == "__main__":
    into_camoufox_dir()

    choice = easygui.choicebox("Select an option:", "Camoufox Dev Tools", choices)
    handle_choice(choice)
