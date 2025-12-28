#!/usr/bin/env python3

"""
GUI for managing Camoufox patches.
"""
import os
import re
import sys
import easygui

from _mixin import find_src_dir, is_bootstrap_patch, list_patches, patch, run, temp_cd


def into_camoufox_dir():
    """Cd to the camoufox-* folder"""
    this_script = os.path.dirname(os.path.abspath(__file__))
    # Go one directory up from the current script path
    os.chdir(os.path.dirname(this_script))
    os.chdir(find_src_dir('.', version=sys.argv[1], release=sys.argv[2]))


def reset_camoufox():
    """Reset the Camoufox source"""
    with temp_cd('..'):
        run('make revert')
    run('touch _READY')


def run_patches(reverse=False):
    """Apply patches"""
    patch_files = list_patches()

    # Create a display list with status labels and a reverse lookup mapping
    display_choices = []
    mapping = {}
    for patch_file in patch_files:
        # If the patch is a bootstrap patch, mark it with the appropriate label
        if is_bootstrap_patch(patch_file):
            status = "BOOTSTRAP"
        else:
            can_apply, can_reverse, broken = check_patch(patch_file)
            if broken:
                status = "BROKEN"
            elif can_reverse:
                status = "APPLIED"
            elif can_apply:
                status = "NOT APPLIED"
            else:
                status = "UNKNOWN"
        # Format the display string (remove the '../patches/' prefix)
        display_name = f"[{status}] {patch_file[len('../patches/'):].strip()}"
        display_choices.append(display_name)
        mapping[display_name] = patch_file

    title = "Unpatch files" if reverse else "Patch files"
    selected_display = easygui.multchoicebox(title, "Patches", display_choices, preselect=[])
    if not selected_display:
        return False

    # Convert the selected items back to filenames
    for display_name in selected_display:
        patch_file = mapping[display_name]
        patch(patch_file, reverse=reverse)
    return True

def open_patch_workspace(selected_patch, stop_at_patch=False):
    """
    Resets a workspace for editing a patch.

    Process:
    1. Resets Camoufox
    2. Patches all except the selected patch
    3. Sets checkpoint
    4. Reruns the selected patch, but reads rejects similar to "Find broken patches"
    """
    # Prepare UI
    patch_files = list_patches()

    # Reset workspace
    reset_camoufox()

    skipped_patches = []
    applied_patches = []
    # Patch all except the selected patch
    for patch_file in patch_files:
        if patch_file == selected_patch:
            if stop_at_patch:
                break
            continue
        if is_broken(patch_file):
            print(f'Skipping broken patch: {patch_file}')
            skipped_patches.append(patch_file)
            continue
        patch(patch_file, silent=True)
        applied_patches.append(patch_file)

    # Set checkpoint
    if applied_patches:
        with temp_cd('..'):
            run('make first-checkpoint')

    # Set message for patch result
    patch_broken = is_broken(selected_patch)
    if patch_broken:
        message = "Broken patch has been applied to the workspace.\n\nPLEASE FIX THE FOLLOWING:\n"
    else:
        message = "Successfully applied patch to the workspace.\n"

    # Run the selected patch
    patch_result = os.popen(f'patch -p1 -i "{selected_patch}"').read()

    # Find any line containing a file .rej
    if patch_broken:
        for line in patch_result.splitlines():
            if file := re.search(r'[^\s]+\.rej', line):
                message += f'> {file[0]}' + '\n'

    def msg_format_paths(file_list):
        message = ''
        for patch_file in file_list:
            message += '> ' + patch_file[len('../patches/') :] + '\n'
        return message

    # Show which patches were applied if not all patches were allowed
    if stop_at_patch and applied_patches:
        message += f'\n{"-" * 22} Applied patches {"-" * 22}\n'
        message += msg_format_paths(applied_patches)

    if skipped_patches:
        message += f'\n{"-" * 17} Skipped patches (broken!) {"-" * 17}\n'
        message += msg_format_paths(skipped_patches)

    message += f'\n{"-" * 24} Full output {"-" * 24}\n{patch_result}'
    easygui.textbox("Patch Result", "Patch Result", message)


def check_patch(patch_file):
    """
    Checks if the patch can be applied or can be reversed
    Returns (can_apply, can_reverse, is_broken)
    """
    can_apply = not bool(
        os.system(f'patch -p1 --dry-run --force -i "{patch_file}" > /dev/null 2>&1')
    )
    can_reverse = not bool(
        os.system(f'patch -p1 -R --dry-run --force -i "{patch_file}" > /dev/null 2>&1')
    )
    return can_apply, can_reverse, not (can_apply or can_reverse)


def is_broken(patch_file):
    """Check if a patch file is broken"""
    _, _, is_broken = check_patch(patch_file)
    return is_broken


def get_rejects(patch_file):
    """Get rejects from a patch file"""
    cmd = f'patch -p1 -i "{patch_file}" | tee /dev/stderr | sed -n -E \'s/^.*saving rejects to file (.*\\.rej)$/\\1/p\''
    result = os.popen(cmd).read().strip()
    return result.split('\n') if result else []


# GUI Choicebox with options
choices = [
    "Reset workspace",
    "Edit a patch",
    "Create new patch",
    "\u2014" * 44,
    "List patches currently applied",
    "Select patches",
    "Reverse patches",
    "Find broken patches (resets workspace)",
    "\u2014" * 44,
    "See current workspace",
    "Write workspace to patch",
    "Set checkpoint",
]

"""
GUI Choicebox
"""


def handle_choice(choice):
    """Handle UI choice"""
    match choice:
        case "Reset workspace":
            reset_camoufox()
            easygui.msgbox(
                "Reset. All patches & changes have been removed.",
                "Reset Complete",
            )

        case "Create new patch":
            # Reset camoufox, apply all patches, then create a checkpoint
            reset_camoufox()
            with temp_cd('..'):
                run('make dir')
                run('make first-checkpoint')
            easygui.msgbox(
                "Created new patch workspace. You can test Camoufox with 'make run'.\n\n"
                "When you are finished, write your workspace back to a new patch.",
                "New Patch Workspace",
            )

        case "List patches currently applied":
            # Produces a list of patches that are applied
            apply_dict = {}
            for patch_file in list_patches():
                print(f'FILE: {patch_file}')
                # Ignore bootstrap files, these will always break.
                if is_bootstrap_patch(patch_file):
                    apply_dict[patch_file] = 'IGNORED'
                    continue
                # Check if the patch can be applied or reversed
                can_apply, can_reverse, broken = check_patch(patch_file)
                if broken:
                    apply_dict[patch_file] = 'BROKEN'
                elif can_reverse:
                    apply_dict[patch_file] = 'APPLIED'
                elif can_apply:
                    apply_dict[patch_file] = 'NOT APPLIED'
                else:
                    apply_dict[patch_file] = 'UNKNOWN (broken .patch?)'
            easygui.textbox(
                "Patching Result",
                "Patching Result",
                '\n'.join(
                    sorted(
                        (
                            f'{v}\t{k[len("../patches/"):-len(".patch")]}'
                            for k, v in apply_dict.items()
                        ),
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
            result = run_patches(reverse=False)
            if result:
                easygui.msgbox("Patching completed.", "Patching Complete")
        
        case "Reverse patches":
            result = run_patches(reverse=True)
            if result:
                easygui.msgbox("Unpatching completed.", "Unpatching Complete")

        case "Find broken patches (resets workspace)":
            reset_camoufox()

            get_all = None

            broken_patches = []
            for patch_file in list_patches():
                print(f'Testing: {patch_file}')
                if reject_files := get_rejects(patch_file):
                    # Add the patch to the list
                    broken_patches.append((patch_file, reject_files))
                    # If get_all is None, ask the user if they want to get all the rejects
                    if get_all is None:
                        get_all = easygui.ynbox(
                            f"Reject was found: {patch_file}.\nGet the rest of them?",
                            "Get All Rejects",
                            choices=["Yes", "No"],
                        )
                    # If the user closed the dialog, return
                    if get_all is None:
                        return
                    # If the user said no, break the patch loop
                    if not get_all:
                        break

            if not broken_patches:
                easygui.msgbox("All patches applied successfully.", "Patching Result")
                return

            # Display message
            message = "Some patches failed to apply:\n\n"
            for patch_file, rejects in broken_patches:
                message += '> ' + patch_file[len('../patches/') :] + '\n'
            message += '\n\n\n'

            # Show file contents
            for patch_file, rejects in broken_patches:
                message += f"Patch: {patch_file[len('../patches/'):]}\nRejects:\n"
                for reject in rejects:
                    with open(reject, 'r') as f:
                        count = len(re.findall('^@@.*', f.read(), re.MULTILINE))
                    message += f"{count} reject(s) > {reject}\n"
                message += '\n'
            easygui.textbox("Patching Result", "Failed Patches", message)

        case "Edit a patch":
            patch_files = list_patches()
            ui_choices = []
            for n, file_name in enumerate(patch_files):
                # If the patch is bootstrap, label it
                if is_bootstrap_patch(file_name):
                    status = "BOOTSTRAP"
                else:
                    can_apply, can_reverse, broken = check_patch(file_name)
                    if broken:
                        status = "BROKEN"
                    elif can_reverse:
                        status = "APPLIED"
                    elif can_apply:
                        status = "NOT APPLIED"
                    else:
                        status = "UNKNOWN"
                display_name = f"{n+1}. [{status}] {file_name[len('../patches/'):]}".strip()
                ui_choices.append(display_name)
            
            selected_patch = easygui.choicebox(
                "Select patch to open in workspace",
                "Patches",
                ui_choices,
            )
            # Return if user cancelled
            if not selected_patch:
                return
            # Get file path of selected patch
            selected_patch = patch_files[ui_choices.index(selected_patch)]
            open_patch_workspace(
                selected_patch,
                # Patches starting with 0- rely on being ran first.
                stop_at_patch=is_bootstrap_patch(selected_patch),
            )

        case "See current workspace":
            result = os.popen('git diff').read()
            easygui.textbox("Diff", "Diff", result)

        case "Write workspace to patch":
            # Open a file dialog to select a file to write the diff to
            with temp_cd('../patches'):
                file_path = easygui.filesavebox(
                    "Select a file to write the patch to",
                    "Write Patch",
                    filetypes="*.patch",
                )
            if not file_path:
                exit()
            run(f'git diff first-checkpoint > {file_path}')
            easygui.msgbox(f"Patch has been written to {file_path}.", "Patch Written")

        case _:
            print('No choice selected')


if __name__ == "__main__":
    into_camoufox_dir()

    while choice := easygui.choicebox("Select an option:", "Camoufox Dev Tools", choices):
        handle_choice(choice)
