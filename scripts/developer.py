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
        return

    for patch_file in selected_patches:
        patch(patch_file, reverse=reverse)


# GUI Choicebox with options
choices = [
    "Reset workspace",
    "Check patches",
    "Set checkpoint",
    "Select patches",
    "Reverse patches",
    "Find broken patches",
    "See current workspace",
    "Write workspace to patch",
]

"""
GUI Choicebox
"""


def handle_choice(choice):
    match choice:
        case "Reset workspace":
            reset_camoufox()
            easygui.msgbox("Reset completed and bootstrap patches applied.", "Reset Complete")

        case "Check patches":
            # Produces a list of patches that are applied
            apply_dict = {}
            for patch_file in list_files('../patches', suffix='*.patch'):
                result = os.system(f'git apply --check "{patch_file}" > /dev/null 2>&1')
                if result == 0:
                    apply_dict[patch_file] = 'NOT APPLIED'
                else:
                    apply_dict[patch_file] = 'APPLIED'
            easygui.textbox(
                "Patching Result",
                "Patching Result",
                '\n'.join(
                    sorted(
                        (f'{v}\t{os.path.basename(k)[:-6]}' for k, v in apply_dict.items()),
                        reverse=True,
                        key=lambda x: x[0],
                    )
                ),
            )

        case "Set checkpoint":
            with temp_cd('..'):
                run('make checkpoint')
            easygui.msgbox("Checkpoint set.", "Checkpoint Set")

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

    while choice := easygui.choicebox("Select an option:", "Camoufox Dev Tools", choices):
        handle_choice(choice)
