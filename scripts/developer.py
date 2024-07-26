import os

import easygui
from patch import list_files, patch, run

# Cd to the camoufox-* folder (this is located ..)
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
folders = os.listdir('.')
for folder in folders:
    if os.path.isdir(folder) and folder.startswith('camoufox-'):
        os.chdir(folder)
        break
else:
    raise Exception('No camoufox-* folder found')


"""
GUI Choicebox with the following options:
- Reset:
    `git checkout -- .`
    then patch *.bootstrap (required)
- Patch all BUT:
    Checklist of *.patch files in ../patches to exclude. The rest gets patched.
- Find broken:
    Resets, runs patches, then finds broken patches.
    If all show good error code, show at the top of the message box "All patches applied successfully"
    If any show bad error code, show at the top of the message box "Some patches failed to apply", then the rej output
"""


def reset_camoufox():
    run('git checkout -- .')
    for patch_file in list_files('../patches', suffix='*.bootstrap'):
        patch(patch_file)


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

choice = easygui.choicebox("Select an option:", "Camoufox Patcher", choices)

if choice == "Reset workspace":
    reset_camoufox()
    easygui.msgbox("Reset completed and bootstrap patches applied.", "Reset Complete")

elif choice == "Select patches":
    run_patches(reverse=False)
    easygui.msgbox("Patching completed.", "Patching Complete")

elif choice == "Reverse patches":
    run_patches(reverse=True)
    easygui.msgbox("Unpatching completed.", "Unpatching Complete")

elif choice == "Find broken patches":
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

elif choice == "See current workspace":
    result = os.popen('git diff').read()
    easygui.textbox("Diff", "Diff", result)

elif choice == "Write workspace to patch":
    # Open a file dialog to select a file to write the diff to
    file_path = easygui.filesavebox(
        "Select a file to write the diff to", "Write Diff", filetypes="*.patch"
    )
    if not file_path:
        exit()
    run(f'git diff > {file_path}')
    easygui.msgbox("Diff written to file", "Diff Written")
